import json
import logging
from typing import AsyncIterator

import httpx

from config import settings
from .base import LLMProvider, THINKING_PREFIX

logger = logging.getLogger(__name__)

# Separate connect vs. read timeouts.  The connect timeout is short so we
# fail fast when Ollama is unreachable, while the read timeout is generous
# to accommodate slow LLM generation on consumer hardware.
_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)


class OllamaProvider(LLMProvider):
    def __init__(self, model: str = "") -> None:
        self.base_url = settings.ollama_base_url
        # Explicit model arg overrides settings, e.g. for skill inference
        # (EDA_SKILL_MODEL) while the main provider uses a different model.
        self.model = model or settings.llm_model or settings.ollama_model

    async def stream_completion(
        self,
        system_prompt: str,
        messages: list[dict],
        *,
        think: bool = False,
    ) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "stream": True,
            "think": think,
            "options": {
                "temperature": settings.temperature,
                "top_p": settings.top_p,
                "top_k": settings.top_k,
                "min_p": settings.min_p,
                "presence_penalty": settings.presence_penalty,
                "repetition_penalty": settings.repetition_penalty,
            },
        }
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    msg = chunk.get("message", {})

                    # Native thinking tokens (Qwen3, DeepSeek-R1, QwQ, etc.)
                    # Yielded with THINKING_PREFIX so callers can distinguish.
                    thinking = msg.get("thinking", "")
                    if think and thinking:
                        yield THINKING_PREFIX + thinking

                    # Regular content tokens
                    content = msg.get("content", "")
                    if content:
                        yield content

                    if chunk.get("done"):
                        break

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{self.base_url}/api/tags")
                return r.status_code == 200
        except Exception:
            return False
