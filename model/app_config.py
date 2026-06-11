"""
模块名: app_config
功能概述: 定义服务端下发给 Android 客户端的配置模型。
对外接口: AppConfig
依赖关系: Pydantic
输入输出: 输入服务端环境配置，输出客户端刷新与版本配置 JSON。
异常与错误: 配置值由 Settings 兜底，模型仅承担结构表达。
维护说明: 字段名需与 Android AppConfigDto 保持一致。
"""

from pydantic import BaseModel


class AppConfig(BaseModel):
    """Android 客户端配置。"""

    minRefreshInterval: int
    defaultRefreshInterval: int
    nonTradingRefreshInterval: int
    notificationEnabled: bool
    latestVersionCode: int
    forceUpdate: bool
    notice: str
