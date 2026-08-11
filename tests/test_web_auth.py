"""La API publica falla cerrada y compara el bearer token en cada request."""
from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI, WebSocket

from tradingbot.web.auth import BearerAuthMiddleware


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
        await ws.accept(subprotocol="bearer")
        await ws.send_text("ok")
        await ws.close()

    return app


@pytest.mark.anyio
async def test_api_falla_cerrada_sin_token_configurado(monkeypatch):
    monkeypatch.delenv("BOT_API_TOKEN", raising=False)
    transport = httpx.ASGITransport(app=auth_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/")).status_code == 200
        response = await client.get("/api/ping")

    assert response.status_code == 503


@pytest.mark.anyio
async def test_api_exige_bearer_token(monkeypatch):
    monkeypatch.setenv("BOT_API_TOKEN", "un-secreto-largo")
    transport = httpx.ASGITransport(app=auth_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.get("/api/ping")
        wrong = await client.get("/api/ping", headers={"Authorization": "Bearer otro"})
        valid = await client.get(
            "/api/ping", headers={"Authorization": "Bearer un-secreto-largo"}
        )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert wrong.headers["www-authenticate"] == "Bearer"
    assert valid.status_code == 200
    assert valid.json() == {"ok": True}


@pytest.mark.anyio
async def test_websocket_acepta_token_como_subprotocolo_y_valida_origen(monkeypatch):
    monkeypatch.setenv("BOT_API_TOKEN", "token-websocket")
    monkeypatch.setenv("BOT_ALLOWED_ORIGINS", "https://panel.example")
    reached = []
    sent = []

    async def downstream(scope, receive, send):
        reached.append(scope["path"])

    async def receive():
        return {"type": "websocket.connect"}

    async def send(message):
        sent.append(message)

    middleware = BearerAuthMiddleware(downstream)
    base = {
        "type": "websocket",
        "path": "/ws",
        "headers": [
            (b"origin", b"https://panel.example"),
            (b"sec-websocket-protocol", b"bearer, token-websocket"),
        ],
    }
    await middleware(base, receive, send)
    assert reached == ["/ws"]

    reached.clear()
    await middleware(
        {**base, "headers": [(b"origin", b"https://evil.example"),
                              (b"sec-websocket-protocol", b"bearer, token-websocket")]},
        receive,
        send,
    )
    assert not reached
    assert sent[-1]["type"] == "websocket.close"
    assert sent[-1]["code"] == 1008


@pytest.mark.anyio
async def test_websocket_acepta_mismo_origen_sin_lista_blanca(monkeypatch):
    """El backend sirve la interfaz: un túnel o la LAN son siempre mismo origen."""
    monkeypatch.setenv("BOT_API_TOKEN", "token-websocket")
    monkeypatch.setenv("BOT_ALLOWED_ORIGINS", "http://localhost:3000")
    reached = []

    async def downstream(scope, receive, send):
        reached.append(scope["path"])

    async def receive():
        return {"type": "websocket.connect"}

    async def send(message):
        pass

    middleware = BearerAuthMiddleware(downstream)
    await middleware(
        {
            "type": "websocket",
            "path": "/ws",
            "headers": [
                (b"host", b"algo.trycloudflare.com"),
                (b"origin", b"https://algo.trycloudflare.com"),
                (b"sec-websocket-protocol", b"bearer, token-websocket"),
            ],
        },
        receive,
        send,
    )
    assert reached == ["/ws"]

    # Un origen distinto al Host sigue necesitando la lista blanca.
    reached.clear()
    await middleware(
        {
            "type": "websocket",
            "path": "/ws",
            "headers": [
                (b"host", b"algo.trycloudflare.com"),
                (b"origin", b"https://evil.example"),
                (b"sec-websocket-protocol", b"bearer, token-websocket"),
            ],
        },
        receive,
        send,
    )
    assert not reached


@pytest.mark.anyio
async def test_cors_incluye_respuesta_de_auth_para_origen_permitido(monkeypatch):
    monkeypatch.setenv("BOT_API_TOKEN", "correcto")
    monkeypatch.setenv("BOT_ALLOWED_ORIGINS", "https://panel.example")

    # Usa la aplicacion real para verificar el orden de middlewares. CORSMiddleware
    # congela allow_origins al construirse, asi que se recarga el modulo con la
    # variable ya puesta: si no, el test dependeria de ser el primero en importar
    # tradingbot.web.app en toda la sesion de pytest.
    import importlib

    import tradingbot.web.app as app_module

    app = importlib.reload(app_module).app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/status",
            headers={"Authorization": "Bearer incorrecto", "Origin": "https://panel.example"},
        )

    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == "https://panel.example"


@pytest.mark.anyio
async def test_la_raiz_sirve_la_interfaz_sin_token(monkeypatch):
    """El HTML es público (no lleva datos); AuthGate pide el token al cargar."""
    monkeypatch.setenv("BOT_API_TOKEN", "correcto")

    from tradingbot.web import app as module

    transport = httpx.ASGITransport(app=module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")

    if module.UI_DIR.is_dir():
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
    else:
        # Sin compilar, el backend arranca igual y explica cómo compilarla.
        assert response.status_code == 503
        assert "npm run build" in response.json()["error"]
