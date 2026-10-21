"""API 层共用的请求字段校验。

原先这几个函数是 account.py 里的私有函数，主站友链申请（public.py）也需要同一套
校验，所以抽出来共用 —— 复制一份迟早会漂移。
"""

# 生产是 Python 3.9：没有这行就不能写 `str | None`（PEP 604）。
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException, Request


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("cf-connecting-ip") or request.headers.get(
        "x-forwarded-for"
    )
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else None


def text_field(
    value: Any, *, field: str, max_length: int, required: bool = False
) -> str:
    result = str(value or "").strip()
    if required and not result:
        raise HTTPException(status_code=422, detail=f"{field}_required")
    if len(result) > max_length:
        raise HTTPException(status_code=422, detail=f"{field}_too_long")
    return result


def url_field(value: Any, *, field: str, required: bool = False) -> str:
    result = text_field(value, field=field, max_length=2048, required=required)
    if not result:
        return ""
    parsed = urlparse(result)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=422, detail=f"invalid_{field}")
    return result
