"""
模块名: utils.logger
功能概述: 配置服务端日志格式，提供统一 logger 获取入口。
对外接口: configure_logging、get_logger
依赖关系: logging
输入输出: 输入日志级别，输出标准 logging.Logger。
异常与错误: 无特殊异常处理。
维护说明: 不记录密钥、签名或完整上游请求 URL。
"""

import logging


def configure_logging(level: str) -> None:
    """配置根日志输出。"""

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """获取模块 logger。"""

    return logging.getLogger(name)
