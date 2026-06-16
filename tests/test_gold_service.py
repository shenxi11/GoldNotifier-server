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
from model.gold_history import GoldHistoryPoint
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
    def __init__(
        self,
        latest: GoldPrice | None = None,
        last_success: GoldPrice | None = None,
        history_points: list[GoldHistoryPoint] | None = None,
        store_success_result: GoldPrice | None = None,
    ) -> None:
        self._latest = latest
        self._last_success = last_success
        self._history_points = history_points or []
        self._store_success_result = store_success_result
        self._source_status: dict[str, Any] | None = None

    async def latest(self, symbol: str) -> GoldPrice | None:
        return self._latest

    async def last_success(self, symbol: str) -> GoldPrice | None:
        return self._last_success

    async def store_success(self, price: GoldPrice) -> GoldPrice:
        result = self._store_success_result or price
        self._latest = result
        self._last_success = result
        return result

    async def mark_source_status(self, status: dict[str, Any]) -> None:
        self._source_status = status

    async def source_status(self) -> dict[str, Any] | None:
        return self._source_status

    async def history(
        self,
        symbol: str,
        date: str,
        start_millis: int | None,
        end_millis: int | None,
        limit: int,
    ) -> list[GoldHistoryPoint]:
        return self._history_points[:limit]


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


def test_latest_falls_back_to_last_success_without_upstream_refresh() -> None:
    datasource = FakeDataSource(error="should not call upstream")
    service = GoldService(
        datasource=datasource,
        cache=FakeCache(last_success=_price()),
        settings=Settings(scheduler_enabled=False),
    )

    result = asyncio.run(service.latest("XAU"))

    assert result.price == 885.72
    assert result.source == "cache"
    assert result.isStale is True
    assert datasource.call_count == 0


def test_latest_without_cache_raises_without_upstream_refresh() -> None:
    datasource = FakeDataSource(price=_price())
    service = GoldService(
        datasource=datasource,
        cache=FakeCache(),
        settings=Settings(scheduler_enabled=False),
    )

    with pytest.raises(GoldServiceError) as exc:
        asyncio.run(service.latest("XAU"))

    assert exc.value.code == 503
    assert "cache is not ready" in exc.value.message
    assert datasource.call_count == 0


def test_refresh_returns_daily_enriched_cache_result() -> None:
    upstream_price = _price(source="finnhub")
    enriched_price = upstream_price.model_copy(
        update={
            "open": 880.0,
            "prevClose": 879.0,
            "high": 890.0,
            "low": 878.0,
            "change": 6.72,
            "changePercent": 0.76,
        }
    )
    service = GoldService(
        datasource=FakeDataSource(price=upstream_price),
        cache=FakeCache(store_success_result=enriched_price),
        settings=Settings(scheduler_enabled=False),
    )

    result = asyncio.run(service.refresh("XAU"))

    assert result.open == 880.0
    assert result.prevClose == 879.0
    assert result.high == 890.0
    assert result.low == 878.0


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


def test_health_reports_alpha_vantage_configuration() -> None:
    service = GoldService(
        datasource=FakeDataSource(price=_price(source="finnhub")),
        cache=FakeCache(),
        settings=Settings(
            data_source="finnhub",
            finnhub_api_key="finnhub-token",
            alpha_vantage_api_key="alpha-token",
            scheduler_enabled=False,
        ),
    )

    result = asyncio.run(service.health())

    assert result["finnhubConfigured"] is True
    assert result["alphaVantageConfigured"] is True


def test_history_returns_cached_points() -> None:
    point = GoldHistoryPoint(
        timestampMillis=4_085_190_365_000,
        price=885.72,
        updateTime="2099-06-11 11:39:25",
        serverTime="2099-06-11 11:39:25",
        source="finnhub",
    )
    service = GoldService(
        datasource=FakeDataSource(error="not used"),
        cache=FakeCache(history_points=[point]),
        settings=Settings(scheduler_enabled=False),
    )

    result = asyncio.run(
        service.history(
            symbol="XAU",
            date="2099-06-11",
            start_millis=None,
            end_millis=None,
            limit=2000,
        )
    )

    assert result.symbol == "XAU"
    assert result.date == "2099-06-11"
    assert result.count == 1
    assert result.points[0].price == 885.72


def test_history_rejects_invalid_date_and_time_window() -> None:
    service = GoldService(
        datasource=FakeDataSource(error="not used"),
        cache=FakeCache(),
        settings=Settings(scheduler_enabled=False),
    )

    with pytest.raises(GoldServiceError) as invalid_date:
        asyncio.run(service.history("XAU", "2099/06/11", None, None, 2000))
    assert invalid_date.value.code == 400

    with pytest.raises(GoldServiceError) as invalid_window:
        asyncio.run(service.history("XAU", "2099-06-11", 200, 100, 2000))
    assert invalid_window.value.code == 400
