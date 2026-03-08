import asyncio
import json
import logging
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents.graph import compiled_graph
from agents.state import AgentState
from streaming import reset_queue, set_queue

router = APIRouter()
logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []
    mode: Literal["conversational", "oneshot"] = "conversational"
    selected_tables: list[str] = ["sales"]


@router.post("/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    """
    SSE endpoint for streaming chat responses.

    Events are pushed directly from agent nodes via streaming.emit() as they
    happen, so the client sees consulting indicators and LLM text in real-time.

    Event types:
      text          — incremental LLM text (stream into message bubble)
      sql           — validated SQL query (for copy button)
      table         — query results (columns, rows, row_count, truncated)
      error         — terminal error message
      consulting    — EDA consultant status indicator
      question      — clarifying question with options [{content, options}]
      thinking      — incremental analyst reasoning text
      thinking_done — analyst block complete (collapsible in UI)
    sql_thinking  — incremental SQL agent reasoning text
    sql_thinking_done — SQL reasoning block complete (collapsible in UI)
      done          — stream complete, unlock UI
    """
    initial_state: AgentState = {
        "user_message": req.message,
        "history": req.history,
        "mode": req.mode,
        "selected_tables": req.selected_tables,
        "intent": None,
        "detected_language": None,
        "candidate_products": [],
        "search_patterns": [],
        "investigation_log": [],
        "investigation_context": None,
        "consultant_verdict": None,
        "analyst_context": None,
        "analyst_done": False,
        "sql_attempts": 0,
        "last_sql": None,
        "last_error": None,
        "is_timeout": False,
    }

    async def event_generator():
        queue: asyncio.Queue[dict | None] = asyncio.Queue()
        token = set_queue(queue)

        async def run_graph():
            try:
                await compiled_graph.ainvoke(initial_state)
            except Exception as e:
                # Log the real error server-side for debugging.
                # Never show raw internal errors (e.g. LangGraph TypedDict messages) to the user.
                logger.error("Graph execution error: %s", e, exc_info=True)
                friendly = "An unexpected error occurred. Please try again."
                await queue.put({"type": "error", "content": friendly})
                await queue.put({"type": "done"})
            finally:
                # Put sentinel BEFORE reset so the outer loop can drain cleanly.
                # Do NOT call reset_queue here — asyncio.create_task() runs the
                # coroutine in a *copy* of the current Context, so the token
                # (created in the generator's context) cannot be reset here.
                await queue.put(None)

        asyncio.create_task(run_graph())

        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            # Reset in the same context where set_queue() was called.
            reset_queue(token)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # prevent nginx from buffering SSE
        },
    )
