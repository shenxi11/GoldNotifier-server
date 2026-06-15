"""
模块名: service.cache_service
功能概述: 封装 Redis 最新行情、最近成功行情、当天历史行情和每日汇总读写。
对外接口: RedisCacheService
依赖关系: redis.asyncio、Settings、GoldPrice、GoldHistoryPoint
输入输出: 输入 GoldPrice，输出 latest、last_success、history 与每日汇总缓存。
异常与错误: Redis 异常在本层记录并返回空结果，不阻断上游刷新。
维护说明: 缓存 JSON 字段必须保持 Android 客户端契约，不写入密钥或上游 URL。
"""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from config import Settings
from model.gold_history import GoldDailySummary, GoldHistoryPoint
from model.gold_price import GoldPrice
from utils.logger import get_logger
from utils.time_utils import date_string_from_timestamp, previous_date_string

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

    async def store_success(self, price: GoldPrice) -> GoldPrice:
        """写入历史缓存，并以本地历史汇总增强 latest 与 last_success。"""

        point = await self.append_history(price)
        enriched_price = await self._with_local_daily_prices(price, point)
        payload = enriched_price.model_dump(mode="json")
        await self._set_json(
            self._latest_key(enriched_price.symbol),
            payload,
            self._settings.latest_cache_ttl_seconds,
        )
        await self._set_json(
            self._last_success_key(enriched_price.symbol),
            payload,
            self._settings.last_success_ttl_seconds,
        )
        return enriched_price

    async def append_history(self, price: GoldPrice) -> GoldHistoryPoint | None:
        """把新鲜成功行情追加到当天历史 ZSet。"""

        if price.isStale or price.source.lower() == "cache" or price.price <= 0:
            return None
        point = GoldHistoryPoint.from_price(price, self._settings.timezone)
        date = date_string_from_timestamp(point.timestampMillis, self._settings.timezone)
        key = self._history_key(price.symbol, date)
        try:
            await self._client().zadd(
                key,
                {point.model_dump_json(): point.timestampMillis},
            )
            await self._client().expire(key, self._history_retention_seconds())
        except RedisError as exc:
            logger.warning("redis history write failed for %s: %s", key, exc.__class__.__name__)
            return None
        await self._upsert_daily_summary(price.symbol, date, point)
        return point

    async def history(
        self,
        symbol: str,
        date: str,
        start_millis: int | None,
        end_millis: int | None,
        limit: int,
    ) -> list[GoldHistoryPoint]:
        """读取指定日期或时间窗口的历史行情点。"""

        key = self._history_key(symbol, date)
        min_score: int | str = start_millis if start_millis is not None else "-inf"
        max_score: int | str = end_millis if end_millis is not None else "+inf"
        try:
            raw_values = await self._client().zrevrangebyscore(
                key,
                max_score,
                min_score,
                start=0,
                num=limit,
            )
        except RedisError as exc:
            logger.warning("redis history read failed for %s: %s", key, exc.__class__.__name__)
            return []

        points: list[GoldHistoryPoint] = []
        for raw_value in reversed(raw_values):
            try:
                points.append(GoldHistoryPoint.model_validate_json(raw_value))
            except ValueError as exc:
                logger.warning("invalid cached history point for %s: %s", key, exc.__class__.__name__)
        return points

    async def daily_summary(self, symbol: str, date: str) -> GoldDailySummary | None:
        """读取指定日期的每日行情汇总。"""

        key = self._daily_summary_key(symbol, date)
        value = await self._get_json(key)
        if not isinstance(value, dict):
            return None
        try:
            return GoldDailySummary.model_validate(value)
        except ValueError as exc:
            logger.warning("invalid cached daily summary for %s: %s", key, exc.__class__.__name__)
            return None

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

    async def _with_local_daily_prices(
        self,
        price: GoldPrice,
        point: GoldHistoryPoint | None,
    ) -> GoldPrice:
        date = self._date_for_price(price, point)
        today_summary = await self.daily_summary(price.symbol, date)
        previous_summary = await self.daily_summary(price.symbol, previous_date_string(date))

        open_price = today_summary.open if today_summary is not None else price.open
        high = today_summary.high if today_summary is not None else price.high
        low = today_summary.low if today_summary is not None else price.low
        prev_close = previous_summary.close if previous_summary is not None else price.prevClose
        change = round(price.price - prev_close, 2)
        change_percent = round((change / prev_close) * 100, 2) if prev_close > 0 else 0.0
        return price.model_copy(
            update={
                "open": round(open_price, 2),
                "prevClose": round(prev_close, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "change": change,
                "changePercent": change_percent,
            }
        )

    async def _upsert_daily_summary(self, symbol: str, date: str, point: GoldHistoryPoint) -> None:
        current = await self.daily_summary(symbol, date)
        if current is None:
            summary = GoldDailySummary(
                symbol=symbol.upper(),
                date=date,
                open=point.price,
                high=point.price,
                low=point.price,
                close=point.price,
                openTimestampMillis=point.timestampMillis,
                closeTimestampMillis=point.timestampMillis,
            )
        else:
            open_price = current.open
            open_timestamp = current.openTimestampMillis
            if point.timestampMillis < current.openTimestampMillis:
                open_price = point.price
                open_timestamp = point.timestampMillis

            close = current.close
            close_timestamp = current.closeTimestampMillis
            if point.timestampMillis >= current.closeTimestampMillis:
                close = point.price
                close_timestamp = point.timestampMillis

            summary = GoldDailySummary(
                symbol=symbol.upper(),
                date=date,
                open=open_price,
                high=max(current.high, point.price),
                low=min(current.low, point.price),
                close=close,
                openTimestampMillis=open_timestamp,
                closeTimestampMillis=close_timestamp,
            )
        await self._set_json(
            self._daily_summary_key(symbol, date),
            summary.model_dump(mode="json"),
            self._history_retention_seconds(),
        )

    def _date_for_price(self, price: GoldPrice, point: GoldHistoryPoint | None) -> str:
        if point is None:
            point = GoldHistoryPoint.from_price(price, self._settings.timezone)
        return date_string_from_timestamp(point.timestampMillis, self._settings.timezone)

    def _safe_redis_url(self) -> str:
        return self._settings.redis_url.split("@")[-1]

    @staticmethod
    def _latest_key(symbol: str) -> str:
        return f"gold:latest:{symbol.upper()}"

    @staticmethod
    def _last_success_key(symbol: str) -> str:
        return f"gold:last_success:{symbol.upper()}"

    @staticmethod
    def _history_key(symbol: str, date: str) -> str:
        return f"gold:history:{symbol.upper()}:{date}"

    @staticmethod
    def _daily_summary_key(symbol: str, date: str) -> str:
        return f"gold:daily_summary:{symbol.upper()}:{date}"

    def _history_retention_seconds(self) -> int:
        return max(self._settings.history_retention_days, 1) * 24 * 60 * 60
