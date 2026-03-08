"""
SQL Agent — generates, verifies, and executes SQL queries.

Retry loop (up to MAX_SQL_RETRIES attempts):
  1. On first attempt: run NLP preprocessing to detect language and find
     candidate product names; store results in state for subsequent retries.
  2. Build prompt with schema + NLP cues + investigation context + previous error
  3. Stream LLM response → accumulate full text + stream "text" events
  4. Extract ```sql block
  5. Verify SQL (sqlglot AST)
  6. Execute query (asyncpg)
  7. Zero-row detection: 0 results → emit a cautious message + clarifying question
      instead of retrying automatically.
  8. On any error: increment attempt counter, set error context, loop back
  9. On timeout: immediately stop retrying (non-retryable)
  10. On success with rows: emit a natural-language summary, "sql", and "table"

Events emitted (appended to state["stream_events"]):
    {"type": "sql_thinking", "content": "..."} — SQL agent reasoning stream
    {"type": "sql_thinking_done"}              — SQL agent reasoning complete
    {"type": "text",  "content": "..."}         — streamed LLM response text
    {"type": "sql",   "content": "..."}         — validated SQL (for copy button)
    {"type": "table", "columns": [...], "rows": [...], "row_count": int, "truncated": bool}
    {"type": "question", "content": "...", "options": [...]} — clarifying question on 0 rows
    {"type": "error", "content": "..."}         — terminal error after all retries
    {"type": "done"}                            — always last
"""

import re

from chat.prompts import build_sql_answer_system_prompt, build_sql_system_prompt
from db.runner import QueryRunner, QueryTimeoutError
from db.schema_inspector import get_schema_description
from eda.agent import get_product_names
from llm import get_llm_provider
from llm.base import THINKING_PREFIX
from nlp.preprocessor import preprocess
from sql.verifier import SQLVerificationError, SQLVerifier
from streaming import emit

from .context import trim_history
from .state import AgentState

