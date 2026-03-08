"""
Render ``data_context.md`` from profiling data with optional LLM interpretation.

Two paths:

* **Interpreted** — LLM-generated semantic sections (Business Domain, Taxonomy,
  Key Metrics, Business Rules …) followed by the mechanically generated Column
  Overview, Value Reference, and Statistics.  This is the primary path.

* **Fallback** — no LLM sections; just Dataset Overview + Column Overview +
  Value Reference + Statistics + Notes.  Equivalent to the legacy output but
  table-agnostic.

Both paths always end with the user-owned ``## Notes`` section so custom
annotations are preserved across regenerations.
"""

from __future__ import annotations

from datetime import datetime, timezone

from eda.profiler import ColumnKind, ColumnProfile, TableProfile

_NOTES_HEADER = "## Notes"
_DEFAULT_NOTES = "<!-- Add domain knowledge here. This section is never overwritten. -->"

# Threshold for "high cardinality" label in the Column Overview table
_HIGH_CARDINALITY = 500


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _header(profile: TableProfile) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"# Data Context: {profile.table_name}\n\n"
        f"_Auto-generated. Your **Notes** are preserved across regenerations._\n\n"
        f"Last updated: {now}\n"
    )


def _dataset_overview(profile: TableProfile) -> str:
    lines = [
        "## Dataset Overview",
        f"- Table: {profile.table_name}",
        f"- Total rows: {profile.row_count:,}",
    ]
    # Date range (from first temporal column with a date component)
    for cp in profile.columns:
        if cp.kind == ColumnKind.TEMPORAL and cp.min_date:
            lines.append(f"- Date range: {cp.min_date} → {cp.max_date}")
            break
    return "\n".join(lines)


def _col_overview_row(cp: ColumnProfile) -> str:
    """Build a single markdown table row for the Column Overview."""
    # Distinct cell
    if cp.kind == ColumnKind.TEMPORAL:
        distinct_cell = "—"
    elif cp.n_distinct >= _HIGH_CARDINALITY:
        distinct_cell = "high"
    else:
        distinct_cell = str(cp.n_distinct)

    # Null% cell
    null_cell = f"{cp.null_pct:.1f}%" if cp.null_pct > 0 else "0%"

    # Range/Values summary cell
    if cp.kind == ColumnKind.NUMERIC:
        summary = f"{cp.min_val} – {cp.max_val}, avg {cp.avg_val}"
        if cp.stddev:
            summary += f", σ {cp.stddev}"
    elif cp.kind == ColumnKind.TEXT:
        if cp.all_values is not None:
            preview = ", ".join(cp.all_values[:5])
            if len(cp.all_values) > 5:
                preview += ", …"
            summary = preview
        elif cp.top_values is not None:
            summary = f"top: {cp.top_values[0][0]}"
        elif cp.prefixes is not None:
            summary = f"prefixes: {', '.join(cp.prefixes[:4])}"
        else:
            summary = "—"
    elif cp.kind == ColumnKind.TEMPORAL:
        if cp.min_date and cp.max_date:
            # Trim time component for readability (keep only date portion)
            min_d = cp.min_date.split(" ")[0].split("T")[0]
            max_d = cp.max_date.split(" ")[0].split("T")[0]
            summary = f"{min_d} → {max_d}"
        else:
            summary = "—"
    else:
        summary = "—"

    return f"| {cp.name} | {cp.data_type} | {distinct_cell} | {null_cell} | {summary} |"


def _column_overview(profile: TableProfile) -> str:
    """Compact markdown table — one row per column, all types."""
    header = (
        "## Column Overview\n"
        "| Column | Type | Distinct | Null% | Range / Values |\n"
        "|--------|------|----------|-------|----------------|"
    )
    rows = [_col_overview_row(cp) for cp in profile.columns]
    return header + "\n" + "\n".join(rows)


def _value_reference(profile: TableProfile) -> str:
    """Mechanically render Value Reference from column profiles."""
    parts: list[str] = ["## Value Reference"]

    for cp in profile.columns:
        if cp.kind == ColumnKind.TEXT:
            if cp.all_values is not None:
                vals = ", ".join(cp.all_values)
                parts.append(
                    f"### {cp.name}\n"
                    f"Distinct values ({cp.n_distinct}): {vals}"
                )
            elif cp.top_values is not None:
                names = ", ".join(v for v, _ in cp.top_values)
                parts.append(
                    f"### {cp.name}\n"
                    f"{cp.n_distinct} distinct values. Top {len(cp.top_values)} by frequency:\n"
                    f"{names}"
                )
            elif cp.prefixes is not None:
                pfx = ", ".join(cp.prefixes)
                parts.append(
                    f"### {cp.name}\n"
                    f"~{cp.n_distinct:,} distinct values (high-cardinality). "
                    f"Common prefixes: {pfx}. "
                    "Do not filter on this column unless the user provides an exact value."
                )

        elif cp.kind == ColumnKind.NUMERIC and cp.n_distinct <= 50:
            # Low-cardinality numerics (e.g. waiter IDs) — list range
            if cp.min_val is not None:
                parts.append(
                    f"### {cp.name}\n"
                    f"{cp.n_distinct} distinct integer values. "
                    f"Range: {cp.min_val} – {cp.max_val}"
                )

    return "\n\n".join(parts)


