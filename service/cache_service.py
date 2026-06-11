"""
模块名: service.cache_service
功能概述: 封装 Redis 缓存读写，并在 Redis 不可用时让业务层可继续尝试上游。
对外接口: RedisCacheService
依赖关系: redis.asyncio、Settings、GoldPrice
输入输出: 输入 GoldPrice，输出 latest 与 last_success 缓存。
异常与错误: Redis 异常在本层记录并返回空结果，不阻断上游刷新。
维护说明: 缓存 JSON 字段必须保持 Android 客户端契约，不写入密钥或上游 URL。
"""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from config import Settings
from model.gold_price import GoldPrice
from utils.logger import get_logger

logger = get_logger(__name__)


class RedisCacheService:
    """金价 Redis 缓存服务。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._redis: Redis | None = None

    async def latest(self, symbol: str) -> GoldPrice | None:
        """读取短 TTL 最新行情缓存。"""

        return await self._get_price(self._latest_key(symbol))

    async def last_success(self, symbol: str) -> GoldPrice | None:
        """读取最近一次成功行情缓存。"""

        return await self._get_price(self._last_success_key(symbol))

    async def store_success(self, price: GoldPrice) -> None:
        """写入 latest 与 last_success 缓存。"""

        payload = price.model_dump(mode="json")
        await self._set_json(
            self._latest_key(price.symbol),
            payload,
            self._settings.latest_cache_ttl_seconds,
        )
        await self._set_json(
            self._last_success_key(price.symbol),
            payload,
            self._settings.last_success_ttl_seconds,
        )

    async def mark_source_status(self, status: dict[str, Any]) -> None:
        """记录数据源状态，供健康检查使用。"""

        await self._set_json("gold:source:status", status, self._settings.last_success_ttl_seconds)

    async def source_status(self) -> dict[str, Any] | None:
        """读取最近一次数据源状态。"""

        value = await self._get_json("gold:source:status")
        return value if isinstance(value, dict) else None

    async def health(self) -> dict[str, Any]:
        """返回 Redis 健康状态。"""

        try:
            await self._client().ping()
            return {"ok": True, "url": self._safe_redis_url()}
        except RedisError as exc:
            logger.warning("redis health check failed: %s", exc.__class__.__name__)
            return {"ok": False, "url": self._safe_redis_url(), "error": exc.__class__.__name__}

    async def close(self) -> None:
        """关闭 Redis 连接。"""

        if self._redis is not None:
            await self._redis.aclose()

    async def _get_price(self, key: str) -> GoldPrice | None:
        value = await self._get_json(key)
        if not isinstance(value, dict):
            return None
        try:
            return GoldPrice.model_validate(value)
        except ValueError as exc:
            logger.warning("invalid cached gold price for %s: %s", key, exc.__class__.__name__)
            return None

    async def _get_json(self, key: str) -> Any | None:
        try:
            raw = await self._client().get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except (RedisError, json.JSONDecodeError) as exc:
            logger.warning("redis read failed for %s: %s", key, exc.__class__.__name__)
            return None

    async def _set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        try:
            await self._client().setex(key, ttl_seconds, json.dumps(value, ensure_ascii=False))
        except RedisError as exc:
            logger.warning("redis write failed for %s: %s", key, exc.__class__.__name__)

    def _client(self) -> Redis:
        if self._redis is None:
            self._redis = Redis.from_url(self._settings.redis_url, decode_responses=True)
        return self._redis

    def _safe_redis_url(self) -> str:
        return self._settings.redis_url.split("@")[-1]

    @staticmethod
    def _latest_key(symbol: str) -> str:
        return f"gold:latest:{symbol.upper()}"

    @staticmethod
    def _last_success_key(symbol: str) -> str:
        return f"gold:last_success:{symbol.upper()}"
