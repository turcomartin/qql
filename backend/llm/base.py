from abc import ABC, abstractmethod
from typing import AsyncIterator

# Sentinel prefix for native thinking tokens in stream_completion output.
# When think=True, thinking-phase chunks are yielded with this prefix so
# callers can distinguish them from content.  The NUL byte never appears
# in normal LLM text.
THINKING_PREFIX = "\x00"


class LLMProvider(ABC):
    """
    Swappable LLM backend interface.

    To add a new provider:
    1. Create a new file in llm/ (e.g. openai_provider.py)
    2. Subclass LLMProvider and implement stream_completion + health_check
    3. Add a branch in llm/__init__.py get_llm_provider()
    4. Set LLM_PROVIDER=<name> in .env
    """

    @abstractmethod
    async def stream_completion(
        self,
        system_prompt: str,
        messages: list[dict],
        *,
        think: bool = False,
    ) -> AsyncIterator[str]:
        """
        Stream text chunks from the LLM.

        Args:
            system_prompt: Instructions injected before the conversation.
            messages: Conversation turns as [{"role": "user"|"assistant", "content": str}].
            think: Enable native chain-of-thought reasoning (Ollama thinking mode).
                   When True, thinking-phase chunks are yielded prefixed with
                   THINKING_PREFIX so callers can distinguish them from content.

        Yields:
            Raw text delta strings as they arrive from the model.
            If think=True, thinking tokens are prefixed with THINKING_PREFIX.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Returns True if the provider is reachable and ready to serve requests."""
        ...
