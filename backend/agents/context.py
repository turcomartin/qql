"""
Context window management utilities.

Local models have limited context windows. We trim conversation history
to stay within a token budget, reserving space for the system prompt,
schema, current message, and the model's response.

Token estimation: len(text) // 4  (chars per token heuristic — good enough for local models)
"""

from config import settings


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def trim_history(
    history: list[dict],
    reserved_tokens: int = 1500,
) -> list[dict]:
    """
    Return a trimmed copy of history that fits within the context budget.

    Args:
        history: Full conversation history as [{"role": ..., "content": ...}].
        reserved_tokens: Tokens reserved for system prompt + schema + response.
                         History is allowed up to (MAX_CONTEXT_TOKENS - reserved_tokens).

    Returns:
        Trimmed history (most recent turns kept, oldest dropped).
    """
    budget = settings.max_context_tokens - reserved_tokens
    if budget <= 0:
        return []

    result: list[dict] = []
    used = 0

    # Walk backwards (newest first), add turns until budget exhausted
    for turn in reversed(history):
        tokens = estimate_tokens(turn.get("content", ""))
        if used + tokens > budget:
            break
        result.append(turn)
        used += tokens

    result.reverse()
    return result
