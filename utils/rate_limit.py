"""
模块名: utils.rate_limit
功能概述: 提供应用层内存限流中间件，降低公开接口被刷风险。
对外接口: InMemoryRateLimitMiddleware
依赖关系: Starlette
输入输出: 输入客户端请求，超限时输出 429 JSON。
异常与错误: 内存状态随进程重启清空，多实例部署需升级为 Redis 限流。
维护说明: MVP 单实例足够；正式多实例部署应迁移到 Nginx 或 Redis。
"""

from __future__ import annotations

from collections import defaultdict, deque
from time import monotonic
from typing import Deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class InMemoryRateLimitMiddleware(BaseHTTPMiddleware):
    """基于客户端 IP 的分钟级内存限流。"""

    def __init__(self, app, requests_per_minute: int) -> None:
        super().__init__(app)
        self._requests_per_minute = requests_per_minute
        self._hits: dict[str, Deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next) -> Response:
        if self._requests_per_minute <= 0:
            return await call_next(request)

        client = request.client.host if request.client else "unknown"
        now = monotonic()
        hits = self._hits[client]
        while hits and now - hits[0] > 60:
            hits.popleft()
        if len(hits) >= self._requests_per_minute:
            return JSONResponse(
                status_code=429,
                content={"code": 429, "message": "too many requests", "data": None},
            )
        hits.append(now)
        return await call_next(request)
