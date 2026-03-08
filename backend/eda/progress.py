"""
EDA progress event system.

Maintains live state for an in-progress EDA run as a sequence of named
phases.  The EDA agent calls ``emit()`` as it moves through each phase;
the ``GET /eda/events`` SSE endpoint subscribes and streams those events
to the browser so the UI can render a live checklist.

Phases (in order):
    discover  — discover the primary table from information_schema
    profile   — profile every column (stat queries)
    interpret — single LLM call to produce semantic sections
    context   — write data_context.md to disk
    skill     — infer abbreviations + write skill.md

Each phase cycles through statuses: pending → start → update* → done|skip
``update`` events carry a changing ``detail`` string (e.g. column name)
without changing the overall phase status to "done".

A synthetic ``__done__`` event is emitted after the last phase to signal
SSE subscribers that the run is fully complete.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

# ── Phase catalogue ───────────────────────────────────────────────────────────

PHASE_KEYS = ["discover", "profile", "interpret", "context", "skill"]

# ── Module-level state ────────────────────────────────────────────────────────

_phase_states: dict[str, dict] = {}
_subscribers: list[asyncio.Queue] = []
_cancel_requested: bool = False


def _init_states() -> None:
    global _phase_states
    _phase_states = {k: {"status": "pending", "detail": ""} for k in PHASE_KEYS}


_init_states()


# ── Public API ────────────────────────────────────────────────────────────────

def reset() -> None:
    """Clear all phase states and cancel flag.  Call at the very start of each EDA run."""
    global _cancel_requested
    _cancel_requested = False
    _init_states()
    for q in _subscribers:
        # Drain any stale events from a previous run so late-joining clients
        # don't receive a burst of old data.
        while not q.empty():
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                break


def request_cancel() -> None:
    """Signal that the current EDA run should stop at the next checkpoint."""
    global _cancel_requested
    _cancel_requested = True


def is_cancel_requested() -> bool:
    """Return True if a cancellation has been requested for the current run."""
    return _cancel_requested


def get_snapshot() -> list[dict]:
    """Return the current phase states for SSE clients that connect mid-run."""
    return [
        {
            "phase": k,
            "status": _phase_states.get(k, {}).get("status", "pending"),
            "detail": _phase_states.get(k, {}).get("detail", ""),
        }
        for k in PHASE_KEYS
    ]


async def emit(phase: str, status: str, detail: str = "") -> None:
    """
    Update a phase's persisted state and push an event to all subscribers.

    status values:
      ``start``  — phase has begun (spinner shown in UI)
      ``update`` — progress within a running phase (detail changes, no tick)
      ``done``   — phase completed successfully (green checkmark)
      ``skip``   — phase was skipped / unavailable (dash shown)
    """
    if phase not in _phase_states:
        return

    # "update" keeps the "start" status so the spinner stays; only detail changes.
    if status == "update":
        _phase_states[phase]["detail"] = detail
    else:
        _phase_states[phase] = {"status": status, "detail": detail}

    event = {"phase": phase, "status": status, "detail": detail}
    _broadcast(event)


async def emit_done() -> None:
    """
    Signal that the EDA run is fully complete.  Sends a synthetic
    ``__done__`` event that the SSE endpoint converts to ``{"type": "done"}``.
    """
    _broadcast({"phase": "__done__", "status": "done", "detail": ""})


async def emit_cancelled() -> None:
    """
    Signal that the EDA run was cancelled by the user.  Sends a synthetic
    ``__cancelled__`` event that the SSE endpoint converts to
    ``{"type": "cancelled"}``.
    """
    _broadcast({"phase": "__cancelled__", "status": "cancel", "detail": ""})


def _broadcast(event: dict) -> None:
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            logger.debug("EDA progress queue full — dropping event for one subscriber")


def subscribe() -> "asyncio.Queue[dict]":
    """Register a new SSE subscriber and return its event queue."""
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subscribers.append(q)
    return q


def unsubscribe(q: "asyncio.Queue[dict]") -> None:
    """Remove a subscriber queue (called when the SSE connection closes)."""
    try:
        _subscribers.remove(q)
    except ValueError:
        pass
