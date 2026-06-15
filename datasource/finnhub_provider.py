"""
模块名: datasource.finnhub_provider
功能概述: 接入 Finnhub WebSocket 黄金报价和 Alpha Vantage 汇率，并换算为人民币每克现货黄金价格。
对外接口: FinnhubProvider、FinnhubQuoteSnapshot、build_gold_price_from_snapshot
依赖关系: asyncio、httpx、websockets、Settings、GoldPrice
输入输出: 输入 XAU 符号和 Finnhub 报价，输出统一 GoldPrice。
异常与错误: 凭据缺失、WebSocket 异常、Alpha Vantage 异常、行情缺项和非法价格均抛出 DataSourceError。
维护说明: 不记录 Finnhub token；当前 Finnhub 权限只允许流式现价，OHLC 字段暂用现价填充。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import websockets
import httpx
from websockets.exceptions import WebSocketException

from config import Settings
from datasource.base import DataSourceError, GoldDataSource
from model.gold_price import GoldPrice
from utils.logger import get_logger
from utils.time_utils import is_time_stale, now_string

TROY_OUNCE_GRAMS = 31.1034768
logger = get_logger(__name__)


@dataclass(frozen=True)
class FinnhubQuote:
    """Finnhub 单一品种的日内报价。"""

    current: float
    open: float
    prev_close: float
    high: float
    low: float
    latest_timestamp_ms: int | None = None
    is_stale: bool = False


@dataclass(frozen=True)
class FinnhubStreamPrice:
    """Finnhub WebSocket 推送的单笔最新价格。"""

    symbol: str
    price: float
    latest_timestamp_ms: int | None = None


@dataclass(frozen=True)
class FinnhubQuoteSnapshot:
    """Finnhub 换算所需的三项最新报价。"""

    xau_jpy: FinnhubQuote
    usd_jpy: FinnhubQuote
    usd_cny: FinnhubQuote


class FinnhubProvider(GoldDataSource):
    """Finnhub WebSocket 黄金行情数据源。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._latest: dict[str, FinnhubStreamPrice] = {}
        self._price_event = asyncio.Event()
        self._stream_lock = asyncio.Lock()
        self._stream_task: asyncio.Task[None] | None = None
        self._last_stream_error = ""
        self._usd_cny_quote_cache: FinnhubQuote | None = None

    async def fetch_latest(self, symbol: str) -> GoldPrice:
        """从 Finnhub WebSocket 获取最新报价并换算为元/克。"""

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
        stream_prices = await self._collect_stream_prices()
        return FinnhubQuoteSnapshot(
            xau_jpy=_quote_from_stream_price(stream_prices[self._settings.finnhub_xau_jpy_symbol]),
            usd_jpy=_quote_from_stream_price(stream_prices[self._settings.finnhub_usd_jpy_symbol]),
            usd_cny=await self._usd_cny_quote(),
        )

    async def _usd_cny_quote(self) -> FinnhubQuote:
        cached = self._cached_usd_cny_quote(allow_stale=False)
        if cached is not None:
            return cached

        try:
            quote = await self._fetch_usd_cny_quote()
            self._usd_cny_quote_cache = quote
            return quote
        except DataSourceError as exc:
            stale_cached = self._cached_usd_cny_quote(allow_stale=True)
            if stale_cached is not None:
                logger.warning("Alpha Vantage USD/CNY failed, using cached rate: %s", exc)
                throttled_cache = replace(
                    stale_cached,
                    latest_timestamp_ms=int(time.time() * 1000),
                    is_stale=True,
                )
                self._usd_cny_quote_cache = throttled_cache
                return throttled_cache

            fallback_rate = self._settings.usd_cny_fallback_rate
            if fallback_rate > 0:
                logger.warning("Alpha Vantage USD/CNY failed, using configured fallback rate: %s", exc)
                fallback_quote = FinnhubQuote(
                    current=fallback_rate,
                    open=fallback_rate,
                    prev_close=fallback_rate,
                    high=fallback_rate,
                    low=fallback_rate,
                    latest_timestamp_ms=int(time.time() * 1000),
                    is_stale=True,
                )
                self._usd_cny_quote_cache = fallback_quote
                return fallback_quote

            raise DataSourceError("Alpha Vantage USD/CNY rate unavailable") from exc

    async def _fetch_usd_cny_quote(self) -> FinnhubQuote:
        if not self._settings.alpha_vantage_api_key:
            raise DataSourceError("ALPHA_VANTAGE_API_KEY is required")
        params = {
            "function": "CURRENCY_EXCHANGE_RATE",
            "from_currency": self._settings.alpha_vantage_from_currency,
            "to_currency": self._settings.alpha_vantage_to_currency,
            "apikey": self._settings.alpha_vantage_api_key,
        }
        try:
            async with httpx.AsyncClient(timeout=self._settings.upstream_timeout_seconds) as client:
                response = await client.get(self._settings.alpha_vantage_endpoint, params=params)
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise DataSourceError("Alpha Vantage USD/CNY request timed out") from exc
        except httpx.HTTPError as exc:
            raise DataSourceError("Alpha Vantage USD/CNY request failed") from exc
        except ValueError as exc:
            raise DataSourceError("Alpha Vantage USD/CNY payload is invalid") from exc

        rate = _extract_alpha_vantage_exchange_rate(payload)
        if rate is None:
            raise DataSourceError("Alpha Vantage USD/CNY rate is missing")

        now_ms = int(time.time() * 1000)
        return FinnhubQuote(
            current=rate,
            open=rate,
            prev_close=rate,
            high=rate,
            low=rate,
            latest_timestamp_ms=now_ms,
        )

    def _cached_usd_cny_quote(self, allow_stale: bool) -> FinnhubQuote | None:
        cached = self._usd_cny_quote_cache
        if cached is None:
            return None
        if allow_stale:
            return cached
        if cached.latest_timestamp_ms is None:
            return None
        ttl_ms = max(self._settings.alpha_vantage_cache_ttl_seconds, 1) * 1000
        if int(time.time() * 1000) - cached.latest_timestamp_ms > ttl_ms:
            return None
        return cached

    async def _collect_stream_prices(self) -> dict[str, FinnhubStreamPrice]:
        timeout_seconds = max(1.0, self._settings.finnhub_stream_timeout_seconds)
        unique_symbols = self._stream_symbols()
        await self._ensure_stream_task(unique_symbols)

        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while True:
            snapshot = self._fresh_snapshot(unique_symbols)
            if snapshot is not None:
                return snapshot

            await self._ensure_stream_task(unique_symbols)
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                missing = [finnhub_symbol for finnhub_symbol in unique_symbols if finnhub_symbol not in self._latest]
                detail = f"Finnhub stream timed out waiting for {', '.join(missing)}"
                if self._last_stream_error:
                    detail = f"{detail}: {self._last_stream_error}"
                raise DataSourceError(detail)

            self._price_event.clear()
            try:
                await asyncio.wait_for(self._price_event.wait(), timeout=remaining)
            except asyncio.TimeoutError as exc:
                missing = [finnhub_symbol for finnhub_symbol in unique_symbols if finnhub_symbol not in self._latest]
                detail = f"Finnhub stream timed out waiting for {', '.join(missing)}"
                if self._last_stream_error:
                    detail = f"{detail}: {self._last_stream_error}"
                raise DataSourceError(detail) from exc

    async def _ensure_stream_task(self, symbols: list[str]) -> None:
        async with self._stream_lock:
            if self._stream_task is None or self._stream_task.done():
                self._stream_task = asyncio.create_task(self._run_stream(symbols))

    async def _run_stream(self, symbols: list[str]) -> None:
        retry_delay_seconds = 2.0
        while True:
            try:
                async with websockets.connect(
                    _websocket_url(self._settings.finnhub_ws_endpoint, self._settings.finnhub_api_key),
                    ping_interval=None,
                    close_timeout=3,
                ) as websocket:
                    self._last_stream_error = ""
                    for finnhub_symbol in symbols:
                        await websocket.send(json.dumps({"type": "subscribe", "symbol": finnhub_symbol}))

                    async for message in websocket:
                        payload = json.loads(message)
                        message_type = payload.get("type")
                        if message_type == "trade":
                            _capture_trade_prices(payload.get("data"), symbols, self._latest)
                            self._price_event.set()
                        elif message_type == "error":
                            self._last_stream_error = str(payload.get("msg", "unknown Finnhub stream error"))
                            self._price_event.set()
            except asyncio.CancelledError:
                raise
            except (json.JSONDecodeError, TypeError):
                self._last_stream_error = "Finnhub stream payload is invalid"
                self._price_event.set()
            except (OSError, WebSocketException) as exc:
                self._last_stream_error = f"Finnhub stream connection failed: {exc.__class__.__name__}"
                self._price_event.set()

            await asyncio.sleep(retry_delay_seconds)

    def _stream_symbols(self) -> list[str]:
        return list(
            dict.fromkeys(
                [
                    self._settings.finnhub_xau_jpy_symbol,
                    self._settings.finnhub_usd_jpy_symbol,
                ]
            )
        )

    def _fresh_snapshot(self, symbols: list[str]) -> dict[str, FinnhubStreamPrice] | None:
        snapshot = {finnhub_symbol: self._latest.get(finnhub_symbol) for finnhub_symbol in symbols}
        if any(stream_price is None for stream_price in snapshot.values()):
            return None

        stale_after_ms = max(self._settings.stale_after_seconds, 1) * 1000
        now_ms = int(time.time() * 1000)
        for stream_price in snapshot.values():
            if stream_price is None or stream_price.latest_timestamp_ms is None:
                return None
            if now_ms - stream_price.latest_timestamp_ms > stale_after_ms:
                return None

        return {symbol: stream_price for symbol, stream_price in snapshot.items() if stream_price is not None}


