"""
模块名: datasource.finnhub_provider
功能概述: 接入 Finnhub Quote 接口，并换算为人民币每克现货黄金价格。
对外接口: FinnhubProvider、FinnhubQuoteSnapshot、build_gold_price_from_snapshot
依赖关系: asyncio、httpx、Settings、GoldPrice
输入输出: 输入 XAU 符号和 Finnhub 报价，输出统一 GoldPrice。
异常与错误: 凭据缺失、HTTP 异常、行情缺项和非法价格均抛出 DataSourceError。
维护说明: 不记录 Finnhub token；open / prevClose / high / low 均来自独立字段，不再复用当前价。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from config import Settings
from datasource.base import DataSourceError, GoldDataSource
from model.gold_price import GoldPrice
from utils.time_utils import is_time_stale, now_string

TROY_OUNCE_GRAMS = 31.1034768
FINNHUB_QUOTE_ENDPOINT = "https://finnhub.io/api/v1/quote"


@dataclass(frozen=True)
class FinnhubQuote:
    """Finnhub 单一品种的日内报价。"""

    current: float
    open: float
    prev_close: float
    high: float
    low: float
    latest_timestamp_ms: int | None = None


@dataclass(frozen=True)
class FinnhubQuoteSnapshot:
    """Finnhub 换算所需的三项最新报价。"""

    xau_jpy: FinnhubQuote
    usd_jpy: FinnhubQuote
    usd_cnh: FinnhubQuote


class FinnhubProvider(GoldDataSource):
    """Finnhub Quote 黄金行情数据源。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def fetch_latest(self, symbol: str) -> GoldPrice:
        """从 Finnhub Quote 获取最新报价并换算为元/克。"""

        normalized_symbol = symbol.upper()
        if normalized_symbol != self._settings.default_symbol:
            raise DataSourceError(f"unsupported symbol: {symbol}")
        if not self._settings.finnhub_configured:
            raise DataSourceError("FINNHUB_API_KEY is required")

        snapshot = await self._collect_snapshot()
        try:
            return build_gold_price_from_snapshot(
                snapshot=snapshot,
                symbol=normalized_symbol,
                stale_after_seconds=self._settings.stale_after_seconds,
                timezone_name=self._settings.timezone,
            )
        except ValueError as exc:
            raise DataSourceError("Finnhub quotes cannot be normalized") from exc

    async def _collect_snapshot(self) -> FinnhubQuoteSnapshot:
        timeout_seconds = max(1.0, self._settings.upstream_timeout_seconds)
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                xau_jpy, usd_jpy, usd_cnh = await asyncio.gather(
                    self._fetch_quote(client, self._settings.finnhub_xau_jpy_symbol),
                    self._fetch_quote(client, self._settings.finnhub_usd_jpy_symbol),
                    self._fetch_quote(client, self._settings.finnhub_usd_cnh_symbol),
                )
        except DataSourceError:
            raise
        except httpx.TimeoutException as exc:
            raise DataSourceError("Finnhub quote request timed out") from exc
        except httpx.HTTPError as exc:
            raise DataSourceError("Finnhub quote request failed") from exc
        except OSError as exc:
            raise DataSourceError("Finnhub quote connection failed") from exc

        return FinnhubQuoteSnapshot(
            xau_jpy=xau_jpy,
            usd_jpy=usd_jpy,
            usd_cnh=usd_cnh,
        )

    async def _fetch_quote(self, client: httpx.AsyncClient, finnhub_symbol: str) -> FinnhubQuote:
        response = await client.get(
            FINNHUB_QUOTE_ENDPOINT,
            params={
                "symbol": finnhub_symbol,
                "token": self._settings.finnhub_api_key,
            },
        )
        response.raise_for_status()

        try:
            payload = response.json()
        except ValueError as exc:
            raise DataSourceError(f"Finnhub quote payload is invalid for {finnhub_symbol}") from exc

        current = _positive_float(payload.get("c"))
        open_price = _positive_float(payload.get("o"))
        prev_close = _positive_float(payload.get("pc"))
        high = _positive_float(payload.get("h"))
        low = _positive_float(payload.get("l"))
        if any(value is None for value in (current, open_price, prev_close, high, low)):
            raise DataSourceError(f"Finnhub quote payload is incomplete for {finnhub_symbol}")

        return FinnhubQuote(
            current=current,
            open=open_price,
            prev_close=prev_close,
            high=high,
            low=low,
            latest_timestamp_ms=_timestamp_ms(payload.get("t")),
        )


def build_gold_price_from_snapshot(
    snapshot: FinnhubQuoteSnapshot,
    symbol: str,
    stale_after_seconds: int,
    timezone_name: str,
) -> GoldPrice:
    """把 Finnhub 三项外汇报价换算为客户端统一金价模型。"""

    price = _convert(snapshot.xau_jpy.current, snapshot.usd_jpy.current, snapshot.usd_cnh.current)
    open_price = _convert(snapshot.xau_jpy.open, snapshot.usd_jpy.open, snapshot.usd_cnh.open)
    prev_close = _convert(
        snapshot.xau_jpy.prev_close,
        snapshot.usd_jpy.prev_close,
        snapshot.usd_cnh.prev_close,
    )
    raw_high = _convert(snapshot.xau_jpy.high, snapshot.usd_jpy.high, snapshot.usd_cnh.high)
    raw_low = _convert(snapshot.xau_jpy.low, snapshot.usd_jpy.low, snapshot.usd_cnh.low)
    high = round(max(price, open_price, prev_close, raw_high, raw_low), 2)
    low = round(min(price, open_price, prev_close, raw_high, raw_low), 2)
    change = round(price - prev_close, 2)
    change_percent = round((change / prev_close) * 100, 2) if prev_close > 0 else 0.0
    timestamps = [
        quote.latest_timestamp_ms
        for quote in (snapshot.xau_jpy, snapshot.usd_jpy, snapshot.usd_cnh)
        if quote.latest_timestamp_ms is not None and quote.latest_timestamp_ms > 0
    ]
    update_time = _format_timestamp_ms(max(timestamps) if timestamps else None, timezone_name)
    is_stale = is_time_stale(update_time, stale_after_seconds, timezone_name)

    return GoldPrice(
        name="现货黄金",
        symbol=symbol.upper(),
        price=price,
        change=change,
        changePercent=change_percent,
        unit="元/克",
        open=open_price,
        prevClose=prev_close,
        high=high,
        low=low,
        updateTime=update_time,
        serverTime=now_string(timezone_name),
        source="finnhub",
        marketStatus="closed" if is_stale else "trading",
        isStale=is_stale,
    )


def _format_timestamp_ms(timestamp_ms: int | None, timezone_name: str) -> str:
    if timestamp_ms is None:
        return now_string(timezone_name)
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=_zone(timezone_name)).strftime("%Y-%m-%d %H:%M:%S")


def _convert(xau_value: float, usd_jpy_value: float, usd_cnh_value: float) -> float:
    if xau_value <= 0 or usd_jpy_value <= 0 or usd_cnh_value <= 0:
        raise ValueError("Finnhub quote fields must be positive")
    cnh_per_ounce = xau_value / usd_jpy_value * usd_cnh_value
    cnh_per_gram = cnh_per_ounce / TROY_OUNCE_GRAMS
    return round(cnh_per_gram, 2)


def _positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _timestamp_ms(value: Any) -> int | None:
    timestamp = _int_or_none(value)
    if timestamp is None or timestamp <= 0:
        return None
    return timestamp * 1000 if timestamp < 1_000_000_000_000 else timestamp


def _zone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Shanghai")
