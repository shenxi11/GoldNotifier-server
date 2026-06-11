"""
模块名: api.health_api
功能概述: 提供部署与监控使用的健康检查接口。
对外接口: router
依赖关系: FastAPI、RedisCacheService、GoldService
输入输出: 输入运行态依赖状态，输出健康检查 JSON。
异常与错误: Redis 异常由缓存层转为 ok=false，不直接抛出 500。
维护说明: health 不返回任何第三方密钥或完整连接串。
"""

from fastapi import APIRouter, Request

from service.cache_service import RedisCacheService
from service.gold_service import GoldService

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict[str, object]:
    """返回服务端健康状态。"""

    cache: RedisCacheService = request.app.state.cache
    service: GoldService = request.app.state.gold_service
    redis_status = await cache.health()
    service_status = await service.health()
    return {
        "ok": redis_status.get("ok", False),
        "redis": redis_status,
        "service": service_status,
    }
