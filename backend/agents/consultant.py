"""
EDA SQL Consultant — validates data availability before the SQL agent runs.

Flow (general-to-particular):
  Stage 1 — Broad probe: check the overall dataset (row count, date range).
  Stage 2 — Category probe: if search patterns exist, run a broad ILIKE query
             using ALL patterns (acronym-expanded) combined with OR.
  Stage 3 — Verdict based on results:
    • 0 rows in category probe  → ask a clarifying question (if partial match possible)
                               or declare infeasible + explanation
    • 1-4 distinct products    → proceed with those products pre-identified
    • 5-15 distinct products   → ask a clarifying question with options
    • 16+ results              → proceed (broad query, let SQL agent handle)

New SSE event types emitted:
  {"type": "consulting", "content": "..."}  — progress indicator
  {"type": "question", "content": "...", "options": [...]}  — clarifying question
  {"type": "text", "content": "..."}        — infeasibility explanation
  {"type": "done"}                          — terminal event (infeasible/question paths)

On proceed/partial: investigation_context is stored in state for sql_agent.
Fallback: any LLM call failure → "proceed" (non-blocking).
"""

import logging

from chat.prompts import build_consultant_explanation_prompt
from db.runner import QueryRunner
from llm import get_llm_provider
from sql.verifier import SQLVerificationError, SQLVerifier
from streaming import emit

from .state import AgentState

logger = logging.getLogger(__name__)

_ABBREV_NOTE = (
    "\n\n_Note: Some product names may use abbreviations or alternative spellings "
    "(e.g., DDL = Dulce de Leche). If results seem incomplete, try the full name "
    "or a different variation._"
)

# Maximum rows returned by the category probe (we only need distinct product names)
_PROBE_ROW_LIMIT = 30


def _build_cues_str(state: AgentState) -> str | None:
    lines: list[str] = []
    lang = state.get("detected_language")
    patterns = state.get("search_patterns") or []
    candidates = state.get("candidate_products") or []

    if lang:
        lines.append(f"Detected language: {'Spanish' if lang == 'es' else 'English'}")
    if patterns:
        lines.append(f"Search patterns (use in ILIKE): {', '.join(patterns)}")
    if candidates:
        lines.append(f"Candidate products: {', '.join(candidates[:10])}")
    return "\n".join(lines) if lines else None


def _format_results_block(log: list[dict]) -> str:
    parts = []
    for entry in log:
        q = entry.get("query", "")
        rc = entry.get("row_count", 0)
        rows = entry.get("rows", [])
        cols = entry.get("columns", [])
        if rows:
            sample = "; ".join(
                ", ".join(f"{c}={v}" for c, v in zip(cols, row)) for row in rows[:5]
            )
            parts.append(f"Query: {q}\nResult ({rc} rows): {sample}")
        else:
            parts.append(f"Query: {q}\nResult: 0 rows")
    return "\n\n".join(parts)


def _build_investigation_context(log: list[dict]) -> str:
    """Build a compact summary to inject into the SQL agent prompt."""
    lines = ["## Investigation Findings"]
    for entry in log:
        q = entry.get("query", "")
        rc = entry.get("row_count", 0)
        rows = entry.get("rows", [])
        cols = entry.get("columns", [])
        if rc == 0:
            lines.append(f"- `{q}` → 0 rows")
        elif rows and cols:
            sample_vals = [row[0] for row in rows[:5] if row]
            lines.append(
                f"- `{q}` → {rc} rows. Sample: {', '.join(str(v) for v in sample_vals)}"
            )
        else:
            lines.append(f"- `{q}` → {rc} rows")
    return "\n".join(lines)


async def _run_probe(
    sql: str, runner: QueryRunner, verifier: SQLVerifier
) -> dict | None:
    """Run a single probe query. Returns result dict or None on failure."""
    try:
        clean = verifier.verify(sql)
        return await runner.execute(clean)
    except (SQLVerificationError, ValueError, Exception) as e:
        logger.warning("Consultant probe failed: %s | SQL: %s", e, sql)
        return None


