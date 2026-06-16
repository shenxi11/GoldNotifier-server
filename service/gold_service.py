"""
模块名: service.gold_service
功能概述: 编排行情获取、缓存命中、上游刷新和失败兜底逻辑。
对外接口: GoldService、GoldServiceError
依赖关系: GoldDataSource、RedisCacheService、Settings
输入输出: 输入行情符号，输出最新或缓存 GoldPrice。
异常与错误: 上游失败且无缓存时抛出 GoldServiceError，API 层转为非 0 code。
维护说明: 所有数据源切换与缓存策略集中在此处，避免泄漏到路由层。
"""

from __future__ import annotations

from dataclasses import dataclass

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import Settings
from datasource.base import DataSourceError, GoldDataSource
from model.gold_history import GoldCandleBar, GoldCandlesResponse, GoldHistoryPoint, GoldHistoryResponse
from model.gold_price import GoldPrice
from service.cache_service import RedisCacheService
from utils.logger import get_logger
from utils.time_utils import is_date_string, now_string, now_timestamp_millis, today_date_string

logger = get_logger(__name__)


@dataclass(frozen=True)
class CandleResolution:
    """K 线时间窗口与聚合粒度配置。"""

    window_millis: int
    bucket_millis: int
    label: str


CANDLE_RESOLUTIONS: dict[str, CandleResolution] = {
    "5m": CandleResolution(window_millis=5 * 60_000, bucket_millis=15_000, label="15s"),
    "1h": CandleResolution(window_millis=60 * 60_000, bucket_millis=60_000, label="1m"),
    "6h": CandleResolution(window_millis=6 * 60 * 60_000, bucket_millis=5 * 60_000, label="5m"),
    "1d": CandleResolution(window_millis=24 * 60 * 60_000, bucket_millis=15 * 60_000, label="15m"),
}


@dataclass
class GoldServiceError(RuntimeError):
    """金价业务错误。"""

    message: str
    code: int = 503

    def __str__(self) -> str:
        return self.message