_SQL_BLOCK_RE = re.compile(r"```sql\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)

_RESULT_PREVIEW_LIMIT = 12


def _format_result_preview(result: dict) -> str:
    columns = result.get("columns") or []
    rows = result.get("rows") or []
    if not columns or not rows:
        return "(no rows)"

    header = " | ".join(str(col) for col in columns)
    line = " | ".join("---" for _ in columns)
    body_lines = []
    for row in rows[:_RESULT_PREVIEW_LIMIT]:
        body_lines.append(" | ".join(str(value) for value in row))
    return "\n".join([header, line, *body_lines])


def _build_zero_result_question(
    candidate_products: list[str],
    search_patterns: list[str],
) -> dict:
    content = (
        "I didn’t find any rows with those filters. "
        "Could you clarify the product or date range?"
    )
    default_options = [
        "Different product name",
        "Different date range",
        "Remove filters",
    ]

    options: list[str] = []
    if candidate_products:
        options = candidate_products[:4]
        options.append("None of these")
    elif search_patterns:
        options = [p.replace("%", "").strip() for p in search_patterns[:4]]
        options = [o for o in options if o]

    if not options:
        options = default_options

    return {"content": content, "options": options}


async def _summarize_result(
    question: str,
    sql: str,
    result: dict,
) -> str:
    try:
        llm = get_llm_provider()
        system_prompt = build_sql_answer_system_prompt()
        preview = _format_result_preview(result)
        row_count = result.get("row_count", 0)
        truncated = result.get("truncated", False)
        columns = result.get("columns") or []
        user_content = (
            f"User question: {question}\n"
            f"SQL: {sql}\n"
            f"Row count: {row_count}\n"
            f"Truncated: {truncated}\n"
            f"Columns: {', '.join(str(c) for c in columns)}\n"
            f"Rows preview:\n{preview}"
        )
        full = ""
        async for chunk in llm.stream_completion(
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": user_content}],
            think=False,
        ):
            full += chunk
        return full.strip()
    except Exception:
        row_count = result.get("row_count", 0)
        truncated = result.get("truncated", False)
        suffix = " (truncated)" if truncated else ""
        return f"The query returned {row_count} rows{suffix}."


def _build_cues(state: AgentState) -> str | None:
    """Build the Query Cues block from NLP preprocessing results stored in state."""
    lines: list[str] = []
    lang = state.get("detected_language")
    candidates = state.get("candidate_products") or []
    patterns = state.get("search_patterns") or []

    if lang:
        lang_label = "Spanish" if lang == "es" else "English"
        lines.append(f"Detected language: {lang_label}")
    if patterns:
        lines.append(f"Use these ILIKE patterns (OR-combined): {', '.join(patterns)}")
    if candidates:
        names = ", ".join(candidates)
        lines.append(f"Candidate product matches: {names}")
        lines.append(
            "Use these candidates in ILIKE filters. "
            "Do not invent product names not listed here or in the schema."
        )
    return "\n".join(lines) if lines else None


async def sql_agent_node(state: AgentState) -> dict:
    llm = get_llm_provider()
    verifier = SQLVerifier()
    runner = QueryRunner()

    schema = await get_schema_description()
    history = (
        trim_history(state["history"]) if state["mode"] == "conversational" else []
    )

    # ── NLP preprocessing (first attempt only) ────────────────────────────
    # On retries, we reuse the language/candidates already stored in state
    # to avoid redundant processing and keep the prompt stable.
    if state["sql_attempts"] == 0:
        nlp_result = preprocess(state["user_message"], get_product_names())
        detected_language = nlp_result["detected_language"]
        candidate_products = nlp_result["candidate_products"]
        search_patterns = nlp_result.get("search_patterns") or []
    else:
        detected_language = state.get("detected_language")
        candidate_products = state.get("candidate_products") or []
        search_patterns = state.get("search_patterns") or []

    # Rebuild state snapshot with NLP data so _build_cues works
    state_with_nlp: AgentState = {  # type: ignore[misc]
        **state,
        "detected_language": detected_language,
        "candidate_products": candidate_products,
        "search_patterns": search_patterns,
    }
    cues = _build_cues(state_with_nlp)

    error_context = state.get("last_error")
    investigation_context = state.get("investigation_context")
    analyst_context = state.get("analyst_context")
    system_prompt = build_sql_system_prompt(
        schema,
        error_context,
        cues,
        investigation_context=investigation_context,
        analyst_context=analyst_context,
    )
    messages = history + [{"role": "user", "content": state["user_message"]}]

    # ── Stream LLM response ───────────────────────────────────────────────
    # Emit each token directly as it arrives — real-time text streaming.
    # When thinking mode is enabled, native thinking tokens are streamed as
    # "sql_thinking" events so SQL reasoning is separated from analyst.
    full_response = ""
    has_thinking = False

    async for chunk in llm.stream_completion(
        system_prompt=system_prompt, messages=messages, think=False, 
    ):
        if chunk.startswith(THINKING_PREFIX):
            has_thinking = True
            await emit({"type": "sql_thinking", "content": chunk[1:]})
        else:
            # Close thinking block before first content token
            if has_thinking:
                await emit({"type": "sql_thinking_done"})
                has_thinking = False
            full_response += chunk
            await emit({"type": "text", "content": chunk})

    if has_thinking:
        await emit({"type": "sql_thinking_done"})
        has_thinking = False

    # ── Extract SQL block ─────────────────────────────────────────────────
    match = _SQL_BLOCK_RE.search(full_response)
    if not match:
        error_msg = (
            "No SQL code block found in response. Please include a ```sql block."
        )
        return {
            "sql_attempts": state["sql_attempts"] + 1,
            "last_error": error_msg,
            "last_sql": None,
            "detected_language": detected_language,
            "candidate_products": candidate_products,
            "search_patterns": search_patterns,
        }

    raw_sql = match.group(1).strip()

    # ── Verify SQL ────────────────────────────────────────────────────────
    try:
        clean_sql = verifier.verify(raw_sql)
    except SQLVerificationError as e:
        error_msg = str(e)
        return {
            "sql_attempts": state["sql_attempts"] + 1,
            "last_error": f"SQL verification failed: {error_msg}",
            "last_sql": raw_sql,
            "detected_language": detected_language,
            "candidate_products": candidate_products,
            "search_patterns": search_patterns,
        }

    # ── Execute query ─────────────────────────────────────────────────────
    try:
        result = await runner.execute(clean_sql)
    except QueryTimeoutError as e:
        # Non-retryable — tell the user to simplify the query
        await emit({"type": "error", "content": str(e)})
        await emit({"type": "done"})
        return {
            "sql_attempts": state["sql_attempts"] + 1,
            "last_sql": clean_sql,
            "last_error": None,  # don't retry on timeout
            "is_timeout": True,
            "detected_language": detected_language,
            "candidate_products": candidate_products,
            "search_patterns": search_patterns,
        }
    except ValueError as e:
        error_msg = str(e)
        return {
            "sql_attempts": state["sql_attempts"] + 1,
            "last_error": f"Query execution error: {error_msg}",
            "last_sql": clean_sql,
            "detected_language": detected_language,
            "candidate_products": candidate_products,
            "search_patterns": search_patterns,
        }

    # ── Zero-row handling ─────────────────────────────────────────────────
    # If the query returns 0 rows, be cautious and ask for clarification.
    if result["row_count"] == 0:
        question = _build_zero_result_question(
            candidate_products,
            search_patterns,
        )
        doubt_msg = (
            "The query returned no results. A filter likely doesn't match the data."
        )
        await emit({"type": "text", "content": doubt_msg})
        await emit({"type": "sql", "content": clean_sql})
        await emit({"type": "table", **result})
        await emit({"type": "question", **question})
        await emit({"type": "done"})

        return {
            "sql_attempts": state["sql_attempts"] + 1,
            "last_sql": clean_sql,
            "last_error": None,
            "detected_language": detected_language,
            "candidate_products": candidate_products,
            "search_patterns": search_patterns,
        }

    # ── Success ───────────────────────────────────────────────────────────
    summary = await _summarize_result(
        state["user_message"],
        clean_sql,
        result,
    )
    if summary:
        await emit({"type": "text", "content": summary})
    await emit({"type": "sql", "content": clean_sql})
    await emit({"type": "table", **result})
    await emit({"type": "done"})

    return {
        "sql_attempts": state["sql_attempts"] + 1,
        "last_sql": clean_sql,
        "last_error": None,
        "detected_language": detected_language,
        "candidate_products": candidate_products,
        "search_patterns": search_patterns,
    }
