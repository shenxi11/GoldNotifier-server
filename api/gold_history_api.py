"""
模块名: api.gold_history_api
功能概述: 提供面向客户端的当天历史金价查询接口和短线 K 线聚合接口。
对外接口: router
依赖关系: FastAPI、GoldService、ApiResponse、GoldHistoryResponse
输入输出: 输入 symbol、date、时间窗口和 limit，输出统一历史行情 JSON。
异常与错误: 业务错误返回非 0 code，保持客户端可解析响应 envelope。
维护说明: 本接口只读取服务端已采集的新鲜行情点，不主动刷新上游。
"""

from fastapi import APIRouter, Query, Request

from model.api_response import ApiResponse
from model.gold_history import GoldCandlesResponse, GoldHistoryResponse
from service.gold_service import GoldService, GoldServiceError

router = APIRouter(prefix="/api/v1/gold", tags=["gold"])

DEFAULT_HISTORY_LIMIT = 2000
MAX_HISTORY_LIMIT = 10000


@router.get("/history", response_model=ApiResponse[GoldHistoryResponse])
async def get_gold_history(
    request: Request,
    symbol: str = "XAU",
    date: str | None = None,
    startMillis: int | None = Query(default=None, ge=0),
    endMillis: int | None = Query(default=None, ge=0),
    limit: int = Query(default=DEFAULT_HISTORY_LIMIT, ge=1),
) -> ApiResponse[GoldHistoryResponse]:
    """查询当天或指定窗口内已采集的历史行情点。"""

    service: GoldService = request.app.state.gold_service
    bounded_limit = min(limit, MAX_HISTORY_LIMIT)
    try:
        return ApiResponse.success(
            await service.history(
                symbol=symbol,
                date=date,
                start_millis=startMillis,
                end_millis=endMillis,
                limit=bounded_limit,
            )
        )
    except GoldServiceError as exc:
        return ApiResponse.error(exc.code, exc.message)


@router.get("/candles", response_model=ApiResponse[GoldCandlesResponse])
async def get_gold_candles(
    request: Request,
    symbol: str = "XAU",
    range_name: str = Query(default="5m", alias="range"),
) -> ApiResponse[GoldCandlesResponse]:
    """查询当前窗口内按固定粒度聚合的 OHLC K 线。"""

    service: GoldService = request.app.state.gold_service
    try:
        return ApiResponse.success(
            await service.candles(
                symbol=symbol,
                range_name=range_name,
            )
        )
    except GoldServiceError as exc:
        return ApiResponse.error(exc.code, exc.message)
