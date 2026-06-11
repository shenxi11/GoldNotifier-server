"""
模块名: datasource.nowapi_provider
功能概述: 接入 NowAPI 黄金行情接口，并转换为服务端统一金价模型。
对外接口: NowApiProvider
依赖关系: httpx、Settings、normalize_service
输入输出: 输入 XAU 符号和 NowAPI 凭据，输出 GoldPrice。
异常与错误: 凭据缺失、HTTP 异常、上游错误码和字段缺失均抛出 DataSourceError。
维护说明: 日志与异常不得包含完整上游请求 URL 或密钥。
"""

from __future__ import annotations

import httpx

from config import Settings
from datasource.base import DataSourceError, GoldDataSource
from model.gold_price import GoldPrice
from service.normalize_service import normalize_nowapi_payload


class NowApiProvider(GoldDataSource):
    """NowAPI 黄金行情数据源。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def fetch_latest(self, symbol: str) -> GoldPrice:
        """从 NowAPI 获取并标准化最新行情。"""

        if not self._settings.nowapi_configured:
            raise DataSourceError("NOWAPI_APPKEY and NOWAPI_SIGN are required")

        try:
            goldid = self._settings.goldid_for_symbol(symbol)
        except ValueError as exc:
            raise DataSourceError(str(exc)) from exc

        params = {
            "app": self._settings.nowapi_app,
            "goldid": goldid,
            "appkey": self._settings.nowapi_appkey,
            "sign": self._settings.nowapi_sign,
            "format": "json",
        }

        try:
            async with httpx.AsyncClient(timeout=self._settings.upstream_timeout_seconds) as client:
                response = await client.get(self._settings.nowapi_endpoint, params=params)
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise DataSourceError("NowAPI request timed out") from exc
        except httpx.HTTPError as exc:
            raise DataSourceError("NowAPI request failed") from exc
        except ValueError as exc:
            raise DataSourceError("NowAPI returned invalid JSON") from exc

        success = str(payload.get("success", "")).lower()
        if success not in {"1", "true"}:
            message = payload.get("msg") or payload.get("message") or "NowAPI returned an error"
            raise DataSourceError(str(message))

        try:
            return normalize_nowapi_payload(
                payload=payload,
                expected_goldid=goldid,
                symbol=symbol.upper(),
                stale_after_seconds=self._settings.stale_after_seconds,
                timezone_name=self._settings.timezone,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise DataSourceError("NowAPI payload cannot be normalized") from exc
