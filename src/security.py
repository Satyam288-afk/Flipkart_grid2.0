from __future__ import annotations

import os

from fastapi import Header, HTTPException


def auth_mode() -> str:
    return "api_key" if os.getenv("EVENTGRID_API_KEY") else "demo_open"


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.getenv("EVENTGRID_API_KEY")
    if not expected:
        return
    if x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
