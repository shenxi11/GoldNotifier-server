"""
模块名: gold_history
功能概述: 定义服务端历史行情查询接口使用的精简点位模型和每日汇总模型。
对外接口: GoldHistoryPoint、GoldHistoryResponse、GoldDailySummary、GoldCandleBar、GoldCandlesResponse
依赖关系: Pydantic、GoldPrice、utils.time_utils
输入输出: 输入成功刷新的 GoldPrice，输出可写入 Redis ZSet 和返回给客户端的历史点。
异常与错误: 时间解析失败时回退服务端当前时间，避免一次异常行情破坏写入链路。
维护说明: 历史点只保存趋势展示需要的字段，不保存第三方原始响应。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from model.gold_price import GoldPrice
from utils.time_utils import now_timestamp_millis, timestamp_millis


class GoldHistoryPoint(BaseModel):
    """历史行情点位，按服务端接收行情时间排序。"""

    timestampMillis: int = Field(description="服务端接收行情时间，Unix 毫秒时间戳。")
    price: float = Field(description="当前价格，单位为元/克。")
    updateTime: str
    serverTime: str
    source: str

    @classmethod
    def from_price(cls, price: GoldPrice, timezone_name: str) -> "GoldHistoryPoint":
        """从新鲜 GoldPrice 构造历史点。"""

        point_timestamp = timestamp_millis(price.serverTime, timezone_name)
        if point_timestamp is None:
            point_timestamp = timestamp_millis(price.updateTime, timezone_name)
        if point_timestamp is None:
            point_timestamp = now_timestamp_millis(timezone_name)
        return cls(
            timestampMillis=point_timestamp,
            price=price.price,
            updateTime=price.updateTime,
            serverTime=price.serverTime,
            source=price.source,
        )


class GoldHistoryResponse(BaseModel):
    """历史行情查询响应数据。"""

    symbol: str
    date: str
    timezone: str
    count: int
    points: list[GoldHistoryPoint]


class GoldDailySummary(BaseModel):
    """每日行情汇总，用于从本地历史行情还原 open/high/low/close。"""

    symbol: str
    date: str
    open: float = Field(description="当天第一条有效行情价格。")
    high: float = Field(description="当天历史行情最高价。")
    low: float = Field(description="当天历史行情最低价。")
    close: float = Field(description="当天最后一条有效行情价格。")
    openTimestampMillis: int
    closeTimestampMillis: int


class GoldCandleBar(BaseModel):
    """按固定周期聚合后的 OHLC K 线。"""

    timestampMillis: int = Field(description="K 线周期起点，Unix 毫秒时间戳。")
    open: float
    high: float
    low: float
    close: float


class GoldCandlesResponse(BaseModel):
    """K 线查询响应数据。"""

    symbol: str
    range: str
    resolution: str
    timezone: str
    count: int
    bars: list[GoldCandleBar]
