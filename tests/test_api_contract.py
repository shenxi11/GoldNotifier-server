"""
模块名: tests.test_api_contract
功能概述: 验证 HTTP API envelope 与客户端字段契约。
对外接口: 无
依赖关系: FastAPI TestClient、create_app
输入输出: 输入测试应用配置，断言 JSON 响应结构。
异常与错误: 无上游凭据时 latest 应返回非 0 code 而不是崩溃。
维护说明: 测试关闭调度器，避免外部网络依赖。
"""

from fastapi.testclient import TestClient

from app import create_app
from config import Settings
from model.gold_history import GoldCandleBar, GoldCandlesResponse, GoldHistoryPoint, GoldHistoryResponse
from service.gold_service import GoldServiceError


def test_app_config_contract() -> None:
    client = TestClient(create_app(Settings(scheduler_enabled=False, rate_limit_per_minute=0)))

    response = client.get("/api/v1/app/config")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["minRefreshInterval"] == 3
    assert body["data"]["defaultRefreshInterval"] == 3
    assert body["data"]["nonTradingRefreshInterval"] == 300


def test_latest_without_cache_returns_json_error() -> None:
    app = create_app(Settings(scheduler_enabled=False, rate_limit_per_minute=0))
    app.state.gold_service = FakeLatestService()
    client = TestClient(app)

    response = client.get("/api/v1/gold/latest?symbol=XAU")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 503
    assert "cache is not ready" in body["message"]
    assert app.state.gold_service.refresh_called is False


def test_server_refresh_defaults_match_quota_plan() -> None:
    settings = Settings()

    assert settings.refresh_interval_seconds == 2
    assert settings.latest_cache_ttl_seconds == 10


def test_gold_history_contract_returns_points_and_caps_limit() -> None:
    app = create_app(Settings(scheduler_enabled=False, rate_limit_per_minute=0))
    app.state.gold_service = FakeHistoryService()
    client = TestClient(app)

    response = client.get("/api/v1/gold/history?symbol=XAU&date=2099-06-11&limit=20000")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["symbol"] == "XAU"
    assert body["data"]["date"] == "2099-06-11"
    assert body["data"]["timezone"] == "Asia/Shanghai"
    assert body["data"]["count"] == 1
    assert body["data"]["points"][0]["price"] == 885.72
    assert app.state.gold_service.last_limit == 10000


def test_gold_candles_contract_returns_bars() -> None:
    app = create_app(Settings(scheduler_enabled=False, rate_limit_per_minute=0))
    app.state.gold_service = FakeHistoryService()
    client = TestClient(app)

    response = client.get("/api/v1/gold/candles?symbol=XAU&range=1h")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["symbol"] == "XAU"
    assert body["data"]["range"] == "1h"
    assert body["data"]["resolution"] == "1m"
    assert body["data"]["timezone"] == "Asia/Shanghai"
    assert body["data"]["count"] == 1
    assert body["data"]["bars"][0]["open"] == 885.72


class FakeHistoryService:
    def __init__(self) -> None:
        self.last_limit = 0

    async def history(
        self,
        symbol: str,
        date: str | None,
        start_millis: int | None,
        end_millis: int | None,
        limit: int,
    ) -> GoldHistoryResponse:
        self.last_limit = limit
        return GoldHistoryResponse(
            symbol=symbol,
            date=date or "2099-06-11",
            timezone="Asia/Shanghai",
            count=1,
            points=[
                GoldHistoryPoint(
                    timestampMillis=4_085_190_365_000,
                    price=885.72,
                    updateTime="2099-06-11 11:39:25",
                    serverTime="2099-06-11 11:39:25",
                    source="finnhub",
                )
            ],
        )

    async def candles(
        self,
        symbol: str,
        range_name: str,
    ) -> GoldCandlesResponse:
        return GoldCandlesResponse(
            symbol=symbol,
            range=range_name,
            resolution="1m",
            timezone="Asia/Shanghai",
            count=1,
            bars=[
                GoldCandleBar(
                    timestampMillis=4_085_190_360_000,
                    open=885.72,
                    high=886.10,
                    low=885.20,
                    close=885.90,
                )
            ],
        )


class FakeLatestService:
    def __init__(self) -> None:
        self.refresh_called = False

    async def latest(self, symbol: str):
        raise GoldServiceError("latest gold cache is not ready")

    async def refresh(self, symbol: str):
        self.refresh_called = True
        raise AssertionError("latest api must not call refresh")
