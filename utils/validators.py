"""
模块名: utils.validators
功能概述: 提供上游字段解析与轻量校验工具。
对外接口: parse_float、parse_percent
依赖关系: 无
输入输出: 输入字符串或数值，输出 float。
异常与错误: 无法解析且没有默认值时抛出 ValueError。
维护说明: 仅处理通用解析，不嵌入具体数据源字段名。
"""

from __future__ import annotations

from typing import Any


_MISSING = object()


def parse_float(value: Any, default: float | object = _MISSING) -> float:
    """解析普通数值字段。"""

    if value in (None, ""):
        if default is _MISSING:
            raise ValueError("number is required")
        return float(default)
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).strip().replace(",", "").replace("元/克", "").replace("￥", "")
    if cleaned.endswith("%"):
        cleaned = cleaned[:-1]
    try:
        return float(cleaned)
    except ValueError:
        if default is _MISSING:
            raise
        return float(default)


def parse_percent(value: Any, default: float | object = _MISSING) -> float:
    """解析百分数字段，返回百分数数值而非小数。"""

    return parse_float(value, default)
