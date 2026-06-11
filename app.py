"""
模块名: app
功能概述: 创建 GoldNotifier 服务端 FastAPI 应用，是容器与本地运行的统一入口。
对外接口: app、create_app
依赖关系: FastAPI、Redis、Finnhub、NowAPI、APScheduler
输入输出: 输入环境变量配置，输出 HTTP API 服务。
异常与错误: 启动阶段不因上游密钥缺失而退出，接口层返回明确错误。
维护说明: 使用 uvicorn app:app 启动，避免在模块导入阶段执行阻塞逻辑。
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.app_config_api import router as app_config_router
from api.gold_api import router as gold_router
from api.health_api import router as health_router
from config import Settings
from datasource.base import GoldDataSource
from datasource.finnhub_provider import FinnhubProvider
from datasource.nowapi_provider import NowApiProvider
from scheduler import GoldRefreshScheduler
from service.cache_service import RedisCacheService
from service.gold_service import GoldService
from utils.logger import configure_logging, get_logger
from utils.rate_limit import InMemoryRateLimitMiddleware

logger = get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """创建 FastAPI 应用，并挂载服务依赖与路由。"""

    resolved_settings = settings or Settings.from_env()
    configure_logging(resolved_settings.log_level)

    cache = RedisCacheService(resolved_settings)
    datasource = _create_datasource(resolved_settings)
    gold_service = GoldService(
        datasource=datasource,
        cache=cache,
        settings=resolved_settings,
    )
    scheduler = GoldRefreshScheduler(
        service=gold_service,
        settings=resolved_settings,
    )

    @asynccontextmanager
    async def lifespan(fastapi_app: FastAPI):
        logger.info("gold api starting")
        if resolved_settings.scheduler_enabled:
            scheduler.start()
        yield
        logger.info("gold api stopping")
        scheduler.stop()
        await cache.close()

    app = FastAPI(
        title="GoldNotifier API",
        version="1.0.0",
        description="Gold price proxy API for the GoldNotifier Android client.",
        lifespan=lifespan,
    )

    app.state.settings = resolved_settings
    app.state.cache = cache
    app.state.gold_service = gold_service
    app.state.scheduler = scheduler

    app.add_middleware(
        InMemoryRateLimitMiddleware,
        requests_per_minute=resolved_settings.rate_limit_per_minute,
    )

    app.include_router(gold_router)
    app.include_router(app_config_router)
    app.include_router(health_router)

    return app


def _create_datasource(settings: Settings) -> GoldDataSource:
    """根据配置创建行情数据源。"""

    if settings.data_source == "nowapi":
        return NowApiProvider(settings)
    if settings.data_source == "finnhub":
        return FinnhubProvider(settings)
    logger.warning("unknown DATA_SOURCE=%s, fallback to finnhub", settings.data_source)
    return FinnhubProvider(settings)


app = create_app()
