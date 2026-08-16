#!/usr/bin/env bash
# Publica el backend local (UI + API + WebSocket) en una URL HTTPS de Cloudflare.
# Los datos no salen de esta máquina: el túnel solo transporta las peticiones.
#
#   ./scripts/tunnel.sh              # túnel efímero, URL *.trycloudflare.com
#   CLOUDFLARE_TUNNEL=bot ./scripts/tunnel.sh    # túnel con nombre (URL estable)
#   ./scripts/tunnel.sh 8321         # otro puerto
#
# AVISO: el backend ya no autentica nada (ver src/tradingbot/web/auth.py). Este
# script publica en Internet, y `POST /api/manual/long` sobre la cuenta Real
# queda al alcance de cualquiera que dé con la URL. Para acceder desde otro
# dispositivo tuyo usa Tailscale, que es una red privada:
#
#   tailscale serve --bg 8000
set -euo pipefail

PORT="${1:-8000}"

if [ "${ACEPTO_EXPONER_SIN_AUTENTICACION:-}" != "1" ]; then
  cat >&2 <<'EOF'
Cancelado: el backend no tiene autenticación y este túnel lo publicaría en
Internet, con la cuenta FXCM conectada y las órdenes manuales abiertas.

Para llegar desde otro dispositivo tuyo, usa la tailnet (red privada):

  tailscale serve --bg 8000

Si aun así quieres el túnel público, asumiéndolo de forma explícita:

  ACEPTO_EXPONER_SIN_AUTENTICACION=1 ./scripts/tunnel.sh
EOF
  exit 1
fi

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared no está instalado. Instálalo con: brew install cloudflared" >&2
  exit 1
fi

if ! curl -fsS --max-time 3 "http://localhost:${PORT}/healthz" >/dev/null; then
  echo "El backend no responde en http://localhost:${PORT}." >&2
  echo "Arráncalo primero:  uv run uvicorn tradingbot.web.app:app --port ${PORT}" >&2
  exit 1
fi

if [ -n "${CLOUDFLARE_TUNNEL:-}" ]; then
  # Túnel con nombre: hostname estable. Requiere un dominio en Cloudflare y
  # haber hecho antes `cloudflared tunnel create` + `cloudflared tunnel route dns`.
  exec cloudflared tunnel run --url "http://localhost:${PORT}" "${CLOUDFLARE_TUNNEL}"
fi

echo "Túnel efímero: la URL cambia en cada arranque." >&2
echo "La URL da acceso completo al panel y a las órdenes: no la compartas." >&2
exec cloudflared tunnel --url "http://localhost:${PORT}"
