"""
Business Analyst Reasoning Node — runs between the EDA Consultant and the SQL Agent.

When the consultant confirms data exists (verdict: proceed/partial), this node streams
a brief structured analysis visible in real-time:
  ## Business Angle    — what the user is really trying to learn
  ## SQL Challenge     — tricky aspects of translating this to SQL
  ## Approach          — how to best answer the query

Assistant prefill ("## Business Angle\\n") is passed as the last message so the
model is forced to continue from that point — no preamble can appear before the
first section header.

New SSE events emitted:
  {"type": "thinking", "content": "...chunk..."}  — streaming analyst text
  {"type": "thinking_done"}                        — analysis complete

The full streamed text is parsed into a compact "analyst_context" summary that is
injected into the SQL agent's system prompt to guide query generation.

Fallback: any LLM failure → emit thinking_done immediately, return analyst_context=None.
The SQL agent still runs — this node is fully non-blocking.
"""

import logging
import re

from chat.prompts import build_analyst_prompt
from db.schema_inspector import get_schema_description
from llm import get_llm_provider
from streaming import emit

from .state import AgentState

logger = logging.getLogger(__name__)

# Regex to pull content from each section
_ALL_SECTIONS_RE = re.compile(
    r"#{1,2}\s*(Business Angle|Ángulo de Negocio|SQL Challenge|Desafío SQL|Approach|Enfoque)\s*\n(.*?)(?=#{1,2}|\Z)",
    re.DOTALL | re.IGNORECASE,
)

# Normalised English section keys used in analyst_context
_SECTION_KEYS = {
    "business angle": "Business",
    "sql challenge": "Challenge",
    "approach": "Approach",
}

# The prefill text is emitted immediately and passed to the model so it is forced
# to continue from the first section header with no preamble.
_ANALYST_PREFILL = "## Business Angle\n"


def _extract_analyst_context(text: str) -> str | None:
    """
    Parse the LLM's 3-section response into a compact summary for the SQL prompt.

    Output format:
        ## Analyst Notes
        Business: <first sentence>
        Challenge: <first sentence>
        Approach: <first sentence>
    """
    matches = _ALL_SECTIONS_RE.findall(text)
    if not matches:
        return None

    lines = ["## Analyst Notes"]
    for header, body in matches:
        key = _SECTION_KEYS.get(header.strip().lower())
        if not key:
            continue
        # Take first sentence only to keep the injection concise
        first = body.strip().split("\n")[0].split(". ")[0].strip()
        if first:
            lines.append(f"{key}: {first}")

    return "\n".join(lines) if len(lines) > 1 else None


async def analyst_node(state: AgentState) -> dict:
    """
    LangGraph node: stream business-analyst reasoning, then return analyst_context
    for injection into the SQL agent's system prompt.

    The assistant prefill (_ANALYST_PREFILL) is emitted immediately and passed as
    the last message in the conversation so the model continues from the first
    section header — it cannot generate preamble before it.
    """
    try:
        llm = get_llm_provider()
        schema = await get_schema_description()
        system_prompt = build_analyst_prompt(
            question=state["user_message"],
            schema=schema,
            investigation_context=state.get("investigation_context"),
        )

        # Emit the prefix immediately so the analyst block appears right away
        await emit({"type": "thinking", "content": _ANALYST_PREFILL})
        full_text = _ANALYST_PREFILL

        async for chunk in llm.stream_completion(
            system_prompt=system_prompt,
            messages=[{"role": "assistant", "content": _ANALYST_PREFILL}],
            think=False,
        ):
            full_text += chunk
            await emit({"type": "thinking", "content": chunk})

        await emit({"type": "thinking_done"})

        analyst_context = _extract_analyst_context(full_text)
        logger.debug("Analyst context extracted: %s", analyst_context)
        return {"analyst_context": analyst_context, "analyst_done": True}

    except Exception as exc:
        logger.warning("Analyst node failed (non-fatal): %s", exc)
        # Always close the thinking block so the UI doesn't hang
        await emit({"type": "thinking_done"})
        return {"analyst_context": None, "analyst_done": True}
