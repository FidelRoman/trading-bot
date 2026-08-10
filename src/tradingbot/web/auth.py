"""Autenticacion minima para exponer el backend del bot a Internet."""
from __future__ import annotations

import json
import os
import secrets

__all__ = ["BearerAuthMiddleware", "allowed_origins"]

TOKEN_ENV = "BOT_API_TOKEN"
ORIGINS_ENV = "BOT_ALLOWED_ORIGINS"
DEFAULT_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")


def allowed_origins() -> list[str]:
    raw = os.getenv(ORIGINS_ENV, "")
    values = [value.strip().rstrip("/") for value in raw.split(",") if value.strip()]
    return values or list(DEFAULT_ORIGINS)


def _header(scope: dict, name: bytes) -> str:
    for key, value in scope.get("headers", ()):
        if key.lower() == name:
            return value.decode("latin-1")
    return ""


def _authorization_token(scope: dict) -> str:
    header = _header(scope, b"authorization")
    scheme, separator, token = header.partition(" ")
    return token.strip() if separator and scheme.lower() == "bearer" else ""


def _websocket_token(scope: dict) -> str:
    token = _authorization_token(scope)
    if token:
        return token
    # La API WebSocket del navegador no permite definir Authorization. Se usa
    # el segundo subprotocolo del handshake y el servidor solo acepta "bearer".
    protocols = [part.strip() for part in _header(scope, b"sec-websocket-protocol").split(",")]
    if len(protocols) >= 2 and protocols[0].lower() == "bearer":
        return protocols[1]
    return ""


def _matches(provided: str, expected: str) -> bool:
    return bool(provided and expected) and secrets.compare_digest(provided, expected)


class BearerAuthMiddleware:
    """Protege todo ``/api/*`` y ``/ws`` con un secreto de entorno.

    La ausencia de ``BOT_API_TOKEN`` falla cerrada: un despliegue mal
    configurado nunca queda accidentalmente abierto.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        scope_type = scope.get("type")
        path = scope.get("path", "")
        protected_http = scope_type == "http" and (path == "/api" or path.startswith("/api/"))
        protected_ws = scope_type == "websocket" and path == "/ws"

        if protected_http and scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return
        if not protected_http and not protected_ws:
            await self.app(scope, receive, send)
            return

        expected = os.getenv(TOKEN_ENV, "")
        provided = _websocket_token(scope) if protected_ws else _authorization_token(scope)
        origin = _header(scope, b"origin").rstrip("/")
        origin_ok = not protected_ws or not origin or origin in allowed_origins()

        if expected and _matches(provided, expected) and origin_ok:
            await self.app(scope, receive, send)
            return

        if protected_ws:
            reason = "backend sin BOT_API_TOKEN" if not expected else "no autorizado"
            await send({"type": "websocket.close", "code": 1008, "reason": reason})
            return

        status = 503 if not expected else 401
        message = (
            "BOT_API_TOKEN no esta configurado en el backend"
            if not expected else "token de acceso invalido o ausente"
        )
        body = json.dumps({"detail": message}).encode("utf-8")
        headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
        if status == 401:
            headers.append((b"www-authenticate", b"Bearer"))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})
