# Runbook: verificación y tareas pesadas

Comandos para ejecutar a mano, en orden. Complementa `docs/local.md` (que explica
la arquitectura); esto es la lista de la compra.

Marcados así los que **ya se verificaron el 2026-08-11** en esta máquina y no hace
falta repetir salvo que cambies el código:

- ✅ ya comprobado
- ⏳ pendiente, lo lanzas tú
- ⚠️ requiere credenciales FXCM y mercado abierto

---

## 1. Entorno

```bash
uv sync
./scripts/fix_forexconnect_macos.sh        # obligatorio tras CADA uv sync
```

⏳ Comprueba que el wheel carga (falla si olvidaste el paso anterior):

```bash
uv run python -c "import forexconnect; print('forexconnect OK')"
```

## 2. Suite de pruebas — ✅ 227 pasan

```bash
uv run pytest -q
```

Esperado: `227 passed`. Cubre, entre otras cosas:

- `tests/test_web_auth.py` — 6 pruebas (`async def`) del 503 sin token, 401 con
  token inválido, subprotocolo del WebSocket y mismo origen.
- `tests/test_net_position.py` — 17 pruebas de la ejecución de posición neta contra
  FXCM: ampliar, reducir con cierre parcial, dar la vuelta al signo, aplanar y las
  guardias de solo-lectura. Es el código que manda órdenes reales.
- `tests/test_execution_mode.py` — sim/live y la pausa obligatoria en Real.
- `tests/test_instruments.py` — descubrimiento del catálogo y derivación de pip.

## 3. Interfaz — ✅ compila

```bash
cd web-ui && npm install && npm run build && cd ..
```

Esperado: `web-ui/out/index.html` existe. Repite tras cada cambio en `web-ui/`.

⚠️ **No exportes `NEXT_PUBLIC_BACKEND_PORT` en la shell al hacer `npm run build`.**
Se incrusta en el export estático y el túnel dejaría de funcionar (el navegador
pediría `:8000` sobre el hostname de Cloudflare). Verificación:

```bash
grep -rl "localhost:8000" web-ui/out/ ; echo "(vacio = correcto)"
```

## 4. Arranque local — ✅

```bash
echo "BOT_API_TOKEN=$(openssl rand -hex 32)" >> .env    # solo la primera vez
caffeinate -s uv run uvicorn tradingbot.web.app:app --port 8000 \
  --proxy-headers --forwarded-allow-ips="*"
```

En otra terminal, ✅ verificado que responde así:

```bash
curl -s localhost:8000/healthz
#  {"ok":true,"ui_built":true}

curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/api/status
#  401

curl -s -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $(grep '^BOT_API_TOKEN=' .env | cut -d= -f2)" \
  localhost:8000/api/status
#  200

curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/
#  200  (la interfaz se sirve sin token; los datos no)
```

⏳ En el navegador: abre <http://localhost:8000>, pega el token, y confirma que
los precios cambian **cada 2 s** (eso prueba WebSocket vivo, no el polling de
respaldo de 15 s). El indicador debe decir `LIVE`, no `RECONECTANDO`.

Arranque simulado, sin credenciales, para probar la interfaz:

```bash
MOCK=1 uv run uvicorn tradingbot.web.app:app --port 8000
```

## 5. Túnel — ⏳

```bash
brew install cloudflared
./scripts/tunnel.sh
```

Comprueba `/healthz` antes de abrir el túnel y falla con mensaje claro si el
backend no está arriba. Abre la URL `https://….trycloudflare.com` que imprime:
debe pedir el token y luego mostrar los mismos datos.

## 6. Conexión FXCM — ⚠️ ⏳

```bash
uv run python scripts/check_connection.py
```

Si un instrumento sale en estado `D` o `V`, actívalo (el cambio persiste en la
cuenta FXCM):

```bash
uv run python scripts/subscribe_instrument.py EUR/USD
```

## 7. Poner el bot a operar — ⚠️ ⏳

**Siempre en este orden: demo → real.** Cada paso confirma algo que el
siguiente da por hecho.

### 7a. Demo con órdenes reales

```bash
# .env: FXCM_CONNECTION=Demo
caffeinate -s uv run uvicorn tradingbot.web.app:app --port 8000 \
  --proxy-headers --forwarded-allow-ips="*"
```

Verifica antes de darle a INICIAR:

```bash
TOKEN=$(grep '^BOT_API_TOKEN=' .env | cut -d= -f2)
curl -s -H "Authorization: Bearer $TOKEN" localhost:8000/api/instrument \
  | python3 -m json.tool
#  execution_mode: "live", connection: "Demo", symbol: el que quieras operar
```

