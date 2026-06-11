"""
模块名: api.app_config_api
功能概述: 提供 Android 客户端运行配置接口。
对外接口: router
依赖关系: FastAPI、Settings、AppConfig
输入输出: 输入服务端配置，输出客户端刷新/通知/版本配置。
异常与错误: 当前接口为静态配置，不访问上游和缓存。
维护说明: 保持字段名与 AppConfigDto 一致，新增字段需客户端兼容。
"""

from fastapi import APIRouter, Request

from config import Settings
from model.api_response import ApiResponse
from model.app_config import AppConfig

router = APIRouter(prefix="/api/v1/app", tags=["app"])


@router.get("/config", response_model=ApiResponse[AppConfig])
async def get_app_config(request: Request) -> ApiResponse[AppConfig]:
    """获取 App 配置。"""

    settings: Settings = request.app.state.settings
    return ApiResponse.success(
        AppConfig(
            minRefreshInterval=settings.min_refresh_interval,
            defaultRefreshInterval=settings.default_refresh_interval,
            nonTradingRefreshInterval=settings.non_trading_refresh_interval_seconds,
            notificationEnabled=True,
            latestVersionCode=settings.latest_version_code,
            forceUpdate=settings.force_update,
            notice=settings.notice,
        )
    )
