"""
模块名: api_response
功能概述: 定义服务端统一响应 envelope，保持 Android Retrofit DTO 契约稳定。
对外接口: ApiResponse
依赖关系: Pydantic
输入输出: 输入业务数据或错误信息，输出 JSON 可序列化响应对象。
异常与错误: 非 0 code 表示业务错误，HTTP 层仍优先保持可解析 JSON。
维护说明: 客户端已约定 code=0 为成功，不要随意变更字段名。
"""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一 API 响应结构。"""

    code: int
    message: str
    data: T | None = None

    @classmethod
    def success(cls, data: T) -> "ApiResponse[T]":
        """创建成功响应。"""

        return cls(code=0, message="success", data=data)

    @classmethod
    def error(cls, code: int, message: str) -> "ApiResponse[None]":
        """创建业务错误响应。"""

        return cls(code=code, message=message, data=None)
