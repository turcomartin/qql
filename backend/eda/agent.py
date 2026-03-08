"""
EDA Agent — profiles any PostgreSQL table at startup and writes a rich
data_context.md combining LLM-interpreted semantic sections with mechanically
generated value references and statistics.

Re-runs only when the file is missing or older than EDA_MAX_AGE_HOURS.
Call run_eda_agent(force=True) to regenerate unconditionally (e.g. from
the /eda/refresh endpoint).

The Notes section at the bottom of the file is user-owned: it is read back
and re-inserted verbatim on every regeneration so custom annotations are
never lost.

After writing data_context.md, the EDA agent also calls the LLM to infer
acronym mappings from the product names and writes/merges skill.md.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from db.connection import get_pool
from eda import progress as _prog
from eda.profiler import ColumnKind, TableProfile, profile_table
from eda.interpreter import interpret_profile
from eda.renderer import render_interpreted, render_fallback

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory product name cache populated whenever the EDA agent runs.
# The NLP preprocessor reads this to build candidate matches.
# ---------------------------------------------------------------------------
_product_names_cache: list[str] | None = None
_week_days_cache: list[str] | None = None
_eda_running: bool = False


def is_eda_running() -> bool:
    """Return True while the EDA agent is actively running."""
    return _eda_running


_NOTES_HEADER = "## Notes"
_DEFAULT_NOTES = (
    "<!-- Add domain knowledge here. This section is never overwritten. -->"
)

# Regex to extract the existing Notes block content (header + everything after)
_NOTES_RE = re.compile(r"## Notes\n(.*?)$", re.DOTALL)


def get_product_names() -> list[str]:
    """Return the cached list of product names (most frequent first)."""
    return _product_names_cache or []


def get_week_days() -> list[str]:
    """Return the cached list of distinct week day values."""
    return _week_days_cache or []


def invalidate_cache() -> None:
    """Clear the in-memory caches — call after a forced EDA refresh."""
    global _product_names_cache, _week_days_cache
    _product_names_cache = None
    _week_days_cache = None


# ---------------------------------------------------------------------------
# Column-name heuristics for cache population
# ---------------------------------------------------------------------------

_PRODUCT_KEYWORDS = {"product", "name", "item", "description", "producto", "nombre"}
_DAY_KEYWORDS = {"day", "week", "dow", "dia", "día"}


def _populate_caches_from_profile(profile: TableProfile) -> None:
    """
    Populate in-memory caches from a freshly built TableProfile.

    Uses column-name heuristics so this works for any table schema, not
    just 'product_name' / 'week_day'.
    """
    global _product_names_cache, _week_days_cache

    for cp in profile.columns:
        col_lower = cp.name.lower()

        # Product / item names — text columns with medium cardinality
        if cp.kind == ColumnKind.TEXT and any(
            kw in col_lower for kw in _PRODUCT_KEYWORDS
        ):
            if cp.top_values is not None:
                _product_names_cache = [v for v, _ in cp.top_values]
            elif cp.all_values is not None:
                _product_names_cache = list(cp.all_values)

        # Day-of-week — text columns with low cardinality (≤10)
        if (
            cp.kind == ColumnKind.TEXT
            and cp.n_distinct <= 10
            and any(kw in col_lower for kw in _DAY_KEYWORDS)
        ):
            if cp.all_values is not None:
                _week_days_cache = list(cp.all_values)

    # If still None, leave them as None (empty list returned by getters).


# ---------------------------------------------------------------------------
# Table discovery
# ---------------------------------------------------------------------------


async def _resolve_table(conn) -> str:
    """Discover the primary user table from information_schema."""
    row = await conn.fetchval(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
        "ORDER BY table_name LIMIT 1"
    )
    return row or "sales"


# ---------------------------------------------------------------------------
# Skill file helpers
# ---------------------------------------------------------------------------

_SKILL_SECTION_RE = re.compile(r"## Acronym Mappings\n(.*?)(?=\n## |\Z)", re.DOTALL)
_SKILL_ROW_RE = re.compile(r"^\|\s*([^|\-][^|]*?)\s*\|\s*([^|]+?)\s*\|", re.MULTILINE)
_SKILL_NOTES_RE = re.compile(r"## Notes\n(.*?)$", re.DOTALL)


def _parse_skill_file(path: Path) -> tuple[list[tuple[str, str]], str]:
    """Return (acronym_rows, notes_str) from skill.md. Both empty if file missing."""
    if not path.exists():
        return [], ""
    content = path.read_text(encoding="utf-8")

    rows: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    section = _SKILL_SECTION_RE.search(content)
    if section:
        for m in _SKILL_ROW_RE.finditer(section.group(1)):
            acronym = m.group(1).strip()
            expansion = m.group(2).strip()
            if (
                acronym
                and expansion
                and acronym.lower() not in ("acronym", "none")
                and expansion.lower() not in ("expansion",)
                and not set(acronym.replace(" ", "")).issubset({"-"})
            ):
                key = (acronym.lower(), expansion.lower())
                if key not in seen:
                    seen.add(key)
                    rows.append((acronym.strip().upper(), expansion.strip()))

    notes = ""
    notes_m = _SKILL_NOTES_RE.search(content)
    if notes_m:
        notes = notes_m.group(1).strip()

    return rows, notes


def _write_skill_md(path: Path, rows: list[tuple[str, str]], notes: str) -> None:
    """Serialise skill.md from the given acronym rows and notes string."""
    seen: set[tuple[str, str]] = set()
    deduped: list[tuple[str, str]] = []
    for acronym, expansion in rows:
        key = (acronym.strip().lower(), expansion.strip().lower())
        if not acronym.strip() or not expansion.strip() or key in seen:
            continue
        seen.add(key)
        deduped.append((acronym.strip().upper(), expansion.strip()))

    table_rows = "\n".join(
        f"| {acr} | {exp} |"
        for acr, exp in sorted(deduped, key=lambda x: (x[0].upper(), x[1].upper()))
    )
    if not table_rows:
        table_rows = "| (none found yet) | — |"

    notes_content = (
        notes or "<!-- Add domain notes here. This section is never overwritten. -->"
    )

    content = f"""\
