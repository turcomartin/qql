import asyncpg

from config import settings
from .connection import get_pool


class QueryTimeoutError(Exception):
    """Raised when a query exceeds QUERY_TIMEOUT_SECONDS. Non-retryable."""


class QueryRunner:
    async def execute(self, sql: str) -> dict:
        """
        Run a validated SELECT query using the read-only DB connection.

        Returns:
            {
                "columns": list[str],
                "rows": list[list],
                "row_count": int,      # total rows before truncation
                "truncated": bool,     # True if result was capped at MAX_QUERY_ROWS
            }

        Raises:
            QueryTimeoutError: if the query exceeds QUERY_TIMEOUT_SECONDS (non-retryable)
            ValueError: on other Postgres execution errors (retryable by SQL Agent)
        """
        timeout_ms = settings.query_timeout_seconds * 1000
        pool = get_pool()

        async with pool.acquire() as conn:
            conn: asyncpg.Connection
            await conn.execute(f"SET statement_timeout = {timeout_ms}")
            try:
                records = await conn.fetch(sql)
            except asyncpg.QueryCanceledError:
                raise QueryTimeoutError(
                    f"Query exceeded the {settings.query_timeout_seconds}s timeout. "
                    "Try narrowing the date range, adding a LIMIT, or simplifying the query."
                )
            except asyncpg.PostgresError as e:
                raise ValueError(f"Query execution error: {e.message}") from e
            finally:
                await conn.execute("RESET statement_timeout")

        if not records:
            return {"columns": [], "rows": [], "row_count": 0, "truncated": False}

        columns = list(records[0].keys())
        total = len(records)
        truncated = total > settings.max_query_rows
        rows = [
            [str(v) if v is not None else None for v in r.values()]
            for r in records[: settings.max_query_rows]
        ]

        return {
            "columns": columns,
            "rows": rows,
            "row_count": total,
            "truncated": truncated,
        }
