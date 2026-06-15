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

from config import Settings
from datasource.base import DataSourceError, GoldDataSource
from model.gold_history import GoldHistoryResponse
from model.gold_price import GoldPrice
from service.cache_service import RedisCacheService
from utils.logger import get_logger
from utils.time_utils import is_date_string, now_string, today_date_string

logger = get_logger(__name__)


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

    async def latest(self, symbol: str, force_refresh: bool = False) -> GoldPrice:
        """获取最新行情，优先使用短 TTL 缓存。"""

        normalized_symbol = symbol.upper()
        self._ensure_supported_symbol(normalized_symbol)
        if not force_refresh:
            cached = await self._cache.latest(normalized_symbol)
            if cached is not None:
                return cached.model_copy(update={"serverTime": now_string(self._settings.timezone)})

        return await self.refresh(normalized_symbol)

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

    def _ensure_supported_symbol(self, symbol: str) -> None:
        if symbol != self._settings.default_symbol:
            raise GoldServiceError(f"unsupported symbol: {symbol}", code=400)
