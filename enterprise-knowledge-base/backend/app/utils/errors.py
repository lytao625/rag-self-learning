import uuid
from typing import Any

from fastapi import HTTPException, Request


def new_trace_id() -> str:
    return uuid.uuid4().hex[:12]


def api_error(
    code: str,
    message: str,
    status_code: int = 400,
    trace_id: str | None = None,
) -> HTTPException:
    tid = trace_id or new_trace_id()
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": code, "message": message, "trace_id": tid}},
    )


def get_trace_id(request: Request) -> str:
    return getattr(request.state, "trace_id", new_trace_id())
