"""
Rate Limiter Middleware — stub placeholder.

Currently passes all requests through without any limiting.

## How to swap in Redis-backed sliding window limiting:

1. Add to requirements.txt:
       redis[asyncio]>=5.0

2. In main.py lifespan, initialize a Redis client:
       from redis.asyncio import Redis
       app.state.redis = await Redis.from_url("redis://redis:6379")

3. Replace the dispatch() body below with:

       import time
       WINDOW_SECONDS = 60
       MAX_REQUESTS = 60   # per window per IP

       client_ip = request.client.host
       key = f"ratelimit:{client_ip}:{int(time.time()) // WINDOW_SECONDS}"
       redis: Redis = request.app.state.redis

       count = await redis.incr(key)
       if count == 1:
           await redis.expire(key, WINDOW_SECONDS * 2)
       if count > MAX_REQUESTS:
           from fastapi.responses import JSONResponse
           return JSONResponse(
               {"detail": "Rate limit exceeded. Try again in a minute."},
               status_code=429,
           )
       return await call_next(request)

## How to swap in Upstash rate limiting:

1. Add: upstash-ratelimit
2. Follow Upstash SDK docs for sliding window limiter — wrap in dispatch().
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RateLimiterMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        # Stub: no limiting applied — swap implementation here
        return await call_next(request)
