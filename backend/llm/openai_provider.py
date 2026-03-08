"""
OpenAI provider stub.

To implement:
1. pip install openai>=1.0
2. Add to requirements.txt
3. Implement stream_completion using the openai.AsyncOpenAI client
4. Set LLM_PROVIDER=openai and OPENAI_API_KEY in .env
"""
from typing import AsyncIterator

from config import settings
from .base import LLMProvider


class OpenAIProvider(LLMProvider):
    def __init__(self) -> None:
        self.model = settings.llm_model or settings.openai_model

    async def stream_completion(
        self,
        system_prompt: str,
        messages: list[dict],
        *,
        think: bool = False,
    ) -> AsyncIterator[str]:
        raise NotImplementedError("OpenAI provider not yet implemented")
        yield  # make this a generator

    async def health_check(self) -> bool:
        return False
