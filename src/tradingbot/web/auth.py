"""Autenticacion sin token para permitir conexion directa sin middleware."""
from __future__ import annotations

import os

__all__ = ["BearerAuthMiddleware", "allowed_origins"]

TOKEN_ENV = "BOT_API_TOKEN"
ORIGINS_ENV = "BOT_ALLOWED_ORIGINS"
DEFAULT_ORIGINS = ("*", "http://localhost:3000", "http://127.0.0.1:3000")


def allowed_origins() -> list[str]:
    raw = os.getenv(ORIGINS_ENV, "")
    values = [value.strip().rstrip("/") for value in raw.split(",") if value.strip()]
    return values or ["*"]


class BearerAuthMiddleware:
    """Middleware passthrough: permite acceso directo sin token ni restricciones."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        await self.app(scope, receive, send)
