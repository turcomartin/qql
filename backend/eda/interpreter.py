"""
LLM interpretation of profiling results.

Takes a :class:`TableProfile` and makes a **single** LLM call to produce
the semantic sections of ``data_context.md`` (Business Domain, Column Guide,
Taxonomy, Key Metrics, Business Rules, Data Quality Notes).

If the LLM call fails for any reason, the caller falls back to the
template-only renderer — this module is strictly non-fatal.
"""

from __future__ import annotations

import logging
import re

from eda.profiler import ColumnKind, ColumnProfile, TableProfile

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_INTERPRET_SYSTEM = (
    "You are a concise data documentation writer. Given raw profiling results "
    "from a database table, produce a structured data context document. "
    "Be factual — only state what the data shows."
)

_INTERPRET_USER = """\
Table: {table_name} ({row_count:,} rows)

Column profiles:
{column_summaries}
{pair_section}
Respond in EXACTLY this markdown format (keep each section to 1-4 lines):

## Business Domain
1-2 sentences describing what this table stores and its likely business context.

## Column Guide
For each column, one line: `column_name` — description (include units, format, domain meaning, and note if the column has a non-zero stddev that implies wide price variance or outliers).

## Taxonomy
Group the text values into meaningful categories. Only include columns with 5+ distinct text values.
Format: **Category Name**: value1, value2, value3

## Key Metrics
3-5 pre-computed reference facts useful for validating SQL results (e.g. busiest day with count, \
top product with count, typical price range, date span). Include actual numbers from the profiles.

## Business Rules
List 3-5 actionable SQL filter patterns derived from value ranges, null patterns, and data semantics.
Format exactly — one rule per line: Description: `SQL expression or WHERE clause`
Examples: Returns/refunds: `quantity < 0`, Revenue per line: `quantity * unitary_price`
Derive only from the column data above — do not invent rules that the data does not support.

## Data Quality Notes
For each column with Null > 0% or a suspicious min/max (e.g. price = 0, negative quantities), \
write one line noting the null rate and when to add IS NOT NULL.
If no issues are found, write: No significant quality issues detected.
"""


# ---------------------------------------------------------------------------
# Column summary builder (fed into the prompt)
# ---------------------------------------------------------------------------

def _summarize_column(cp: ColumnProfile) -> str:
    """Render a single :class:`ColumnProfile` into compact text for the prompt."""
    lines = [f"- {cp.name} ({cp.data_type}, {cp.kind.value}, {cp.n_distinct} distinct)"]

    if cp.null_pct > 0:
        lines.append(f"  Null: {cp.null_pct:.1f}%")

    if cp.kind == ColumnKind.NUMERIC:
        stat_line = (
            f"  Range: {cp.min_val} to {cp.max_val}, "
            f"Avg: {cp.avg_val}, Median: {cp.median_val}"
        )
        if cp.stddev:
            stat_line += f", Stddev: {cp.stddev}"
        lines.append(stat_line)
        lines.append(f"  P25: {cp.p25_val}, P75: {cp.p75_val}")

    elif cp.kind == ColumnKind.TEXT:
        if cp.all_values is not None:
            vals_str = ", ".join(cp.all_values[:30])
            lines.append(f"  All values: {vals_str}")
        elif cp.top_values is not None:
            top_str = ", ".join(f"{v} ({c})" for v, c in cp.top_values[:20])
            lines.append(f"  Top by freq: {top_str}")
        elif cp.prefixes is not None:
            lines.append(f"  Prefixes: {', '.join(cp.prefixes)}")

    elif cp.kind == ColumnKind.TEMPORAL:
        lines.append(f"  Range: {cp.min_date} to {cp.max_date}")
        if cp.dow_distribution:
            dow_str = ", ".join(f"{d}: {c}" for d, c in cp.dow_distribution)
            lines.append(f"  By DOW: {dow_str}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

_SECTION_RE = re.compile(r"## ([\w\s]+)\n(.*?)(?=\n## |\Z)", re.DOTALL)


def parse_llm_sections(text: str) -> dict[str, str]:
    """Parse the LLM response into ``{section_title: body}``."""
    sections: dict[str, str] = {}
    for m in _SECTION_RE.finditer(text):
        title = m.group(1).strip()
        body = m.group(2).strip()
        if body:
            sections[title] = body
    return sections


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def interpret_profile(profile: TableProfile) -> dict[str, str] | None:
    """
    Run a single LLM call to interpret profiling results.

    Returns a ``{section_title: markdown_body}`` dict on success, or
    ``None`` if the LLM call fails or produces no usable sections.
    """
    from llm import get_llm_provider

    column_summaries = "\n".join(_summarize_column(cp) for cp in profile.columns)

    pair_lines: list[str] = []
    if profile.numeric_pairs:
        pair_lines.append("\nNumeric pair analysis:")
        for p in profile.numeric_pairs:
            pair_lines.append(f"- {p['expression']}: avg={p['avg']}, min={p['min']}, max={p['max']}")
    pair_section = "\n".join(pair_lines)

    user_prompt = _INTERPRET_USER.format(
        table_name=profile.table_name,
        row_count=profile.row_count,
        column_summaries=column_summaries,
        pair_section=pair_section,
    )

    llm = get_llm_provider()

    # Quick connectivity check — skip LLM call immediately if unreachable
    # rather than waiting for the full connect timeout.
    if not await llm.health_check():
        logger.warning("LLM not reachable — skipping interpretation (will use fallback)")
        return None

    full = ""
    try:
        async for chunk in llm.stream_completion(
            system_prompt=_INTERPRET_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
            think=False,
        ):
            full += chunk
    except Exception:
        logger.warning("LLM interpretation call failed", exc_info=True)
        return None

    if not full.strip():
        logger.warning("LLM interpretation returned empty response")
        return None

    sections = parse_llm_sections(full)
    if not sections:
        logger.warning("LLM interpretation returned no parseable sections")
        return None

    logger.info("LLM interpretation produced %d sections: %s", len(sections), list(sections.keys()))
    return sections
