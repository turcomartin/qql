import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.middleware.rate_limiter import RateLimiterMiddleware
from api.routes.chat import router as chat_router
from api.routes.eda import router as eda_router
from api.routes.health import router as health_router
from api.routes.tables import router as tables_router
from config import settings
from db.connection import close_db_pool, init_db_pool
from eda import run_eda_agent

# Logging is configured via backend/log_config.json, passed to uvicorn with
# --log-config. The root logger (and all application loggers) emit to stdout
# at INFO level. To change the level, edit log_config.json or set LOG_LEVEL.
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db_pool()

    # Run the EDA agent to generate / refresh data_context.md.
    # This populates column value distributions into the file so the SQL
    # agent has accurate filter candidates, and warms the in-memory product
    # name cache used by the NLP preprocessor.
    try:
        await run_eda_agent(
            path=Path(settings.eda_context_path),
            max_age_hours=settings.eda_max_age_hours,
        )
        logger.info("EDA context ready at %s", settings.eda_context_path)
    except Exception as exc:  # noqa: BLE001
        # Non-fatal: the app still works without EDA context, just with less
        # accurate SQL generation on the first requests.
        logger.warning("EDA agent failed (non-fatal): %s", exc)

    yield
    await close_db_pool()


app = FastAPI(title="QQL Chat API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimiterMiddleware)

app.include_router(chat_router, prefix="/chat")
app.include_router(eda_router)
app.include_router(health_router)
app.include_router(tables_router)