def _capture_trade_prices(
    trades: Any,
    expected_symbols: list[str],
    latest: dict[str, FinnhubStreamPrice],
) -> None:
    if not isinstance(trades, list):
        return
    expected = set(expected_symbols)
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        symbol = trade.get("s")
        if symbol not in expected:
            continue
        price = _positive_float(trade.get("p"))
        if price is None:
            continue
        latest[symbol] = FinnhubStreamPrice(
            symbol=symbol,
            price=price,
            latest_timestamp_ms=_timestamp_ms(trade.get("t")),
        )


def _quote_from_stream_price(stream_price: FinnhubStreamPrice) -> FinnhubQuote:
    return FinnhubQuote(
        current=stream_price.price,
        open=stream_price.price,
        prev_close=stream_price.price,
        high=stream_price.price,
        low=stream_price.price,
        latest_timestamp_ms=stream_price.latest_timestamp_ms,
    )


def _extract_alpha_vantage_exchange_rate(payload: Any) -> float | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("Error Message") or payload.get("Note") or payload.get("Information"):
        return None
    rate_block = payload.get("Realtime Currency Exchange Rate")
    if not isinstance(rate_block, dict):
        return None
    return _positive_float(rate_block.get("5. Exchange Rate"))


def build_gold_price_from_snapshot(
    snapshot: FinnhubQuoteSnapshot,
    symbol: str,
    stale_after_seconds: int,
    timezone_name: str,
) -> GoldPrice:
    """把 Finnhub 三项外汇报价换算为客户端统一金价模型。"""

    price = _convert(snapshot.xau_jpy.current, snapshot.usd_jpy.current, snapshot.usd_cny.current)
    open_price = _convert(snapshot.xau_jpy.open, snapshot.usd_jpy.open, snapshot.usd_cny.open)
    prev_close = _convert(
        snapshot.xau_jpy.prev_close,
        snapshot.usd_jpy.prev_close,
        snapshot.usd_cny.prev_close,
    )
    raw_high = _convert(snapshot.xau_jpy.high, snapshot.usd_jpy.high, snapshot.usd_cny.high)
    raw_low = _convert(snapshot.xau_jpy.low, snapshot.usd_jpy.low, snapshot.usd_cny.low)
    high = round(max(price, open_price, prev_close, raw_high, raw_low), 2)
    low = round(min(price, open_price, prev_close, raw_high, raw_low), 2)
    change = round(price - prev_close, 2)
    change_percent = round((change / prev_close) * 100, 2) if prev_close > 0 else 0.0
    timestamps = [
        quote.latest_timestamp_ms
        for quote in (snapshot.xau_jpy, snapshot.usd_jpy, snapshot.usd_cny)
        if quote.latest_timestamp_ms is not None and quote.latest_timestamp_ms > 0
    ]
    update_time = _format_timestamp_ms(max(timestamps) if timestamps else None, timezone_name)
    is_stale = is_time_stale(update_time, stale_after_seconds, timezone_name) or snapshot.usd_cny.is_stale

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


def _convert(xau_value: float, usd_jpy_value: float, usd_cny_value: float) -> float:
    if xau_value <= 0 or usd_jpy_value <= 0 or usd_cny_value <= 0:
        raise ValueError("Finnhub quote fields must be positive")
    cny_per_ounce = xau_value / usd_jpy_value * usd_cny_value
    cny_per_gram = cny_per_ounce / TROY_OUNCE_GRAMS
    return round(cny_per_gram, 2)


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


def _websocket_url(endpoint: str, token: str) -> str:
    separator = "&" if "?" in endpoint else "?"
    return f"{endpoint}{separator}{urlencode({'token': token})}"


def _zone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Shanghai")
