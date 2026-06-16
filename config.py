"""
模块名: config
功能概述: 读取并规范化服务端运行配置，集中管理环境变量默认值。
对外接口: Settings
依赖关系: os、dataclasses
输入输出: 输入进程环境变量，输出不可变配置对象。
异常与错误: 类型转换失败时回退到默认值，避免容器因非关键配置拼写错误崩溃。
维护说明: 第三方密钥只允许来自环境变量，不在代码或仓库中存储；DATA_SOURCE 默认使用 Finnhub。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


def _int_env(env: Mapping[str, str], key: str, default: int) -> int:
    value = env.get(key)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _float_env(env: Mapping[str, str], key: str, default: float) -> float:
    value = env.get(key)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _bool_env(env: Mapping[str, str], key: str, default: bool) -> bool:
    value = env.get(key)
    if value is None or value == "":
        return default
    return value.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """服务端运行配置。"""

    data_source: str = "finnhub"
    nowapi_appkey: str = ""
    nowapi_sign: str = ""
    nowapi_endpoint: str = "https://sapi.k780.com"
    nowapi_app: str = "finance.gold_price"
    nowapi_goldid: str = "1053"
    finnhub_api_key: str = ""
    finnhub_ws_endpoint: str = "wss://ws.finnhub.io"
    finnhub_xau_jpy_symbol: str = "OANDA:XAU_JPY"
    finnhub_usd_jpy_symbol: str = "OANDA:USD_JPY"
    finnhub_stream_timeout_seconds: float = 8.0
    alpha_vantage_api_key: str = ""
    alpha_vantage_endpoint: str = "https://www.alphavantage.co/query"
    alpha_vantage_from_currency: str = "USD"
    alpha_vantage_to_currency: str = "CNY"
    alpha_vantage_cache_ttl_seconds: int = 3600
    usd_cny_fallback_rate: float = 6.7582
    default_symbol: str = "XAU"
    redis_url: str = "redis://redis:6379/0"
    latest_cache_ttl_seconds: int = 10
    last_success_ttl_seconds: int = 86400
    history_retention_days: int = 2
    stale_after_seconds: int = 180
    upstream_timeout_seconds: float = 8.0
    refresh_interval_seconds: int = 2
    non_trading_refresh_interval_seconds: int = 300
    scheduler_enabled: bool = True
    rate_limit_per_minute: int = 120
    log_level: str = "INFO"
    timezone: str = "Asia/Shanghai"
    min_refresh_interval: int = 3
    default_refresh_interval: int = 3
    latest_version_code: int = 1
    force_update: bool = False
    notice: str = ""

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        """从环境变量创建配置对象。"""

        source = os.environ if env is None else env
        redis_host = source.get("REDIS_HOST", "redis")
        redis_port = source.get("REDIS_PORT", "6379")
        redis_db = source.get("REDIS_DB", "0")
        redis_url = source.get("REDIS_URL") or f"redis://{redis_host}:{redis_port}/{redis_db}"
        return cls(
            data_source=source.get("DATA_SOURCE", cls.data_source).strip().lower(),
            nowapi_appkey=source.get("NOWAPI_APPKEY") or source.get("NOWAPI_KEY", ""),
            nowapi_sign=source.get("NOWAPI_SIGN", ""),
            nowapi_endpoint=source.get("NOWAPI_ENDPOINT", cls.nowapi_endpoint),
            nowapi_app=source.get("NOWAPI_APP", cls.nowapi_app),
            nowapi_goldid=source.get("NOWAPI_GOLDID", cls.nowapi_goldid),
            finnhub_api_key=source.get("FINNHUB_API_KEY") or source.get("FINNHUB_TOKEN", ""),
            finnhub_ws_endpoint=source.get("FINNHUB_WS_ENDPOINT", cls.finnhub_ws_endpoint),
            finnhub_xau_jpy_symbol=source.get("FINNHUB_XAU_JPY_SYMBOL", cls.finnhub_xau_jpy_symbol),
            finnhub_usd_jpy_symbol=source.get("FINNHUB_USD_JPY_SYMBOL", cls.finnhub_usd_jpy_symbol),
            alpha_vantage_api_key=source.get("ALPHA_VANTAGE_API_KEY", ""),
            alpha_vantage_endpoint=source.get("ALPHA_VANTAGE_ENDPOINT", cls.alpha_vantage_endpoint),
            alpha_vantage_from_currency=source.get(
                "ALPHA_VANTAGE_FROM_CURRENCY",
                cls.alpha_vantage_from_currency,
            ).upper(),
            alpha_vantage_to_currency=source.get(
                "ALPHA_VANTAGE_TO_CURRENCY",
                cls.alpha_vantage_to_currency,
            ).upper(),
            finnhub_stream_timeout_seconds=_float_env(
                source,
                "FINNHUB_STREAM_TIMEOUT_SECONDS",
                cls.finnhub_stream_timeout_seconds,
            ),
            alpha_vantage_cache_ttl_seconds=_int_env(
                source,
                "ALPHA_VANTAGE_CACHE_TTL_SECONDS",
                cls.alpha_vantage_cache_ttl_seconds,
            ),
            usd_cny_fallback_rate=_float_env(source, "USD_CNY_FALLBACK_RATE", cls.usd_cny_fallback_rate),
            default_symbol=source.get("DEFAULT_SYMBOL", cls.default_symbol).upper(),
            redis_url=redis_url,
            latest_cache_ttl_seconds=_int_env(source, "LATEST_CACHE_TTL_SECONDS", cls.latest_cache_ttl_seconds),
            last_success_ttl_seconds=_int_env(source, "LAST_SUCCESS_TTL_SECONDS", cls.last_success_ttl_seconds),
            history_retention_days=_int_env(source, "HISTORY_RETENTION_DAYS", cls.history_retention_days),
            stale_after_seconds=_int_env(source, "STALE_AFTER_SECONDS", cls.stale_after_seconds),
            upstream_timeout_seconds=_float_env(source, "UPSTREAM_TIMEOUT_SECONDS", cls.upstream_timeout_seconds),
            refresh_interval_seconds=_int_env(source, "REFRESH_INTERVAL_SECONDS", cls.refresh_interval_seconds),
            non_trading_refresh_interval_seconds=_int_env(
                source,
                "NON_TRADING_REFRESH_INTERVAL_SECONDS",
                cls.non_trading_refresh_interval_seconds,
            ),
            scheduler_enabled=_bool_env(source, "SCHEDULER_ENABLED", cls.scheduler_enabled),
            rate_limit_per_minute=_int_env(source, "RATE_LIMIT_PER_MINUTE", cls.rate_limit_per_minute),
            log_level=source.get("LOG_LEVEL", cls.log_level).upper(),
            timezone=source.get("TZ", cls.timezone),
            min_refresh_interval=_int_env(source, "MIN_REFRESH_INTERVAL", cls.min_refresh_interval),
            default_refresh_interval=_int_env(source, "DEFAULT_REFRESH_INTERVAL", cls.default_refresh_interval),
            latest_version_code=_int_env(source, "LATEST_VERSION_CODE", cls.latest_version_code),
            force_update=_bool_env(source, "FORCE_UPDATE", cls.force_update),
            notice=source.get("NOTICE", cls.notice),
        )

    @property
    def nowapi_configured(self) -> bool:
        """返回 NowAPI 凭据是否完整。"""

        return bool(self.nowapi_appkey and self.nowapi_sign)

    @property
    def finnhub_configured(self) -> bool:
        """返回 Finnhub 凭据是否完整。"""

        return bool(self.finnhub_api_key)

    @property
    def alpha_vantage_configured(self) -> bool:
        """返回 Alpha Vantage 汇率凭据是否完整。"""

        return bool(self.alpha_vantage_api_key)

    @property
    def upstream_configured(self) -> bool:
        """返回当前数据源凭据是否完整。"""

        if self.data_source == "nowapi":
            return self.nowapi_configured
        if self.data_source == "finnhub":
            return self.finnhub_configured
        return False

    def goldid_for_symbol(self, symbol: str) -> str:
        """返回符号对应的 NowAPI goldid。"""

        normalized = symbol.upper()
        if normalized != self.default_symbol:
            raise ValueError(f"unsupported symbol: {symbol}")
        return self.nowapi_goldid