def _statistics(profile: TableProfile) -> str:
    """
    Render enhanced Statistics section.

    Numeric columns: Range, Avg, Stddev, Median, P25, P75, Distinct, Nulls
    Temporal columns: Date Ranges subsection with min → max for each.
    """
    parts: list[str] = ["## Statistics"]
    has_content = False

    # Numeric columns
    for cp in profile.columns:
        if cp.kind == ColumnKind.NUMERIC and cp.min_val is not None:
            distinct_str = (
                "high" if cp.n_distinct >= _HIGH_CARDINALITY else str(cp.n_distinct)
            )
            null_str = f"{cp.null_pct:.1f}%"
            row = (
                f"### {cp.name}\n"
                f"Range: {cp.min_val} – {cp.max_val}"
                f" | Avg: {cp.avg_val}"
            )
            if cp.stddev:
                row += f" | Stddev: {cp.stddev}"
            row += (
                f" | Median: {cp.median_val}"
                f" | P25: {cp.p25_val}"
                f" | P75: {cp.p75_val}"
                f" | Distinct: {distinct_str}"
                f" | Nulls: {null_str}"
            )
            parts.append(row)
            has_content = True

    # Temporal columns — date range subsection
    temporal_lines: list[str] = []
    for cp in profile.columns:
        if cp.kind == ColumnKind.TEMPORAL and cp.min_date:
            min_d = cp.min_date.split(" ")[0].split("T")[0]
            max_d = cp.max_date.split(" ")[0].split("T")[0] if cp.max_date else "?"
            null_note = f" ({cp.null_pct:.1f}% null)" if cp.null_pct > 0 else ""
            temporal_lines.append(f"- {cp.name}: {min_d} → {max_d}{null_note}")
    if temporal_lines:
        parts.append("### Date Ranges\n" + "\n".join(temporal_lines))
        has_content = True

    return "\n\n".join(parts) if has_content else ""


def _notes_section(existing_notes: str) -> str:
    notes = existing_notes.strip() if existing_notes else _DEFAULT_NOTES
    return f"{_NOTES_HEADER}\n{notes}"


# ---------------------------------------------------------------------------
# Public renderers
# ---------------------------------------------------------------------------

def render_value_reference(profile: TableProfile) -> str:
    """Return only the Value Reference section (used by the interpreter prompt too)."""
    return _value_reference(profile)


def render_interpreted(
    profile: TableProfile,
    llm_sections: dict[str, str],
    existing_notes: str,
) -> str:
    """Full data_context.md with LLM-interpreted sections + value reference."""
    parts: list[str] = [_header(profile)]

    # LLM-generated sections (in preferred order)
    section_order = [
        "Business Domain",
        "Column Guide",
        "Taxonomy",
        "Key Metrics",
        "Business Rules",
        "Data Quality Notes",
    ]
    for title in section_order:
        body = llm_sections.get(title)
        if body:
            parts.append(f"## {title}\n{body}")

    parts.append("---")
    parts.append(_dataset_overview(profile))
    parts.append("")
    parts.append(_column_overview(profile))
    parts.append("")
    parts.append(_value_reference(profile))

    stats = _statistics(profile)
    if stats:
        parts.append("")
        parts.append(stats)

    parts.append("\n---\n")
    parts.append(_notes_section(existing_notes))

    return "\n\n".join(parts) + "\n"


def render_fallback(profile: TableProfile, existing_notes: str) -> str:
    """Fallback data_context.md — no LLM sections, just profiled data."""
    parts: list[str] = [_header(profile)]

    parts.append("---")
    parts.append(_dataset_overview(profile))
    parts.append("")
    parts.append(_column_overview(profile))
    parts.append("")
    parts.append(_value_reference(profile))

    stats = _statistics(profile)
    if stats:
        parts.append("")
        parts.append(stats)

    parts.append("\n---\n")
    parts.append(_notes_section(existing_notes))

    return "\n\n".join(parts) + "\n"
