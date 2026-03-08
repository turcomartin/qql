"""
Conversation Agent — handles general chat, clarifications, and non-data questions.

Does NOT inject the database schema (saves tokens for general conversation).
"""

from chat.prompts import build_chat_system_prompt
from llm import get_llm_provider
from llm.base import THINKING_PREFIX
from streaming import emit

from .context import trim_history
from .state import AgentState


async def conversation_agent_node(state: AgentState) -> dict:
    llm = get_llm_provider()
    system_prompt = build_chat_system_prompt()

    history = (
        trim_history(state["history"]) if state["mode"] == "conversational" else []
    )
    messages = history + [{"role": "user", "content": state["user_message"]}]

    has_thinking = False
    async for chunk in llm.stream_completion(
        system_prompt=system_prompt, messages=messages, think=True
    ):
        if chunk.startswith(THINKING_PREFIX):
            has_thinking = True
            await emit({"type": "thinking", "content": chunk[1:]})
        else:
            # Close the thinking block before the first content token
            if has_thinking:
                await emit({"type": "thinking_done"})
                has_thinking = False
            await emit({"type": "text", "content": chunk})

    # If the model only produced thinking tokens (edge case), close the block
    if has_thinking:
        await emit({"type": "thinking_done"})

    await emit({"type": "done"})

    return {"intent": "chat"}
