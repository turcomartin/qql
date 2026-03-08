"""
Table-agnostic SQL profiling engine.

Discovers columns from ``information_schema``, classifies each by data type,
and runs adaptive profiling queries (statistics, value distributions, temporal
patterns).  All work is pure SQL — no LLM calls — so reliability is near-100 %.

The output is a ``TableProfile`` dataclass consumed by the interpreter
(for LLM-generated semantic context) and the renderer (for the mechanically
generated Value Reference / Statistics sections of data_context.md).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class ColumnKind(Enum):
    NUMERIC = "numeric"
    TEXT = "text"
    TEMPORAL = "temporal"
    OTHER = "other"


_NUMERIC_TYPES = frozenset({
    "integer", "bigint", "smallint", "numeric", "decimal",
    "real", "double precision", "money",
})
_TEXT_TYPES = frozenset({
    "character varying", "text", "character", "name",
})
_TEMPORAL_TYPES = frozenset({
    "date",
    "timestamp without time zone",
    "timestamp with time zone",
    "time without time zone",
    "time with time zone",
})


def classify_column(data_type: str) -> ColumnKind:
    """Map a PostgreSQL ``data_type`` string to a :class:`ColumnKind`."""
    dt = data_type.lower()
    if dt in _NUMERIC_TYPES:
        return ColumnKind.NUMERIC
    if dt in _TEXT_TYPES:
        return ColumnKind.TEXT
    if dt in _TEMPORAL_TYPES:
        return ColumnKind.TEMPORAL
    return ColumnKind.OTHER


@dataclass
class ColumnProfile:
    name: str
    data_type: str
    kind: ColumnKind
    n_distinct: int = 0
    null_pct: float = 0.0

    # Numeric ---------------------------------------------------------------
    min_val: str | None = None
    max_val: str | None = None
    avg_val: str | None = None
    stddev: str | None = None
    median_val: str | None = None
    p25_val: str | None = None
    p75_val: str | None = None

    # Text ------------------------------------------------------------------
    all_values: list[str] | None = None               # cardinality ≤50
    top_values: list[tuple[str, int]] | None = None    # 51..500
    prefixes: list[str] | None = None                  # >500

    # Temporal --------------------------------------------------------------
    min_date: str | None = None
    max_date: str | None = None
    dow_distribution: list[tuple[str, int]] | None = None


@dataclass
class TableProfile:
    table_name: str
    row_count: int = 0
    columns: list[ColumnProfile] = field(default_factory=list)
    numeric_pairs: list[dict] = field(default_factory=list)
    date_column: str | None = None


# ---------------------------------------------------------------------------
# Schema discovery
# ---------------------------------------------------------------------------

async def discover_columns(conn, table: str) -> list[dict]:
    """Return column metadata from ``information_schema``."""
    rows = await conn.fetch(
        "SELECT column_name, data_type, is_nullable "
        "FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = $1 "
        "ORDER BY ordinal_position",
        table,
    )
    return [
        {
            "name": r["column_name"],
            "data_type": r["data_type"],
            "nullable": r["is_nullable"] == "YES",
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Per-column profiling
# ---------------------------------------------------------------------------

def _qi(name: str) -> str:
    """Quote a SQL identifier (double-quotes)."""
    return f'"{name}"'


async def _profile_numeric(conn, table: str, col: str) -> dict:
    row = await conn.fetchrow(f"""
        SELECT
            COUNT({_qi(col)})                                          AS non_null,
            COUNT(*) - COUNT({_qi(col)})                               AS null_count,
            COUNT(*)                                                   AS total,
            MIN({_qi(col)})::text                                      AS min_val,
            MAX({_qi(col)})::text                                      AS max_val,
            ROUND(AVG({_qi(col)})::numeric, 2)::text                   AS avg_val,
            ROUND(STDDEV_SAMP({_qi(col)})::numeric, 2)::text           AS stddev,
            ROUND((PERCENTILE_CONT(0.25)
                   WITHIN GROUP (ORDER BY {_qi(col)}))::numeric, 2)::text AS p25,
            ROUND((PERCENTILE_CONT(0.50)
                   WITHIN GROUP (ORDER BY {_qi(col)}))::numeric, 2)::text AS median,
            ROUND((PERCENTILE_CONT(0.75)
                   WITHIN GROUP (ORDER BY {_qi(col)}))::numeric, 2)::text AS p75
        FROM {_qi(table)}
    """)  # noqa: S608
    total = row["total"] or 1
    return {
        "null_pct": round(100.0 * (row["null_count"] or 0) / total, 1),
        "min_val": row["min_val"],
        "max_val": row["max_val"],
        "avg_val": row["avg_val"],
        "stddev": row["stddev"],
        "median_val": row["median"],
        "p25_val": row["p25"],
        "p75_val": row["p75"],
    }


async def _profile_text(conn, table: str, col: str, top_n: int) -> dict:
    # Cardinality + null count
    stats = await conn.fetchrow(f"""
        SELECT COUNT(DISTINCT {_qi(col)}) AS n_distinct,
               COUNT(*) - COUNT({_qi(col)}) AS null_count,
               COUNT(*) AS total
        FROM {_qi(table)}
    """)  # noqa: S608
    n_distinct = stats["n_distinct"]
    total = stats["total"] or 1
    null_pct = round(100.0 * (stats["null_count"] or 0) / total, 1)

    result: dict = {"n_distinct": n_distinct, "null_pct": null_pct}

    if n_distinct <= 50:
        rows = await conn.fetch(
            f"SELECT DISTINCT {_qi(col)}::text FROM {_qi(table)} "
            f"WHERE {_qi(col)} IS NOT NULL ORDER BY 1"
        )  # noqa: S608
        result["all_values"] = [r[0] for r in rows]
    elif n_distinct <= 500:
        rows = await conn.fetch(
            f"SELECT {_qi(col)}::text, COUNT(*) AS cnt "
            f"FROM {_qi(table)} WHERE {_qi(col)} IS NOT NULL "
            f"GROUP BY {_qi(col)} ORDER BY cnt DESC LIMIT $1",
            top_n,
        )  # noqa: S608
        result["top_values"] = [(r[0], r[1]) for r in rows]
    else:
        rows = await conn.fetch(
            f"SELECT DISTINCT split_part({_qi(col)}::text, ' ', 1) AS pfx "
            f"FROM {_qi(table)} WHERE {_qi(col)} IS NOT NULL "
            f"ORDER BY pfx LIMIT 20"
        )  # noqa: S608
        result["prefixes"] = [r[0] for r in rows if r[0]]

    return result


async def _profile_temporal(conn, table: str, col: str) -> dict:
    # Range + null pct
    rng = await conn.fetchrow(f"""
        SELECT
            MIN({_qi(col)})::text AS min_date,
            MAX({_qi(col)})::text AS max_date,
            ROUND(100.0 * (COUNT(*) - COUNT({_qi(col)})) / GREATEST(COUNT(*), 1), 1) AS null_pct
        FROM {_qi(table)}
    """)  # noqa: S608

    result: dict = {
        "min_date": rng["min_date"],
        "max_date": rng["max_date"],
        "null_pct": float(rng["null_pct"] or 0),
    }

    # Day-of-week distribution (skip for time-only columns)
    try:
        dow_rows = await conn.fetch(f"""
            SELECT TRIM(TO_CHAR({_qi(col)}, 'Day')) AS dow, COUNT(*) AS cnt
            FROM {_qi(table)}
            WHERE {_qi(col)} IS NOT NULL
            GROUP BY dow, EXTRACT(DOW FROM {_qi(col)})
            ORDER BY EXTRACT(DOW FROM {_qi(col)})
        """)  # noqa: S608
        result["dow_distribution"] = [(r["dow"], r["cnt"]) for r in dow_rows]
    except Exception:  # noqa: BLE001
        # TO_CHAR with 'Day' fails for time-without-date columns
        pass

    return result


async def profile_column(
    conn,
    table: str,
    col_info: dict,
    top_n: int = 30,
) -> ColumnProfile:
    """Profile a single column, adapting queries to its :class:`ColumnKind`."""
    name = col_info["name"]
    kind = classify_column(col_info["data_type"])
    cp = ColumnProfile(name=name, data_type=col_info["data_type"], kind=kind)

    if kind == ColumnKind.NUMERIC:
        stats = await _profile_numeric(conn, table, name)
        cp.null_pct = stats["null_pct"]
        cp.min_val = stats["min_val"]
        cp.max_val = stats["max_val"]
        cp.avg_val = stats["avg_val"]
        cp.stddev = stats["stddev"]
        cp.median_val = stats["median_val"]
        cp.p25_val = stats["p25_val"]
        cp.p75_val = stats["p75_val"]
        # n_distinct for numerics (useful for integer IDs)
        row = await conn.fetchrow(
            f"SELECT COUNT(DISTINCT {_qi(name)}) FROM {_qi(table)}"
        )  # noqa: S608
        cp.n_distinct = row[0]

    elif kind == ColumnKind.TEXT:
        stats = await _profile_text(conn, table, name, top_n)
        cp.n_distinct = stats["n_distinct"]
        cp.null_pct = stats["null_pct"]
        cp.all_values = stats.get("all_values")
        cp.top_values = stats.get("top_values")
        cp.prefixes = stats.get("prefixes")

    elif kind == ColumnKind.TEMPORAL:
        stats = await _profile_temporal(conn, table, name)
        cp.null_pct = stats["null_pct"]
        cp.min_date = stats["min_date"]
        cp.max_date = stats["max_date"]
        cp.dow_distribution = stats.get("dow_distribution")

    return cp


# ---------------------------------------------------------------------------
# Cross-column analysis
# ---------------------------------------------------------------------------

async def detect_numeric_pairs(
    conn,
    table: str,
    numeric_cols: list[ColumnProfile],
    max_pairs: int = 3,
) -> list[dict]:
    """Compute aggregate stats for products of numeric column pairs."""
    pairs: list[dict] = []
    done = 0
    for i, a in enumerate(numeric_cols):
        if done >= max_pairs:
            break
        for b in numeric_cols[i + 1:]:
            if done >= max_pairs:
                break
            try:
                row = await conn.fetchrow(f"""
                    SELECT
                        ROUND(AVG({_qi(a.name)} * {_qi(b.name)})::numeric, 2)::text AS avg_p,
                        ROUND(MIN({_qi(a.name)} * {_qi(b.name)})::numeric, 2)::text AS min_p,
                        ROUND(MAX({_qi(a.name)} * {_qi(b.name)})::numeric, 2)::text AS max_p
                    FROM {_qi(table)}
                    WHERE {_qi(a.name)} IS NOT NULL AND {_qi(b.name)} IS NOT NULL
                """)  # noqa: S608
                pairs.append({
                    "expression": f"{a.name} * {b.name}",
                    "avg": row["avg_p"],
                    "min": row["min_p"],
                    "max": row["max_p"],
                })
                done += 1
            except Exception:  # noqa: BLE001
                logger.debug("Numeric pair %s * %s failed, skipping", a.name, b.name)
    return pairs


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------

async def profile_table(
    conn,
    table_name: str,
    progress_cb=None,
) -> TableProfile:
    """
    Discover columns, profile each one, and run cross-column analysis.

    Individual column failures are logged and skipped — they never abort
    the full profiling run.

    Args:
        progress_cb: Optional async callable ``(col_name, done, total)``
            invoked after each column is profiled.  Used by the EDA agent
            to stream per-column progress events to the UI.
    """
    top_n = settings.eda_top_n_values
    max_pairs = settings.eda_max_numeric_pairs

    row_count = await conn.fetchval(f"SELECT COUNT(*) FROM {_qi(table_name)}")  # noqa: S608

    col_infos = await discover_columns(conn, table_name)
    logger.info(
        "Profiling table %s (%d rows, %d columns)",
        table_name, row_count, len(col_infos),
    )

    columns: list[ColumnProfile] = []
    done_count = 0
    for ci in col_infos:
        try:
            cp = await profile_column(conn, table_name, ci, top_n=top_n)
            columns.append(cp)
        except Exception:  # noqa: BLE001
            logger.warning("Profiling column %s.%s failed, skipping", table_name, ci["name"])
        finally:
            done_count += 1
            if progress_cb is not None:
                try:
                    await progress_cb(ci["name"], done_count, len(col_infos))
                except Exception:  # noqa: BLE001
                    pass  # never let a progress callback abort profiling

    # Identify primary date column for cross-column analysis
    temporal_cols = [c for c in columns if c.kind == ColumnKind.TEMPORAL]
    date_column = temporal_cols[0].name if temporal_cols else None

    # Numeric pair analysis
    numeric_cols = [c for c in columns if c.kind == ColumnKind.NUMERIC]
    pairs: list[dict] = []
    if len(numeric_cols) >= 2:
        try:
            pairs = await detect_numeric_pairs(conn, table_name, numeric_cols, max_pairs)
        except Exception:  # noqa: BLE001
            logger.warning("Numeric pair detection failed, skipping")

    return TableProfile(
        table_name=table_name,
        row_count=row_count,
        columns=columns,
        numeric_pairs=pairs,
        date_column=date_column,
    )
