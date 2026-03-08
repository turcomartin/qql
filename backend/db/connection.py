import asyncpg

from config import settings

_pool: asyncpg.Pool | None = None


async def init_db_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=settings.db_dsn,
        min_size=2,
        max_size=10,
    )


async def close_db_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized — call init_db_pool() during lifespan")
    return _pool
