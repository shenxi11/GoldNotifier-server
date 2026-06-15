"""
模块名: tests.test_finnhub_provider
功能概述: 验证 Finnhub 报价换算逻辑，不依赖外网 HTTP。
对外接口: 无
依赖关系: pytest、FinnhubQuoteSnapshot
输入输出: 输入三项外汇报价，断言输出 GoldPrice 客户端字段。
异常与错误: 非法报价应触发 ValueError。
维护说明: 测试样本不包含真实 Finnhub token。
"""

import asyncio
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from config import Settings
from datasource.base import DataSourceError
from datasource.finnhub_provider import (
    FinnhubProvider,
    FinnhubQuote,
    FinnhubQuoteSnapshot,
    FinnhubStreamPrice,
    _extract_alpha_vantage_exchange_rate,
    _quote_from_stream_price,
    build_gold_price_from_snapshot,
)


def test_build_gold_price_from_finnhub_snapshot_matches_client_contract() -> None:
    timestamp_ms = int(
        datetime(2099, 6, 11, 11, 39, 23, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp() * 1000
    )
    snapshot = FinnhubQuoteSnapshot(
        xau_jpy=FinnhubQuote(
            current=656497.5,
            open=655120.0,
            prev_close=654880.0,
            high=658200.0,
            low=651900.0,
            latest_timestamp_ms=timestamp_ms,
        ),
        usd_jpy=FinnhubQuote(
            current=160.5395,
            open=160.1200,
            prev_close=160.2800,
            high=160.8100,
            low=159.8800,
            latest_timestamp_ms=timestamp_ms,
        ),
        usd_cny=FinnhubQuote(
            current=6.78,
            open=6.75,
            prev_close=6.76,
            high=6.82,
            low=6.74,
            latest_timestamp_ms=timestamp_ms,
        ),
    )

    price = build_gold_price_from_snapshot(
        snapshot=snapshot,
        symbol="XAU",
        stale_after_seconds=180,
        timezone_name="Asia/Shanghai",
    )

    assert price.symbol == "XAU"
    converted_price = round((656497.5 / 160.5395 * 6.78) / 31.1034768, 2)
    converted_open = round((655120.0 / 160.1200 * 6.75) / 31.1034768, 2)
    converted_prev_close = round((654880.0 / 160.2800 * 6.76) / 31.1034768, 2)
    converted_high = round((658200.0 / 160.8100 * 6.82) / 31.1034768, 2)
    converted_low = round((651900.0 / 159.8800 * 6.74) / 31.1034768, 2)

    assert price.price == converted_price
    assert price.open == converted_open
    assert price.prevClose == converted_prev_close
    assert price.high == round(max(converted_price, converted_open, converted_prev_close, converted_high, converted_low), 2)
    assert price.low == round(min(converted_price, converted_open, converted_prev_close, converted_high, converted_low), 2)
    assert price.unit == "元/克"
    assert price.open != price.price
    assert price.prevClose != price.price
    assert price.high >= price.low
    assert price.change == round(price.price - price.prevClose, 2)
    assert price.changePercent == round((price.change / price.prevClose) * 100, 2)
    assert price.updateTime == "2099-06-11 11:39:23"
    assert price.source == "finnhub"
    assert price.marketStatus == "trading"
    assert price.isStale is False


def test_build_gold_price_rejects_invalid_quote() -> None:
    snapshot = FinnhubQuoteSnapshot(
        xau_jpy=FinnhubQuote(current=0, open=0, prev_close=0, high=0, low=0),
        usd_jpy=FinnhubQuote(current=160.5395, open=160.0, prev_close=160.0, high=161.0, low=159.0),
        usd_cny=FinnhubQuote(current=6.78, open=6.7, prev_close=6.7, high=6.8, low=6.6),
    )

    with pytest.raises(ValueError):
        build_gold_price_from_snapshot(
            snapshot=snapshot,
            symbol="XAU",
            stale_after_seconds=180,
            timezone_name="Asia/Shanghai",
        )


def test_stream_price_maps_to_client_price_fields() -> None:
    stream_price = FinnhubStreamPrice(
        symbol="OANDA:XAU_JPY",
        price=655432.5,
        latest_timestamp_ms=4_077_619_200_000,
    )

    quote = _quote_from_stream_price(stream_price)

    assert quote.current == 655432.5
    assert quote.open == 655432.5
    assert quote.prev_close == 655432.5
    assert quote.high == 655432.5
    assert quote.low == 655432.5
    assert quote.latest_timestamp_ms == 4_077_619_200_000


def test_build_gold_price_marks_fallback_rate_as_stale() -> None:
    timestamp_ms = int(
        datetime(2099, 6, 11, 11, 39, 23, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp() * 1000
    )
    snapshot = FinnhubQuoteSnapshot(
        xau_jpy=FinnhubQuote(
            current=656497.5,
            open=656497.5,
            prev_close=656497.5,
            high=656497.5,
            low=656497.5,
            latest_timestamp_ms=timestamp_ms,
        ),
        usd_jpy=FinnhubQuote(
            current=160.5395,
            open=160.5395,
            prev_close=160.5395,
            high=160.5395,
            low=160.5395,
            latest_timestamp_ms=timestamp_ms,
        ),
        usd_cny=FinnhubQuote(
            current=6.7582,
            open=6.7582,
            prev_close=6.7582,
            high=6.7582,
            low=6.7582,
            latest_timestamp_ms=timestamp_ms,
            is_stale=True,
        ),
    )

    price = build_gold_price_from_snapshot(
        snapshot=snapshot,
        symbol="XAU",
        stale_after_seconds=180,
        timezone_name="Asia/Shanghai",
    )

    assert price.isStale is True
    assert price.marketStatus == "closed"


def test_provider_stream_symbols_exclude_invalid_usd_cnh_symbol() -> None:
    provider = FinnhubProvider(Settings(finnhub_api_key="token", scheduler_enabled=False))

    assert provider._stream_symbols() == ["OANDA:XAU_JPY", "OANDA:USD_JPY"]


def test_extract_alpha_vantage_exchange_rate_reads_realtime_rate() -> None:
    payload = {
        "Realtime Currency Exchange Rate": {
            "1. From_Currency Code": "USD",
            "3. To_Currency Code": "CNY",
            "5. Exchange Rate": "6.7582",
        }
    }

    assert _extract_alpha_vantage_exchange_rate(payload) == 6.7582


def test_extract_alpha_vantage_exchange_rate_rejects_error_payloads() -> None:
    assert _extract_alpha_vantage_exchange_rate({"Note": "rate limit"}) is None
    assert _extract_alpha_vantage_exchange_rate({"Error Message": "invalid api call"}) is None
    assert _extract_alpha_vantage_exchange_rate({"Realtime Currency Exchange Rate": {}}) is None


def test_usd_cny_quote_uses_configured_fallback_when_alpha_vantage_fails() -> None:
    provider = FinnhubProvider(
        Settings(
            finnhub_api_key="token",
            alpha_vantage_api_key="alpha-token",
            usd_cny_fallback_rate=6.7582,
            scheduler_enabled=False,
        )
    )

    async def fail() -> FinnhubQuote:
        raise DataSourceError("rest down")

    provider._fetch_usd_cny_quote = fail  # type: ignore[method-assign]

    quote = asyncio.run(provider._usd_cny_quote())

    assert quote.current == 6.7582
    assert quote.is_stale is True


def test_usd_cny_quote_prefers_stale_memory_cache_before_configured_fallback() -> None:
    provider = FinnhubProvider(
        Settings(
            finnhub_api_key="token",
            alpha_vantage_api_key="alpha-token",
            usd_cny_fallback_rate=6.7582,
            alpha_vantage_cache_ttl_seconds=1,
            scheduler_enabled=False,
        )
    )
    provider._usd_cny_quote_cache = FinnhubQuote(
        current=7.1,
        open=7.1,
        prev_close=7.1,
        high=7.1,
        low=7.1,
        latest_timestamp_ms=int((time.time() - 10) * 1000),
    )

    async def fail() -> FinnhubQuote:
        raise DataSourceError("rest down")

    provider._fetch_usd_cny_quote = fail  # type: ignore[method-assign]

    quote = asyncio.run(provider._usd_cny_quote())

    assert quote.current == 7.1
    assert quote.is_stale is True


def test_usd_cny_quote_uses_fallback_without_alpha_vantage_key() -> None:
    provider = FinnhubProvider(
        Settings(
            finnhub_api_key="token",
            alpha_vantage_api_key="",
            usd_cny_fallback_rate=6.7582,
            scheduler_enabled=False,
        )
    )

    quote = asyncio.run(provider._usd_cny_quote())

    assert quote.current == 6.7582
    assert quote.is_stale is True
