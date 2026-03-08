"""
AWS Bedrock provider.

Uses the Bedrock Converse API — works with Claude, Titan, Llama, Mistral,
and all other models available on Bedrock via a single unified interface.

Required env vars:
    LLM_PROVIDER=bedrock
    LLM_MODEL=anthropic.claude-3-5-sonnet-20241022-v2:0   (or any Bedrock model ID)
    AWS_REGION=us-east-1

Auth (standard boto3 credential chain, in order of precedence):
    1. AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY env vars
    2. ~/.aws/credentials file
    3. IAM role attached to the instance / ECS task / Lambda

Dependency: boto3 (add to requirements.txt when using this provider)
"""

import asyncio
from typing import AsyncIterator

from config import settings
from .base import LLMProvider


class BedrockProvider(LLMProvider):
    def __init__(self) -> None:
        import boto3  # imported lazily — only needed when this provider is active
        self._client = boto3.client("bedrock-runtime", region_name=settings.aws_region)
        self._model_id = settings.llm_model or settings.bedrock_model_id

    async def stream_completion(
        self,
        system_prompt: str,
        messages: list[dict],
        *,
        think: bool = False,
    ) -> AsyncIterator[str]:
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        # Converse API message format
        converse_messages = [
            {"role": m["role"], "content": [{"text": m["content"]}]}
            for m in messages
        ]

        def _sync_stream() -> None:
            try:
                response = self._client.converse_stream(
                    modelId=self._model_id,
                    system=[{"text": system_prompt}],
                    messages=converse_messages,
                )
                for event in response["stream"]:
                    if "contentBlockDelta" in event:
                        delta = event["contentBlockDelta"]["delta"].get("text", "")
                        if delta:
                            loop.call_soon_threadsafe(queue.put_nowait, delta)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)  # sentinel

        loop.run_in_executor(None, _sync_stream)

        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            yield chunk

    async def health_check(self) -> bool:
        try:
            loop = asyncio.get_event_loop()
            # Light check: list models to verify credentials + region are valid
            await loop.run_in_executor(
                None,
                lambda: self._client.list_foundation_models(byOutputModality="TEXT"),
            )
            return True
        except Exception:
            return False
