"""
模块名: tests.test_normalize_service
功能概述: 验证 NowAPI 响应标准化与字段校验。
对外接口: 无
依赖关系: pytest、normalize_service
输入输出: 输入上游示例 JSON，断言输出 GoldPrice 字段。
异常与错误: 非法行情字段应触发 ValueError。
维护说明: 测试样本不包含真实密钥。
"""

import pytest

from service.normalize_service import normalize_nowapi_payload


def _payload(high: str = "896.99", low: str = "876.21") -> dict:
    return {
        "success": "1",
        "result": {
            "dtList": {
                "1053": {
                    "varietynm": "现货黄金",
                    "last_price": "885.72",
                    "open_price": "887.28",
                    "yesy_price": "886.73",
                    "high_price": high,
                    "low_price": low,
                    "change_price": "-1.01",
                    "change_margin": "-0.11%",
                    "uptime": "2099-06-11 11:39:23",
                }
            }
        },
    }


def test_normalize_nowapi_payload_matches_client_contract() -> None:
    price = normalize_nowapi_payload(
        payload=_payload(),
        expected_goldid="1053",
        symbol="XAU",
        stale_after_seconds=180,
        timezone_name="Asia/Shanghai",
    )

    assert price.symbol == "XAU"
    assert price.price == 885.72
    assert price.change == -1.01
    assert price.changePercent == -0.11
    assert price.open == 887.28
    assert price.prevClose == 886.73
    assert price.high == 896.99
    assert price.low == 876.21
    assert price.source == "nowapi"


def test_normalize_rejects_invalid_high_low() -> None:
    with pytest.raises(ValueError):
        normalize_nowapi_payload(
            payload=_payload(high="870.00", low="876.21"),
            expected_goldid="1053",
            symbol="XAU",
            stale_after_seconds=180,
            timezone_name="Asia/Shanghai",
        )
