"""
模块名: scheduler
功能概述: 使用 APScheduler 定时刷新默认金价缓存。
对外接口: GoldRefreshScheduler
依赖关系: APScheduler、GoldService、Settings
输入输出: 输入业务服务与刷新间隔，周期性写入 Redis 缓存。
异常与错误: 定时任务异常只记录日志，不影响 HTTP 服务继续响应。
维护说明: 调度器只刷新默认 symbol，扩展多品种时再增加任务表。
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import Settings
from service.gold_service import GoldService, GoldServiceError
from utils.logger import get_logger

logger = get_logger(__name__)


class GoldRefreshScheduler:
    """默认行情定时刷新调度器。"""

    def __init__(self, service: GoldService, settings: Settings) -> None:
        self._service = service
        self._settings = settings
        self._scheduler = AsyncIOScheduler(timezone=settings.timezone)

    def start(self) -> None:
        """启动定时刷新任务。"""

        if self._scheduler.running:
            return
        self._scheduler.add_job(
            self._safe_refresh,
            "interval",
            seconds=self._settings.refresh_interval_seconds,
            id="refresh-default-gold",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        self._scheduler.start()

    def stop(self) -> None:
        """停止调度器。"""

        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    async def _safe_refresh(self) -> None:
        try:
            await self._service.refresh(self._settings.default_symbol)
        except GoldServiceError as exc:
            logger.warning("scheduled refresh skipped: %s", exc)
