"""
Google Vertex AI provider (Gemini models).

Required env vars:
    LLM_PROVIDER=vertex
    GCP_PROJECT=my-gcp-project
    GCP_LOCATION=us-central1
    LLM_MODEL=gemini-1.5-pro   (or gemini-1.5-flash, gemini-2.0-flash-exp, etc.)

Auth (standard Google Application Default Credentials chain):
    1. GOOGLE_APPLICATION_CREDENTIALS env var pointing to a service account JSON key file
    2. gcloud auth application-default login (for local dev)
    3. Workload Identity / attached service account on GCE/GKE/Cloud Run

Dependency: google-cloud-aiplatform (add to requirements.txt when using this provider)
"""

import asyncio
from typing import AsyncIterator

from config import settings
from .base import LLMProvider


class VertexProvider(LLMProvider):
    def __init__(self) -> None:
        import vertexai  # imported lazily — only needed when this provider is active
        from vertexai.generative_models import GenerativeModel

        vertexai.init(project=settings.gcp_project, location=settings.gcp_location)
        self._GenerativeModel = GenerativeModel
        self._model_name = settings.llm_model or settings.vertex_model

    async def stream_completion(
        self,
        system_prompt: str,
        messages: list[dict],
        *,
        think: bool = False,
    ) -> AsyncIterator[str]:
        from vertexai.generative_models import Content, Part

        loop = asyncio.get_event_loop()
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        # Build Vertex chat history from all turns except the last (current user message)
        history = [
            Content(
                role="user" if m["role"] == "user" else "model",
                parts=[Part.from_text(m["content"])],
            )
            for m in messages[:-1]
        ]
        current_message = messages[-1]["content"] if messages else ""

        def _sync_stream() -> None:
            try:
                model = self._GenerativeModel(
                    self._model_name,
                    system_instruction=system_prompt,
                )
                chat = model.start_chat(history=history)
                responses = chat.send_message(current_message, stream=True)
                for response in responses:
                    if response.text:
                        loop.call_soon_threadsafe(queue.put_nowait, response.text)
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
            # Attempt a minimal model initialization to verify credentials
            self._GenerativeModel(self._model_name)
            return True
        except Exception:
            return False