class GoldService:
    """金价业务服务。"""

    def __init__(
        self,
        datasource: GoldDataSource,
        cache: RedisCacheService,
        settings: Settings,
    ) -> None:
        self._datasource = datasource
        self._cache = cache
        self._settings = settings

    async def latest(self, symbol: str) -> GoldPrice:
        """获取服务端已缓存的最新行情，不主动刷新上游。"""

        normalized_symbol = symbol.upper()
        self._ensure_supported_symbol(normalized_symbol)
        cached = await self._cache.latest(normalized_symbol)
        if cached is not None:
            return cached.model_copy(update={"serverTime": now_string(self._settings.timezone)})

        fallback = await self._cache.last_success(normalized_symbol)
        if fallback is not None:
            return fallback.model_copy(
                update={
                    "source": "cache",
                    "isStale": True,
                    "serverTime": now_string(self._settings.timezone),
                }
            )
        raise GoldServiceError("latest gold cache is not ready")

    async def refresh(self, symbol: str) -> GoldPrice:
        """主动刷新上游行情，并在失败时返回 last_success 缓存。"""

        normalized_symbol = symbol.upper()
        self._ensure_supported_symbol(normalized_symbol)
        try:
            price = await self._datasource.fetch_latest(normalized_symbol)
            price = await self._cache.store_success(price)
            await self._cache.mark_source_status(
                {
                    "ok": True,
                    "symbol": normalized_symbol,
                    "source": price.source,
                    "serverTime": price.serverTime,
                }
            )
            return price
        except DataSourceError as exc:
            logger.warning("upstream refresh failed for %s: %s", normalized_symbol, exc)
            await self._cache.mark_source_status(
                {
                    "ok": False,
                    "symbol": normalized_symbol,
                    "error": str(exc),
                    "serverTime": now_string(self._settings.timezone),
                }
            )
            fallback = await self._cache.last_success(normalized_symbol)
            if fallback is not None:
                return fallback.model_copy(
                    update={
                        "source": "cache",
                        "isStale": True,
                        "serverTime": now_string(self._settings.timezone),
                    }
                )
            raise GoldServiceError(str(exc)) from exc

    async def health(self) -> dict[str, object]:
        """返回业务层健康信息。"""

        source_status = await self._cache.source_status()
        return {
            "defaultSymbol": self._settings.default_symbol,
            "dataSource": self._settings.data_source,
            "upstreamConfigured": self._settings.upstream_configured,
            "finnhubConfigured": self._settings.finnhub_configured,
            "alphaVantageConfigured": self._settings.alpha_vantage_configured,
            "nowapiConfigured": self._settings.nowapi_configured,
            "sourceStatus": source_status,
        }

    async def history(
        self,
        symbol: str,
        date: str | None,
        start_millis: int | None,
        end_millis: int | None,
        limit: int,
    ) -> GoldHistoryResponse:
        """查询指定日期或时间窗口内的历史行情点。"""

        normalized_symbol = symbol.upper()
        self._ensure_supported_symbol(normalized_symbol)
        query_date = date or today_date_string(self._settings.timezone)
        if not is_date_string(query_date):
            raise GoldServiceError(f"invalid date: {query_date}", code=400)
        if start_millis is not None and end_millis is not None and start_millis > end_millis:
            raise GoldServiceError("startMillis must be less than or equal to endMillis", code=400)

        points = await self._cache.history(
            symbol=normalized_symbol,
            date=query_date,
            start_millis=start_millis,
            end_millis=end_millis,
            limit=limit,
        )
        return GoldHistoryResponse(
            symbol=normalized_symbol,
            date=query_date,
            timezone=self._settings.timezone,
            count=len(points),
            points=points,
        )

    async def candles(
        self,
        symbol: str,
        range_name: str,
    ) -> GoldCandlesResponse:
        """按当前时间窗口把历史点聚合为 TradingView K 线。"""

        normalized_symbol = symbol.upper()
        self._ensure_supported_symbol(normalized_symbol)
        resolution = CANDLE_RESOLUTIONS.get(range_name)
        if resolution is None:
            supported = ", ".join(CANDLE_RESOLUTIONS.keys())
            raise GoldServiceError(f"unsupported range: {range_name}. supported: {supported}", code=400)

        end_millis = now_timestamp_millis(self._settings.timezone)
        start_millis = end_millis - resolution.window_millis
        points = await self._history_points_between(
            symbol=normalized_symbol,
            start_millis=start_millis,
            end_millis=end_millis,
        )
        bars = self._aggregate_candles(
            points=points,
            start_millis=start_millis,
            end_millis=end_millis,
            bucket_millis=resolution.bucket_millis,
        )
        return GoldCandlesResponse(
            symbol=normalized_symbol,
            range=range_name,
            resolution=resolution.label,
            timezone=self._settings.timezone,
            count=len(bars),
            bars=bars,
        )

    def _ensure_supported_symbol(self, symbol: str) -> None:
        if symbol != self._settings.default_symbol:
            raise GoldServiceError(f"unsupported symbol: {symbol}", code=400)

    async def _history_points_between(
        self,
        symbol: str,
        start_millis: int,
        end_millis: int,
    ) -> list[GoldHistoryPoint]:
        points: list[GoldHistoryPoint] = []
        for date in self._dates_between(start_millis, end_millis):
            points.extend(
                await self._cache.history(
                    symbol=symbol,
                    date=date,
                    start_millis=start_millis,
                    end_millis=end_millis,
                    limit=100_000,
                )
            )
        return sorted(
            {
                point.timestampMillis: point
                for point in points
                if start_millis <= point.timestampMillis <= end_millis and point.price > 0.0
            }.values(),
            key=lambda point: point.timestampMillis,
        )

    def _aggregate_candles(
        self,
        points: list[GoldHistoryPoint],
        start_millis: int,
        end_millis: int,
        bucket_millis: int,
    ) -> list[GoldCandleBar]:
        bars_by_bucket: dict[int, GoldCandleBar] = {}
        for point in points:
            if point.timestampMillis < start_millis or point.timestampMillis > end_millis:
                continue
            bucket_start = point.timestampMillis - point.timestampMillis % bucket_millis
            current = bars_by_bucket.get(bucket_start)
            if current is None:
                bars_by_bucket[bucket_start] = GoldCandleBar(
                    timestampMillis=bucket_start,
                    open=point.price,
                    high=point.price,
                    low=point.price,
                    close=point.price,
                )
            else:
                bars_by_bucket[bucket_start] = current.model_copy(
                    update={
                        "high": max(current.high, point.price),
                        "low": min(current.low, point.price),
                        "close": point.price,
                    }
                )
        return [bars_by_bucket[key] for key in sorted(bars_by_bucket.keys())]

    def _dates_between(self, start_millis: int, end_millis: int) -> list[str]:
        start_date = datetime.fromtimestamp(start_millis / 1000, tz=self._zone()).date()
        end_date = datetime.fromtimestamp(end_millis / 1000, tz=self._zone()).date()
        dates: list[str] = []
        current = start_date
        while current <= end_date:
            dates.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)
        return dates

    def _zone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self._settings.timezone)
        except ZoneInfoNotFoundError:
            return ZoneInfo("Asia/Shanghai")
