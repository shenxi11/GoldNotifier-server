"""
模块名: utils.time_utils
功能概述: 提供服务端时间格式化、行情更新时间解析和交易状态判断。
对外接口: now_string、now_timestamp_millis、timestamp_millis、today_date_string、date_string_from_timestamp、is_time_stale、market_status
依赖关系: datetime、zoneinfo
输入输出: 输入时间字符串或时区名称，输出标准时间字符串与状态标记。
异常与错误: 无法解析更新时间时按 stale 处理，避免误报新鲜数据。
维护说明: 时间格式需保持 yyyy-MM-dd HH:mm:ss，匹配 Android 展示层。
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def now_string(timezone_name: str) -> str:
    """返回服务端当前时间字符串。"""

    return datetime.now(_zone(timezone_name)).strftime("%Y-%m-%d %H:%M:%S")


def now_timestamp_millis(timezone_name: str) -> int:
    """返回服务端当前 Unix 毫秒时间戳。"""

    return int(datetime.now(_zone(timezone_name)).timestamp() * 1000)


def timestamp_millis(value: str, timezone_name: str) -> int | None:
    """把服务端时间字符串转换为 Unix 毫秒时间戳。"""

    parsed = _parse_datetime(value, timezone_name)
    if parsed is None:
        return None
    return int(parsed.timestamp() * 1000)


def today_date_string(timezone_name: str) -> str:
    """返回指定时区的当天日期字符串。"""

    return datetime.now(_zone(timezone_name)).strftime("%Y-%m-%d")


def date_string_from_timestamp(timestamp_millis: int, timezone_name: str) -> str:
    """把 Unix 毫秒时间戳转换为指定时区日期字符串。"""

    return datetime.fromtimestamp(timestamp_millis / 1000, tz=_zone(timezone_name)).strftime("%Y-%m-%d")


def is_date_string(value: str) -> bool:
    """判断字符串是否符合 yyyy-MM-dd 日期格式。"""

    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def is_time_stale(update_time: str, stale_after_seconds: int, timezone_name: str) -> bool:
    """判断上游更新时间是否超过延迟阈值。"""

    parsed = _parse_datetime(update_time, timezone_name)
    if parsed is None:
        return True
    delta = datetime.now(_zone(timezone_name)) - parsed
    return delta.total_seconds() > stale_after_seconds


def market_status(timezone_name: str) -> str:
    """粗略判断上海黄金相关交易状态。"""

    current = datetime.now(_zone(timezone_name))
    if current.weekday() >= 5:
        return "closed"
    current_time = current.time()
    day_session = time(9, 0) <= current_time <= time(15, 30)
    night_session = current_time >= time(20, 0) or current_time <= time(2, 30)
    return "trading" if day_session or night_session else "closed"


def _parse_datetime(value: str, timezone_name: str) -> datetime | None:
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=_zone(timezone_name))
        except ValueError:
            continue
    return None


def _zone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Shanghai")
