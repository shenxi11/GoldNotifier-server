"""
模块名: api.gold_api
功能概述: 提供面向 Android 客户端的最新金价接口。
对外接口: router
依赖关系: FastAPI、GoldService、ApiResponse
输入输出: 输入 symbol 查询参数，输出统一金价 JSON。
异常与错误: 业务错误返回非 0 code，保持客户端可解析响应 envelope。
维护说明: 字段名必须与 Android GoldPriceDto 保持一致。
"""

from fastapi import APIRouter, Request

from model.api_response import ApiResponse
from model.gold_price import GoldPrice
from service.gold_service import GoldService, GoldServiceError

router = APIRouter(prefix="/api/v1/gold", tags=["gold"])


@router.get("/latest", response_model=ApiResponse[GoldPrice])
async def get_latest_gold(request: Request, symbol: str = "XAU") -> ApiResponse[GoldPrice]:
    """获取最新金价；客户端请求始终主动刷新上游，失败时由服务层回退缓存。"""

    service: GoldService = request.app.state.gold_service
    try:
        return ApiResponse.success(await service.latest(symbol, force_refresh=True))
    except GoldServiceError as exc:
        return ApiResponse.error(exc.code, exc.message)
