"""
Orchestrator Agent — classifies user intent.

Uses a minimal, cheap LLM call (no schema injected) to decide:
  "data" → route to SQL Agent
  "chat" → route to Conversation Agent
"""

from chat.prompts import build_orchestrator_system_prompt
from llm import get_llm_provider

from .state import AgentState


async def orchestrator_node(state: AgentState) -> dict:
    llm = get_llm_provider()
    system_prompt = build_orchestrator_system_prompt()

    full_response = ""
    async for chunk in llm.stream_completion(
        system_prompt=system_prompt,
        messages=[{"role": "user", "content": state["user_message"]}],
    ):
        full_response += chunk

    intent_raw = full_response.strip().lower()
    # Default to "data" — the EDA consultant handles infeasible queries gracefully,
    # so routing an ambiguous message to "data" is safer than routing a real data
    # question to "chat" (which gives an unhelpful response).
    intent = "chat" if "chat" in intent_raw and "data" not in intent_raw else "data"

    return {"intent": intent}
