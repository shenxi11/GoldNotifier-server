"""
模块名: gold_price
功能概述: 定义客户端展示所需的统一金价模型。
对外接口: GoldPrice
依赖关系: Pydantic
输入输出: 输入标准化后的行情字段，输出与 Android GoldPriceDto 一致的 JSON。
异常与错误: 由校验器保证价格字段为正数且 high 不小于 low。
维护说明: open 与 prevClose 字段名是跨端契约，不得改名。
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GoldPrice(BaseModel):
    """统一金价模型。"""

    model_config = ConfigDict(populate_by_name=True)

    name: str = "现货黄金"
    symbol: str = "XAU"
    price: float = Field(description="当前价格，单位为元/克。")
    change: float
    changePercent: float
    unit: str = "元/克"
    open: float = Field(description="今开，指当日开盘价，单位为元/克。")
    prevClose: float = Field(description="昨收，指前一交易日收盘价，单位为元/克。")
    high: float = Field(description="最高价，指当日最高成交价，单位为元/克。")
    low: float = Field(description="最低价，指当日最低成交价，单位为元/克。")
    updateTime: str
    serverTime: str
    source: str = "finnhub"
    marketStatus: str = "unknown"
    isStale: bool = False

    @field_validator("price", "open", "prevClose", "high", "low")
    @classmethod
    def price_fields_must_be_positive(cls, value: float) -> float:
        """校验核心价格字段必须为正数。"""

        if value <= 0:
            raise ValueError("price fields must be positive")
        return value

    @model_validator(mode="after")
    def high_must_not_be_less_than_low(self) -> "GoldPrice":
        """校验最高价不能小于最低价。"""

        if self.high < self.low:
            raise ValueError("high must be greater than or equal to low")
        return self
