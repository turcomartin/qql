from fastapi import APIRouter

from config import settings
from llm import get_llm_provider

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    llm = get_llm_provider()
    llm_ok = await llm.health_check()
    return {
        "status": "ok" if llm_ok else "degraded",
        "llm": {
            "provider": settings.llm_provider,
            "model": settings.active_model,
            "reachable": llm_ok,
        },
    }