async def _generate_explanation(
    question: str,
    log: list[dict],
    has_product_filter: bool = False,
) -> str:
    """Ask the LLM to explain why the data is unavailable. Falls back to template."""
    abbrev = _ABBREV_NOTE if has_product_filter else ""
    try:
        llm = get_llm_provider()
        results_block = _format_results_block(log)
        system_prompt = build_consultant_explanation_prompt(
            question=question,
            results_block=results_block,
        )
        full = ""
        async for chunk in llm.stream_completion(
            system_prompt=system_prompt, messages=[], think=False
        ):
            full += chunk
        return full.strip() + abbrev
    except Exception as e:
        logger.warning("Explanation LLM call failed: %s", e)
        return "No data found matching your query." + abbrev


async def eda_consultant_node(state: AgentState) -> dict:  # noqa: PLR0912 PLR0915
    runner = QueryRunner()
    verifier = SQLVerifier()
    search_patterns = state.get("search_patterns") or []
    selected_tables = state.get("selected_tables") or ["sales"]

    await emit({"type": "consulting", "content": "Checking data availability..."})

    # ── Stage 1: Broad probe (always runs, no LLM) ────────────────────────
    # Use COUNT(*) only — no column references so it works on any table.
    table = selected_tables[0] if selected_tables else "sales"
    broad_sql = f"SELECT COUNT(*) AS total_rows FROM {table}"
    broad_result = await _run_probe(broad_sql, runner, verifier)

    log: list[dict] = []
    if broad_result is not None:
        log.append({"query": broad_sql, **broad_result})

    broad_count = 0
    if log and log[0].get("rows"):
        try:
            broad_count = int(log[0]["rows"][0][0] or 0)
        except (IndexError, TypeError, ValueError):
            broad_count = 0

    # No data at all in the DB (empty table)
    if broad_count == 0:
        explanation = await _generate_explanation(
            state["user_message"], log, has_product_filter=False
        )
        await emit({"type": "text", "content": explanation})
        await emit({"type": "done"})
        return {
            "investigation_log": log,
            "investigation_context": None,
            "consultant_verdict": "infeasible",
        }

    # No product-specific terms → data exists, proceed immediately.
    # General aggregate queries (totals, date ranges, etc.) don't need product validation.
    if not search_patterns:
        return {
            "investigation_log": log,
            "investigation_context": None,
            "consultant_verdict": "proceed",
        }

    # ── Stage 2: Category probe (only when search patterns exist) ─────────
    distinct_products: list[str] = []
    ilike_conditions = " OR ".join(f"product_name ILIKE '{p}'" for p in search_patterns)
    category_sql = (
        f"SELECT DISTINCT product_name, COUNT(*) AS cnt "
        f"FROM {table} "
        f"WHERE {ilike_conditions} "
        f"GROUP BY product_name "
        f"ORDER BY cnt DESC "
        f"LIMIT {_PROBE_ROW_LIMIT}"
    )
    category_result = await _run_probe(category_sql, runner, verifier)
    if category_result is not None:
        log.append({"query": category_sql, **category_result})
        if category_result["row_count"] > 0 and category_result["rows"]:
            distinct_products = [row[0] for row in category_result["rows"] if row]

    # ── Verdict ───────────────────────────────────────────────────────────
    # We had search patterns but found 0 matching products
    if not distinct_products:
        explanation = await _generate_explanation(
            state["user_message"], log, has_product_filter=True
        )
        await emit({"type": "text", "content": explanation})
        await emit({"type": "done"})
        return {
            "investigation_log": log,
            "investigation_context": None,
            "consultant_verdict": "infeasible",
        }

    # 5-15 distinct products → ask for clarification
    if search_patterns and 5 <= len(distinct_products) <= 15:
        q_content = (
            f"I found {len(distinct_products)} matching products. "
            "Which one are you interested in?"
        )
        options = distinct_products[:4]
        options.append("All of the above")

        await emit({"type": "question", "content": q_content, "options": options})
        await emit({"type": "done"})
        return {
            "investigation_log": log,
            "investigation_context": _build_investigation_context(log),
            "consultant_verdict": "question",
        }

    # 1-4 specific products or 16+ results (proceed)
    investigation_context = _build_investigation_context(log)

    # Emit a findings summary so the user can see what the data check found.
    if distinct_products:
        names = ", ".join(distinct_products[:4])
        extra = (
            f" (+{len(distinct_products) - 4} more)"
            if len(distinct_products) > 4
            else ""
        )
        summary = f"Found {len(distinct_products)} product(s): {names}{extra}"
        await emit({"type": "consulting", "content": summary})

    return {
        "investigation_log": log,
        "investigation_context": investigation_context,
        "consultant_verdict": "proceed",
    }
