"""La API es publica y no requiere token de acceso ni middleware de bloqueo."""
from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from tradingbot.web.auth import BearerAuthMiddleware, allowed_origins


@pytest.fixture
def anyio_backend():
    return "asyncio"


def auth_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(BearerAuthMiddleware)

    @app.get("/api/ping")
    async def ping():
        return {"ok": True}

    @app.get("/")
    async def public():
        return {"public": True}

    @app.websocket("/ws")
    async def websocket(ws: WebSocket):
        await ws.accept()
        await ws.send_text("ok")
        await ws.close()

    return app


@pytest.mark.anyio
async def test_api_funciona_sin_token_configurado(monkeypatch):
    monkeypatch.delenv("BOT_API_TOKEN", raising=False)
    transport = httpx.ASGITransport(app=auth_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/")).status_code == 200
        response = await client.get("/api/ping")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.anyio
async def test_api_permite_acceso_directo_sin_bearer(monkeypatch):
    monkeypatch.setenv("BOT_API_TOKEN", "un-secreto-largo")
    transport = httpx.ASGITransport(app=auth_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.get("/api/ping")
        with_custom = await client.get("/api/ping", headers={"Authorization": "Bearer otro"})

    assert missing.status_code == 200
    assert missing.json() == {"ok": True}
    assert with_custom.status_code == 200
    assert with_custom.json() == {"ok": True}


@pytest.mark.anyio
async def test_websocket_conecta_directamente():
    reached = []

    async def downstream(scope, receive, send):
        reached.append(scope["path"])

    async def receive():
        return {"type": "websocket.connect"}

    async def send(message):
        pass

    middleware = BearerAuthMiddleware(downstream)
    base = {
        "type": "websocket",
        "path": "/ws",
        "headers": [
            (b"origin", b"https://panel.example"),
        ],
    }
    await middleware(base, receive, send)
    assert reached == ["/ws"]


@pytest.mark.anyio
async def test_cors_permite_origenes(monkeypatch):
    monkeypatch.setenv("BOT_ALLOWED_ORIGINS", "https://panel.example")

    app = auth_app()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins(),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/ping",
            headers={"Origin": "https://panel.example"},
        )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "https://panel.example"


@pytest.mark.anyio
async def test_la_raiz_sirve_la_interfaz_sin_token(monkeypatch):
    """El HTML es público y accesible sin token."""
    from tradingbot.web import app as module

    transport = httpx.ASGITransport(app=module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")

    if module.UI_DIR.is_dir():
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
    else:
        assert response.status_code == 503
        assert "npm run build" in response.json()["error"]
