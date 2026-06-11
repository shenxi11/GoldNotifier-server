"""
模块名: tests.test_gold_service
功能概述: 验证 GoldService 的缓存命中、上游成功和失败兜底策略。
对外接口: 无
依赖关系: pytest、GoldService
输入输出: 输入 fake datasource/cache，断言返回 GoldPrice 或业务错误。
异常与错误: 无缓存且上游失败时应抛出 GoldServiceError。
维护说明: 测试不依赖 Redis 或外网。
"""

import asyncio
from typing import Any

import pytest

from config import Settings
from datasource.base import DataSourceError, GoldDataSource
from model.gold_price import GoldPrice
from service.gold_service import GoldService, GoldServiceError


class FakeDataSource(GoldDataSource):
    def __init__(self, price: GoldPrice | None = None, error: str | None = None) -> None:
        self.price = price
        self.error = error
        self.call_count = 0

    async def fetch_latest(self, symbol: str) -> GoldPrice:
        self.call_count += 1
        if self.error is not None:
            raise DataSourceError(self.error)
        assert self.price is not None
        return self.price


class FakeCache:
    def __init__(self, latest: GoldPrice | None = None, last_success: GoldPrice | None = None) -> None:
        self._latest = latest
        self._last_success = last_success
        self.source_status: dict[str, Any] | None = None

    async def latest(self, symbol: str) -> GoldPrice | None:
        return self._latest

    async def last_success(self, symbol: str) -> GoldPrice | None:
        return self._last_success

    async def store_success(self, price: GoldPrice) -> None:
        self._latest = price
        self._last_success = price

    async def mark_source_status(self, status: dict[str, Any]) -> None:
        self.source_status = status

    async def source_status(self) -> dict[str, Any] | None:
        return self.source_status


def _price(source: str = "nowapi") -> GoldPrice:
    return GoldPrice(
        name="现货黄金",
        symbol="XAU",
        price=885.72,
        change=-1.01,
        changePercent=-0.11,
        unit="元/克",
        open=887.28,
        prevClose=886.73,
        high=896.99,
        low=876.21,
        updateTime="2099-06-11 11:39:23",
        serverTime="2099-06-11 11:39:25",
        source=source,
        marketStatus="trading",
        isStale=False,
    )


def test_latest_returns_short_cache_before_upstream() -> None:
    datasource = FakeDataSource(error="should not call upstream")
    service = GoldService(
        datasource=datasource,
        cache=FakeCache(latest=_price()),
        settings=Settings(scheduler_enabled=False),
    )

    result = asyncio.run(service.latest("XAU"))

    assert result.price == 885.72
    assert result.source == "nowapi"
    assert datasource.call_count == 0


def test_latest_force_refresh_bypasses_short_cache() -> None:
    upstream_price = _price().model_copy(update={"price": 886.88})
    datasource = FakeDataSource(price=upstream_price)
    service = GoldService(
        datasource=datasource,
        cache=FakeCache(latest=_price()),
        settings=Settings(scheduler_enabled=False),
    )

    result = asyncio.run(service.latest("XAU", force_refresh=True))

    assert result.price == 886.88
    assert datasource.call_count == 1


def test_refresh_falls_back_to_last_success_as_stale() -> None:
    service = GoldService(
        datasource=FakeDataSource(error="upstream down"),
        cache=FakeCache(last_success=_price()),
        settings=Settings(scheduler_enabled=False),
    )

    result = asyncio.run(service.refresh("XAU"))

    assert result.source == "cache"
    assert result.isStale is True


def test_refresh_without_cache_raises_service_error() -> None:
    service = GoldService(
        datasource=FakeDataSource(error="missing key"),
        cache=FakeCache(),
        settings=Settings(scheduler_enabled=False),
    )

    with pytest.raises(GoldServiceError):
        asyncio.run(service.refresh("XAU"))