Con `bollinger`/`rsi`/`wyckoff_1`: la orden lleva SL pegado al precio de apertura y
TP absoluto, puestos en el servidor de FXCM. Con `fsrppo`: posición neta sin SL/TP
en el bróker — la política decide la salida en cada barra, así que **el bot tiene
que seguir vivo** para gestionarla. Confirma la operación en la plataforma FXCM.

### 7b. Real

```bash
# .env: FXCM_CONNECTION=Real
caffeinate -s uv run uvicorn tradingbot.web.app:app --port 8000 \
  --proxy-headers --forwarded-allow-ips="*"
```

Arranca **pausado** a propósito y el panel enseña la banda roja «ÓRDENES REALES».
Antes de pulsar INICIAR: revisa `risk_per_trade`, `daily_loss_limit` y
`max_trades_per_day` en `/settings`, y empieza con el tamaño mínimo.

Para volver atrás en cualquier momento: DETENER en el panel, o
`curl -X POST -H "Authorization: Bearer $TOKEN" localhost:8000/api/control/pause`.

## 8. Tareas pesadas — ⏳ (ninguna se ha lanzado)

Estas van **en la otra máquina**: ver `docs/entrenamiento-remoto.md`. Aquí solo hace
falta el histórico, que es rápido:

```bash
uv run python scripts/download_history.py --symbols EUR/USD --timeframes h1 --years 2
uv run python scripts/run_backtest.py     # backtest de referencia, sin entrenar
```

Orden obligatorio si las lanzas aquí: `download_history` → `precompute_fsr` →
`train_fsrppo`. Sin la caché de FSR, el entrenamiento recalcula la señal en cada
época y tarda mucho más.

## 9. Cordura antes de tocar dinero

```bash
# Que no queden referencias a la infraestructura retirada (Firestore/Vercel/Actions)
grep -rn "firestore\|scheduled_tick\|FIRESTORE" --include="*.py" --include="*.ts" \
  --include="*.tsx" --include="*.mjs" . | grep -v node_modules
#  (vacio = limpio)  ✅ verificado
```

⏳ Y revisa a mano en `/settings` que `risk_per_trade`, `daily_loss_limit` y
`max_trades_per_day` son los que quieres **antes** de darle a INICIAR.

---

## Modo de ejecución

Para comprobar todo sin riesgo y sin credenciales, arranca en modo simulado:

```bash
MOCK=1 caffeinate -s uv run uvicorn tradingbot.web.app:app --port 8000
```

FSRPPO ya opera contra FXCM: `FxcmBroker.set_position` gestiona la posición neta
con órdenes a mercado (cierres parciales, vuelta de signo y aplanado). Necesita un
modelo activo entrenado **para el mismo instrumento**, o el motor se niega a operar.

## Multi-instrumento

El universo sale de la tabla OFFERS de tu cuenta, no de una lista fija:

```bash
# Con el backend arriba y credenciales FXCM:
TOKEN=$(grep '^BOT_API_TOKEN=' .env | cut -d= -f2)
curl -s -X POST -H "Authorization: Bearer $TOKEN" localhost:8000/api/instruments/refresh
curl -s -H "Authorization: Bearer $TOKEN" "localhost:8000/api/instruments?tradable=1" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d['instruments']),'operables')"
```

En el panel, el selector INSTRUMENTO agrupa por clase de activo. Cambiarlo exige el
bot detenido y sin posiciones abiertas: `open_trades()` filtra por instrumento, así
que cambiar con una posición viva la dejaría invisible para el motor.

⏳ **Sonda del catálogo** (opcional, para afinar el mapa de clases de activo).
ForexConnect no expone el enum `O2GInstrumentType` a Python, así que el mapa de
`src/tradingbot/instruments.py` es provisional y hay una heurística por símbolo de
respaldo. Para fijarlo con datos reales:

```bash
uv run python scripts/probe_offers.py Demo | tee /tmp/offers.tsv
```

Imprime, por oferta, `instrument_type`, `digits`, `point_size`, `pip_cost` y el
estado de suscripción, más un resumen `tipo → cuántos + ejemplos`. Con esa salida se
rellena `_TYPE_CLASSES`. Es de **solo lectura**: no manda órdenes ni cambia
suscripciones.

## Entrenamiento

En otra máquina: ver **`docs/entrenamiento-remoto.md`**. Aquí no hace falta lanzar
nada pesado.
