"""
模块名: datasource.base
功能概述: 定义行情数据源抽象与错误类型，隔离上游供应商差异。
对外接口: GoldDataSource、DataSourceError
依赖关系: abc、GoldPrice
输入输出: 输入行情符号，输出统一 GoldPrice。
异常与错误: 上游网络、凭据、字段异常统一包装为 DataSourceError。
维护说明: 新增备用源时实现 GoldDataSource，不修改 API 层。
"""

from abc import ABC, abstractmethod

from model.gold_price import GoldPrice


class DataSourceError(RuntimeError):
    """上游行情数据源错误。"""


class GoldDataSource(ABC):
    """行情数据源抽象。"""

    @abstractmethod
    async def fetch_latest(self, symbol: str) -> GoldPrice:
        """获取指定符号的最新行情。"""
