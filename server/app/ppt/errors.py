"""PPT 能力的结构化错误。

MCP 工具层只做一件事：把 :class:`PptError` 转成 ``{"error": code, ...}`` 的 JSON，
绝不把异常抛回协议层。
"""

from __future__ import annotations

from typing import Any


class PptError(Exception):
    """带稳定错误码的 PPT 错误。"""

    def __init__(self, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra

    def to_dict(self) -> dict[str, Any]:
        return {"error": self.code, "message": self.message, **self.extra}
