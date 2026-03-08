"""
EDA routes.

POST /eda/refresh  — force-regenerate data_context.md and skill.md, invalidate caches.
POST /eda/cancel   — request cancellation of a running EDA agent.
GET  /eda/events   — SSE stream of live EDA phase progress events.
GET  /eda/context  — return the current data_context.md content as plain text.
GET  /eda/skill    — return skill.md content + parsed acronyms as JSON.
PUT  /eda/skill    — overwrite skill.md with user-supplied content, invalidate cache.
"""

import asyncio
import json
import logging
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from config import settings
from db.schema_inspector import invalidate_schema_cache
from eda import invalidate_cache, is_eda_running, run_eda_agent
from eda.agent import _write_skill_md
from eda import progress as _eda_progress
from nlp.preprocessor import reload_models
from nlp.variations import invalidate_acronym_cache

router = APIRouter(prefix="/eda", tags=["eda"])

_SKILL_SECTION_RE = re.compile(r"## Acronym Mappings\n(.*?)(?=\n## |\Z)", re.DOTALL)
_SKILL_ROW_RE = re.compile(r"^\|\s*([^|\-][^|]*?)\s*\|\s*([^|]+?)\s*\|", re.MULTILINE)
_SKILL_NOTES_RE = re.compile(r"## Notes\n(.*?)$", re.DOTALL)


def _parse_skill(content: str) -> dict:
    """Return {"acronyms": [...], "notes": "..."} parsed from skill.md content."""
    acronyms: list[dict] = []
    seen: set[tuple[str, str]] = set()
    section = _SKILL_SECTION_RE.search(content)
    if section:
        for m in _SKILL_ROW_RE.finditer(section.group(1)):
            acronym = m.group(1).strip()
            expansion = m.group(2).strip()
            if (
                acronym
                and expansion
                and acronym.lower() not in ("acronym", "none")
                and expansion.lower() not in ("expansion", "—", "-")
                and not set(acronym.replace(" ", "")).issubset({"-"})
                and "(none found" not in acronym.lower()
            ):
                key = (acronym.lower(), expansion.lower())
                if key in seen:
                    continue
                seen.add(key)
                acronyms.append(
                    {"acronym": acronym.strip().upper(), "expansion": expansion.strip()}
                )

    notes = ""
    notes_m = _SKILL_NOTES_RE.search(content)
    if notes_m:
        notes = notes_m.group(1).strip()
        if notes.startswith("<!--"):
            notes = ""

    return {"acronyms": acronyms, "notes": notes}


def _extract_skill_rows(content: str) -> tuple[list[tuple[str, str]], str]:
    """Return (rows, notes) from skill.md content with duplicates removed."""
    parsed = _parse_skill(content)
    rows = [(r["acronym"], r["expansion"]) for r in parsed["acronyms"]]
    return rows, parsed["notes"]


class SkillUpdateRequest(BaseModel):
    content: str


@router.get("/status")
async def get_eda_status():
    """
    Return whether the EDA agent is currently running and how many acronyms
    have been learned so far (based on the current skill.md on disk).
    """
    skill_path = Path(settings.skill_path)
    acronym_count = 0
    if skill_path.exists():
        try:
            content = skill_path.read_text(encoding="utf-8")
            parsed = _parse_skill(content)
            acronym_count = len(parsed["acronyms"])
        except OSError:
            pass
    return {"running": is_eda_running(), "acronym_count": acronym_count}


@router.get("/events")
async def eda_events(request: Request) -> StreamingResponse:
    """
    SSE stream of EDA phase progress events.

    Immediately sends a ``snapshot`` message with the current state of all
    phases, then streams ``phase`` messages as the EDA agent advances through
    each stage.  A final ``done`` message is sent when the run completes.

    Event shapes:
      {"type": "snapshot", "phases": [{"phase": str, "status": str, "detail": str}, ...]}
      {"type": "phase",    "phase": str, "status": str, "detail": str}
      {"type": "done"}
    """

    async def generate():
        # ── Snapshot: current phase states for late-joining clients ──────────
        snapshot = _eda_progress.get_snapshot()
        yield f"data: {json.dumps({'type': 'snapshot', 'phases': snapshot})}\n\n"

        if not is_eda_running():
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        q = _eda_progress.subscribe()
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=2.0)
                    if event.get("phase") == "__done__":
                        yield f"data: {json.dumps({'type': 'done'})}\n\n"
                        break
                    if event.get("phase") == "__cancelled__":
                        yield f"data: {json.dumps({'type': 'cancelled'})}\n\n"
                        break
                    yield f"data: {json.dumps({'type': 'phase', **event})}\n\n"
                except asyncio.TimeoutError:
                    # Check whether EDA finished between events (e.g. fast run
                    # or a crash that never emitted the __done__ sentinel).
                    if not is_eda_running():
                        yield f"data: {json.dumps({'type': 'done'})}\n\n"
                        break
                    # Keep the connection alive with an SSE comment heartbeat.
                    yield ": heartbeat\n\n"
        finally:
            _eda_progress.unsubscribe(q)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # prevent nginx from buffering SSE
        },
    )


@router.post("/refresh")
async def refresh_eda():
    """
    Force-regenerate data_context.md and skill.md from the live database and
    invalidate the schema and NLP caches so the next request picks up fresh data.
    """
    path = Path(settings.eda_context_path)
    try:
        invalidate_cache()
        invalidate_schema_cache()
        reload_models()
        await run_eda_agent(
            path=path, max_age_hours=settings.eda_max_age_hours, force=True
        )
        return {"status": "ok", "path": str(path)}
    except Exception as exc:
        logger.error("EDA refresh failed: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc)},
        )


@router.post("/cancel")
async def cancel_eda():
    """
    Request cancellation of the currently running EDA agent.

    The agent will stop at the next checkpoint (between phases or between
    LLM stream chunks) and emit a ``cancelled`` SSE event to all listeners.
    Returns 409 if no EDA run is in progress.
    """
    if not is_eda_running():
        return JSONResponse(
            status_code=409, content={"detail": "No EDA run in progress"}
        )
    _eda_progress.request_cancel()
    return {"status": "cancel_requested"}


@router.get("/context", response_class=PlainTextResponse)
async def get_context():
    """Return the contents of data_context.md as plain text."""
    path = Path(settings.eda_context_path)
    if not path.exists():
        return PlainTextResponse(
            "data_context.md has not been generated yet. Call POST /eda/refresh.",
            status_code=404,
        )
    return PlainTextResponse(path.read_text(encoding="utf-8"))


@router.get("/skill")
async def get_skill():
    """
    Return skill.md content and parsed acronym table.

    Response: {"content": str, "acronyms": [{"acronym": str, "expansion": str}], "notes": str}
    """
    path = Path(settings.skill_path)
    if not path.exists():
        return {"content": "", "acronyms": [], "notes": ""}
    content = path.read_text(encoding="utf-8")
    parsed = _parse_skill(content)
    return {"content": content, **parsed}


@router.put("/skill")
async def put_skill(body: SkillUpdateRequest):
    """
    Overwrite skill.md with the user-supplied Markdown content and invalidate
    the acronym cache so the NLP system picks up the new mappings immediately.
    """
    path = Path(settings.skill_path)
    try:
        rows, notes = _extract_skill_rows(body.content)
        _write_skill_md(path, rows, notes)
        invalidate_acronym_cache()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok"}
