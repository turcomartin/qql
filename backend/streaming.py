"""
Per-request SSE streaming via a ContextVar-backed asyncio.Queue.

Usage (in route handler):
    queue = asyncio.Queue()
    token = set_queue(queue)
    asyncio.create_task(run_graph_and_put_sentinel(queue, token))
    async for event in drain(queue):
        yield f"data: {json.dumps(event)}\\n\\n"

Usage (in agent nodes):
    from streaming import emit
    await emit({"type": "consulting", "content": "..."})
"""

import asyncio
import contextvars

_queue: contextvars.ContextVar[asyncio.Queue] = contextvars.ContextVar("stream_queue")


async def emit(event: dict) -> None:
    """Push an SSE event to the current request's queue. No-op if no queue is set."""
    try:
        await _queue.get().put(event)
    except LookupError:
        pass  # called outside of a request context (e.g. tests)


def set_queue(q: "asyncio.Queue[dict | None]") -> contextvars.Token:
    """Bind a queue to the current async context. Returns a token for reset."""
    return _queue.set(q)


def reset_queue(token: contextvars.Token) -> None:
    """Remove the queue binding after the request completes."""
    _queue.reset(token)