# QQL Skill File
> Auto-generated by the EDA agent. Edit freely — your changes are preserved across re-generations.

## Acronym Mappings
Abbreviations recognized in user queries and expanded for product search.

| Acronym | Expansion |
|---------|-----------|
{table_rows}

## Notes
{notes_content}
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


async def _infer_acronyms(product_names: list[str]) -> dict[str, str]:
    """Ask the LLM to identify abbreviations in the product name list."""
    from llm import get_skill_llm_provider

    llm = get_skill_llm_provider()
    names_text = "\n".join(f"- {n}" for n in product_names[:60])
    prompt = (
        f"Given these product names from a database:\n{names_text}\n\n"
        "Identify abbreviations or acronyms that appear in product names along with their "
        "full-form expansions. Only include cases where the abbreviation is clearly derived "
        "from or related to the full name (e.g. DDL = Dulce de Leche, CC = Coca Cola).\n\n"
        "Respond with one mapping per line in this EXACT format:\n"
        "ACRONYM: Full Expansion\n\n"
        "If none found, respond with only: NONE"
    )

    full = ""
    async for chunk in llm.stream_completion(
        system_prompt="You are a concise data analyst. List only clear abbreviation mappings.",
        messages=[{"role": "user", "content": prompt}],
        think=False,
    ):
        # Check cancel flag between chunks so a user stop is responsive
        if _prog.is_cancel_requested():
            logger.info("_infer_acronyms: cancel requested — aborting LLM stream")
            raise asyncio.CancelledError("EDA cancelled during acronym inference")
        full += chunk

    result: dict[str, str] = {}
    for line in full.strip().splitlines():
        line = line.strip()
        if not line or line.upper() == "NONE":
            continue
        if ":" in line:
            acronym, _, expansion = line.partition(":")
            acronym = acronym.strip()
            expansion = expansion.strip()
            # Hard quality filters — discard low-confidence or nonsensical outputs:
            #   • expansion starts with "[" → model couldn't determine a real expansion
            #   • acronym and expansion are the same string (case-insensitive)
            #   • expansion is a substring/superset of just the acronym with different casing
            if not expansion or expansion.startswith("["):
                continue
            if acronym.lower() == expansion.lower():
                continue
            # Sanity: acronym 2-8 chars, expansion meaningfully longer than acronym
            if acronym and 1 < len(acronym) <= 8 and len(expansion) > len(acronym) + 1:
                result[acronym.upper()] = expansion
    return result


