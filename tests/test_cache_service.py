"""
模块名: tests.test_cache_service
功能概述: 验证 RedisCacheService 的最新行情、最近成功行情和历史行情缓存策略。
对外接口: 无
依赖关系: RedisCacheService、Settings、GoldPrice
输入输出: 输入 fake Redis 和模拟行情，断言写入 key、TTL 与历史查询结果。
异常与错误: 不依赖真实 Redis，避免网络或容器状态影响单元测试。
维护说明: 调整历史 key、TTL 或查询方向时同步更新这些断言。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from config import Settings
from model.gold_price import GoldPrice
from service.cache_service import RedisCacheService


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.sorted_sets: dict[str, dict[str, float]] = {}
        self.expirations: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def setex(self, key: str, ttl_seconds: int, value: str) -> None:
        self.values[key] = value
        self.expirations[key] = ttl_seconds

    async def zadd(self, key: str, mapping: dict[str, int]) -> None:
        entries = self.sorted_sets.setdefault(key, {})
        for member, score in mapping.items():
            entries[member] = float(score)

    async def expire(self, key: str, ttl_seconds: int) -> None:
        self.expirations[key] = ttl_seconds

    async def zrevrangebyscore(
        self,
        key: str,
        max_score: int | str,
        min_score: int | str,
        start: int = 0,
        num: int | None = None,
    ) -> list[str]:
        low = _score_value(min_score)
        high = _score_value(max_score)
        entries = [
            (member, score)
            for member, score in self.sorted_sets.get(key, {}).items()
            if low <= score <= high
        ]
        entries.sort(key=lambda item: item[1], reverse=True)
        if num is None:
            selected = entries[start:]
        else:
            selected = entries[start : start + num]
        return [member for member, _ in selected]

    async def ping(self) -> bool:
        return True


class RedisCacheServiceForTest(RedisCacheService):
    def __init__(self, settings: Settings, fake_redis: FakeRedis) -> None:
        super().__init__(settings)
        self._fake_redis = fake_redis

    def _client(self) -> FakeRedis:
        return self._fake_redis


def test_store_success_writes_latest_last_success_and_history() -> None:
    fake_redis = FakeRedis()
    cache = _cache(fake_redis)
    price = _price(price=885.72, server_time="2099-06-11 11:39:25")

    asyncio.run(cache.store_success(price))

    assert "gold:latest:XAU" in fake_redis.values
    assert "gold:last_success:XAU" in fake_redis.values
    history_key = "gold:history:XAU:2099-06-11"
    assert len(fake_redis.sorted_sets[history_key]) == 1
    assert fake_redis.expirations[history_key] == 2 * 24 * 60 * 60
    points = asyncio.run(cache.history("XAU", "2099-06-11", None, None, 2000))
    assert len(points) == 1
    assert points[0].price == 885.72
    assert points[0].timestampMillis == _timestamp("2099-06-11 11:39:25")


def test_store_success_skips_stale_and_cache_history_points() -> None:
    fake_redis = FakeRedis()
    cache = _cache(fake_redis)

    asyncio.run(cache.store_success(_price(price=885.72, source="cache")))
    asyncio.run(cache.store_success(_price(price=885.80, is_stale=True)))

    assert "gold:history:XAU:2099-06-11" not in fake_redis.sorted_sets


def test_history_returns_recent_limit_in_time_order_without_duplicates() -> None:
    fake_redis = FakeRedis()
    cache = _cache(fake_redis)
    first = _price(price=885.72, server_time="2099-06-11 11:39:25")
    second = _price(price=885.88, server_time="2099-06-11 11:39:28")
    third = _price(price=886.02, server_time="2099-06-11 11:39:31")

    asyncio.run(cache.store_success(first))
    asyncio.run(cache.store_success(second))
    asyncio.run(cache.store_success(third))
    asyncio.run(cache.store_success(third))

    points = asyncio.run(cache.history("XAU", "2099-06-11", None, None, 2))

    assert [point.price for point in points] == [885.88, 886.02]
    assert len(fake_redis.sorted_sets["gold:history:XAU:2099-06-11"]) == 3


def test_history_filters_time_window() -> None:
    fake_redis = FakeRedis()
    cache = _cache(fake_redis)

    asyncio.run(cache.store_success(_price(price=885.72, server_time="2099-06-11 11:39:25")))
    asyncio.run(cache.store_success(_price(price=885.88, server_time="2099-06-11 11:39:28")))
    asyncio.run(cache.store_success(_price(price=886.02, server_time="2099-06-11 11:39:31")))

    points = asyncio.run(
        cache.history(
            "XAU",
            "2099-06-11",
            _timestamp("2099-06-11 11:39:28"),
            _timestamp("2099-06-11 11:39:28"),
            2000,
        )
    )

    assert [point.price for point in points] == [885.88]


def _cache(fake_redis: FakeRedis) -> RedisCacheServiceForTest:
    return RedisCacheServiceForTest(
        settings=Settings(
            scheduler_enabled=False,
            history_retention_days=2,
            timezone="Asia/Shanghai",
        ),
        fake_redis=fake_redis,
    )


def _price(
    price: float,
    server_time: str = "2099-06-11 11:39:25",
    source: str = "finnhub",
    is_stale: bool = False,
) -> GoldPrice:
    return GoldPrice(
        name="现货黄金",
        symbol="XAU",
        price=price,
        change=0.0,
        changePercent=0.0,
        unit="元/克",
        open=price,
        prevClose=price,
        high=price,
        low=price,
        updateTime=server_time,
        serverTime=server_time,
        source=source,
        marketStatus="trading",
        isStale=is_stale,
    )


def _timestamp(value: str) -> int:
    return int(datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo("Asia/Shanghai")).timestamp() * 1000)


def _score_value(value: int | str) -> float:
    if value == "+inf":
        return float("inf")
    if value == "-inf":
        return float("-inf")
    return float(value)
