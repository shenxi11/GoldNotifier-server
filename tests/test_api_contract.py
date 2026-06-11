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


def test_app_config_contract() -> None:
    client = TestClient(create_app(Settings(scheduler_enabled=False, rate_limit_per_minute=0)))

    response = client.get("/api/v1/app/config")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["minRefreshInterval"] == 30
    assert body["data"]["defaultRefreshInterval"] == 60
    assert body["data"]["nonTradingRefreshInterval"] == 300


def test_latest_without_credentials_returns_json_error() -> None:
    client = TestClient(create_app(Settings(scheduler_enabled=False, rate_limit_per_minute=0)))

    response = client.get("/api/v1/gold/latest?symbol=XAU")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 503
    assert "FINNHUB_API_KEY" in body["message"]
