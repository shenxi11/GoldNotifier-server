"""
模块名: tests.test_finnhub_provider
功能概述: 验证 Finnhub 报价换算逻辑，不依赖外网 HTTP。
对外接口: 无
依赖关系: pytest、FinnhubQuoteSnapshot
输入输出: 输入三项外汇报价，断言输出 GoldPrice 客户端字段。
异常与错误: 非法报价应触发 ValueError。
维护说明: 测试样本不包含真实 Finnhub token。
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from datasource.finnhub_provider import FinnhubQuote, FinnhubQuoteSnapshot, build_gold_price_from_snapshot


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
        usd_cnh=FinnhubQuote(
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
        usd_cnh=FinnhubQuote(current=6.78, open=6.7, prev_close=6.7, high=6.8, low=6.6),
    )

    with pytest.raises(ValueError):
        build_gold_price_from_snapshot(
            snapshot=snapshot,
            symbol="XAU",
            stale_after_seconds=180,
            timezone_name="Asia/Shanghai",
        )
