"""
模块名: service.normalize_service
功能概述: 将 NowAPI 上游字段标准化为 Android 客户端约定的金价模型。
对外接口: normalize_nowapi_payload
依赖关系: GoldPrice、time_utils、validators
输入输出: 输入 NowAPI JSON，输出统一 GoldPrice。
异常与错误: 字段缺失、数值无法解析或校验失败时抛出异常供数据源层包装。
维护说明: 不在此处处理网络与缓存，保持纯数据转换便于单元测试。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from model.gold_price import GoldPrice
from utils.time_utils import is_time_stale, market_status, now_string
from utils.validators import parse_float, parse_percent


def normalize_nowapi_payload(
    payload: Mapping[str, Any],
    expected_goldid: str,
    symbol: str,
    stale_after_seconds: int,
    timezone_name: str,
) -> GoldPrice:
    """把 NowAPI 响应转换为统一 GoldPrice。"""

    row = _extract_quote_row(payload, expected_goldid)
    price = parse_float(_first_present(row, "last_price", "price", "nowpri", "latest_price"))
    open_price = parse_float(_first_present(row, "open_price", "open", "openpri"))
    prev_close = parse_float(_first_present(row, "yesy_price", "prevClose", "yestclose", "yes_price"))
    high = parse_float(_first_present(row, "high_price", "high", "maxpri"))
    low = parse_float(_first_present(row, "low_price", "low", "minpri"))
    change = parse_float(_first_present(row, "change_price", "change", "increase"), default=price - prev_close)
    change_percent = parse_percent(
        _first_present(row, "change_margin", "changePercent", "changeratio"),
        default=(change / prev_close) * 100,
    )
    update_time = str(_first_present(row, "uptime", "updateTime", "time", "date")).strip()
    if not update_time:
        raise ValueError("updateTime is required")

    name = str(_first_present(row, "varietynm", "name", default="现货黄金")).strip() or "现货黄金"
    return GoldPrice(
        name=name,
        symbol=symbol,
        price=round(price, 2),
        change=round(change, 2),
        changePercent=round(change_percent, 2),
        unit="元/克",
        open=round(open_price, 2),
        prevClose=round(prev_close, 2),
        high=round(high, 2),
        low=round(low, 2),
        updateTime=update_time,
        serverTime=now_string(timezone_name),
        source="nowapi",
        marketStatus=market_status(timezone_name),
        isStale=is_time_stale(update_time, stale_after_seconds, timezone_name),
    )


def _extract_quote_row(payload: Mapping[str, Any], expected_goldid: str) -> Mapping[str, Any]:
    result = payload.get("result")
    if not isinstance(result, Mapping):
        raise ValueError("result is required")

    dt_list = result.get("dtList", result)
    if isinstance(dt_list, Mapping):
        if expected_goldid in dt_list and isinstance(dt_list[expected_goldid], Mapping):
            return dt_list[expected_goldid]
        for value in dt_list.values():
            if isinstance(value, Mapping):
                return value
    if isinstance(dt_list, list):
        for value in dt_list:
            if isinstance(value, Mapping):
                goldid = str(value.get("goldid", ""))
                if not goldid or goldid == expected_goldid:
                    return value
    raise ValueError("quote row is required")


def _first_present(row: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    if default is not None:
        return default
    raise KeyError(keys[0])