async def _update_skill_file(
    product_names: list[str],
    skill_path: Path,
    llm_sections: "dict[str, str] | None" = None,
) -> None:
    """
    Infer acronyms via LLM, merge with existing skill.md, and write it back.

    ``llm_sections`` — optional sections dict from the interpret phase.  Used
    to auto-seed the Notes section when it is currently empty so users have
    useful starting content (Business Domain + Key Metrics).  User-edited
    notes are never overwritten.
    """
    from nlp.variations import invalidate_acronym_cache

    existing_rows, existing_notes = _parse_skill_file(skill_path)

    # Auto-seed Notes from LLM interpretation when the section is empty.
    # Pull the two most useful summaries; user can trim or extend freely.
    if not existing_notes and llm_sections:
        parts: list[str] = []
        if "Business Domain" in llm_sections:
            parts.append(llm_sections["Business Domain"])
        if "Key Metrics" in llm_sections:
            parts.append("Key metrics:\n" + llm_sections["Key Metrics"])
        if parts:
            existing_notes = "\n\n".join(parts)
            logger.info("Auto-seeding skill.md Notes from LLM interpretation")

    new_acronyms: dict[str, str] = {}
    try:
        from llm import get_skill_llm_provider

        llm = get_skill_llm_provider()
        if await llm.health_check():
            # Wrap with a timeout so a slow/hung LLM doesn't block indefinitely.
            # asyncio.CancelledError (from a user stop) is NOT caught here — it
            # propagates up to run_eda_agent() which handles it gracefully.
            new_acronyms = await asyncio.wait_for(
                _infer_acronyms(product_names), timeout=90.0
            )
        else:
            logger.warning(
                "Skill LLM (%s) not reachable — skipping acronym inference",
                llm.model if hasattr(llm, "model") else "?",
            )
    except asyncio.TimeoutError:
        logger.warning("Acronym inference timed out after 90 s — skipping")
    except Exception as exc:
        logger.warning("Acronym inference failed (non-fatal): %s", exc)

    # Merge: preserve ALL existing entries (user may have edited/added them);
    # add newly inferred ones only if the acronym is not already present.
    merged_rows = list(existing_rows)
    seen = {(a.lower(), e.lower()) for a, e in merged_rows}
    for acronym, expansion in new_acronyms.items():
        key = (acronym.lower(), expansion.lower())
        if key not in seen:
            seen.add(key)
            merged_rows.append((acronym.upper(), expansion))

    _write_skill_md(skill_path, merged_rows, existing_notes)
    invalidate_acronym_cache()
    logger.info(
        "Skill file updated at %s (%d acronym mappings)", skill_path, len(merged)
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def _check_cancel() -> None:
    """Raise asyncio.CancelledError if a user-initiated stop has been requested."""
    if _prog.is_cancel_requested():
        raise asyncio.CancelledError("EDA run cancelled by user")


async def run_eda_agent(
    path: Path,
    max_age_hours: int = 24,
    force: bool = False,
) -> None:
    """
    Run EDA against the database and write *path* (data_context.md).

    Skips if the file is recent enough (< max_age_hours old) unless
    force=True.  Always updates the in-memory product/week-day caches.
    """
    global _product_names_cache, _week_days_cache, _eda_running
    _eda_running = True
    try:
        await _run_eda_agent_inner(path=path, max_age_hours=max_age_hours, force=force)
    except asyncio.CancelledError:
        # User pressed Stop — emit the cancelled sentinel so SSE clients
        # know the run ended early (not via normal completion).
        logger.info("EDA run cancelled by user request")
        await _prog.emit_cancelled()
    finally:
        _eda_running = False


async def _run_eda_agent_inner(
    path: Path,
    max_age_hours: int = 24,
    force: bool = False,
) -> None:
    global _product_names_cache, _week_days_cache

    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    # Age check
    if not force and path.exists() and path.stat().st_size > 0:
        age_s = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
        if age_s < max_age_hours * 3600:
            # File is fresh — still populate in-memory caches from DB
            await _warm_caches()
            # Always generate skill.md on startup if it is missing or empty.
            from config import settings as _settings  # noqa: PLC0415

            skill_path = Path(_settings.skill_path)
            if not skill_path.exists() or skill_path.stat().st_size == 0:
                try:
                    await _update_skill_file(_product_names_cache or [], skill_path)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Skill file init on startup failed (non-fatal): %s", exc
                    )
            return

    # Preserve existing Notes block
    existing_notes = _DEFAULT_NOTES
    if path.exists():
        m = _NOTES_RE.search(path.read_text(encoding="utf-8"))
        if m:
            existing_notes = m.group(1).strip()

    # Reset progress state for this run so SSE clients see a fresh checklist.
    _prog.reset()

    # ── Phase: discover ────────────────────────────────────────────────────────
    pool = get_pool()
    await _prog.emit("discover", "start")
    async with pool.acquire() as conn:
        table_name = await _resolve_table(conn)
        logger.info("EDA: profiling table '%s'", table_name)
        await _prog.emit("discover", "done", f"Table: {table_name}")

        # ── Phase: profile ─────────────────────────────────────────────────────
        _check_cancel()
        await _prog.emit("profile", "start")

        async def _col_progress(col_name: str, done: int, total: int) -> None:
            if not _prog.is_cancel_requested():
                await _prog.emit("profile", "update", f"{col_name}  ({done}/{total})")

        profile = await profile_table(conn, table_name, progress_cb=_col_progress)
        await _prog.emit("profile", "done", f"{len(profile.columns)} columns")

    # Register discovered table with the SQL verifier
    try:
        from sql.verifier import set_known_tables

        set_known_tables(frozenset({profile.table_name}))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to register table with verifier: %s", exc)

    # Populate in-memory caches from profile
    _populate_caches_from_profile(profile)

    # ── Phase: interpret ───────────────────────────────────────────────────────
    _check_cancel()
    await _prog.emit("interpret", "start")
    llm_sections = None
    try:
        llm_sections = await interpret_profile(profile)
        await _prog.emit("interpret", "done")
    except Exception as exc:
        logger.warning("LLM interpretation failed (non-fatal): %s", exc)
        await _prog.emit("interpret", "skip", "LLM unavailable")

    # ── Phase: context — render + write data_context.md ───────────────────────
    _check_cancel()
    await _prog.emit("context", "start")
    if llm_sections:
        content = render_interpreted(profile, llm_sections, existing_notes)
    else:
        content = render_fallback(profile, existing_notes)

    path.write_text(content, encoding="utf-8")
    logger.info("data_context.md written to %s (%d chars)", path, len(content))
    await _prog.emit("context", "done")

    # ── Phase: skill — infer acronyms + write/merge skill.md ──────────────────
    # Note: _check_cancel() is intentionally NOT called here so that even if
    # the user stops during the skill phase, the data_context.md written above
    # is preserved and the skill.md gets at least a partial write.
    await _prog.emit("skill", "start")
    try:
        from config import settings as _settings

        await _update_skill_file(
            _product_names_cache or [],
            Path(_settings.skill_path),
            llm_sections=llm_sections,
        )
        await _prog.emit("skill", "done")
    except asyncio.CancelledError:
        # Re-raise so run_eda_agent() can emit the cancelled sentinel.
        raise
    except Exception as exc:
        logger.warning("Skill file update failed (non-fatal): %s", exc)
        await _prog.emit("skill", "skip", "failed")

    # Signal full completion to SSE subscribers.
    await _prog.emit_done()


async def _warm_caches() -> None:
    """Populate in-memory caches from DB without rewriting the file."""
    global _product_names_cache, _week_days_cache
    if _product_names_cache is not None and _week_days_cache is not None:
        return

    pool = get_pool()
    async with pool.acquire() as conn:
        table_name = await _resolve_table(conn)

        # Discover columns and find the right ones via heuristics
        from eda.profiler import (
            discover_columns,
            classify_column,
            _qi,
            ColumnKind as CK,
        )

        col_infos = await discover_columns(conn, table_name)

        if _product_names_cache is None:
            for ci in col_infos:
                col_lower = ci["name"].lower()
                kind = classify_column(ci["data_type"])
                if kind == CK.TEXT and any(kw in col_lower for kw in _PRODUCT_KEYWORDS):
                    rows = await conn.fetch(
                        f"SELECT {_qi(ci['name'])}::text, COUNT(*) AS cnt "
                        f"FROM {_qi(table_name)} WHERE {_qi(ci['name'])} IS NOT NULL "
                        f"GROUP BY {_qi(ci['name'])} ORDER BY cnt DESC LIMIT 100"
                    )  # noqa: S608
                    _product_names_cache = [r[0] for r in rows]
                    break

        if _week_days_cache is None:
            for ci in col_infos:
                col_lower = ci["name"].lower()
                kind = classify_column(ci["data_type"])
                if kind == CK.TEXT and any(kw in col_lower for kw in _DAY_KEYWORDS):
                    rows = await conn.fetch(
                        f"SELECT DISTINCT {_qi(ci['name'])}::text "
                        f"FROM {_qi(table_name)} WHERE {_qi(ci['name'])} IS NOT NULL "
                        f"ORDER BY 1"
                    )  # noqa: S608
                    vals = [r[0] for r in rows]
                    if len(vals) <= 10:
                        _week_days_cache = vals
                    break
