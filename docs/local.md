# Operación local

Todo corre en esta Mac. No hay base de datos remota, ni funciones serverless, ni
runners: el bot, la API, la interfaz y los datos viven en el repositorio y en
`data/`. El acceso desde fuera se hace con un túnel que **transporta** las
peticiones hasta este equipo, sin copiar nada a ningún servicio.

```
                        ┌──────────────── esta Mac ────────────────┐
  navegador ──HTTPS──►  │  cloudflared ──► uvicorn :8000           │
  (móvil, portátil)     │                   ├── /        interfaz  │
                        │                   ├── /api/*   FastAPI   │
                        │                   ├── /ws      tiempo real│
                        │                   └── data/*.db  SQLite  │
                        └──────────────────────────────────────────┘
```

## 1. Instalación

```bash
uv sync                                # Python 3.10 + dependencias
./scripts/fix_forexconnect_macos.sh    # re-enlaza el binario FXCM
cp .env.example .env                   # completar FXCM_USER / FXCM_PASS
```

Hay que re-ejecutar `fix_forexconnect_macos.sh` después de cada `uv sync`:
Python está fijado a 3.10 porque es el único wheel de `forexconnect` para macOS
ARM64.

Genera el token de la API y guárdalo en `.env`:

```bash
echo "BOT_API_TOKEN=$(openssl rand -hex 32)" >> .env
```

Sin `BOT_API_TOKEN` el backend responde `503` a todo `/api/*`: falla cerrado a
propósito, para que un despliegue mal configurado nunca quede abierto.

## 2. Compilar la interfaz

```bash
cd web-ui && npm install && npm run build
```

Genera `web-ui/out/`, un export estático que sirve el propio backend. Hay que
repetirlo tras cada cambio en `web-ui/`. Para desarrollar con recarga en
caliente, `npm run dev` levanta Next en `:3000` y reescribe `/api` hacia `:8000`.

## 3. Arrancar

```bash
caffeinate -s uv run uvicorn tradingbot.web.app:app --port 8000 \
  --proxy-headers --forwarded-allow-ips="*"
```

### Modo de ejecución

El bot manda órdenes **reales** a la cuenta elegida en `FXCM_CONNECTION` (Demo o Real).
Para probar la interfaz sin credenciales, arranca en modo simulado:

```bash
MOCK=1 uv run uvicorn tradingbot.web.app:app --port 8000
```

Con `FXCM_CONNECTION=Real`, el bot **arranca siempre
pausado** y lo registra en el log: un reinicio del proceso no reabre operativa real
sin que alguien pulse INICIAR. El panel muestra una banda roja «ÓRDENES REALES»
cuando es el caso. INICIAR y cada orden manual requieren reconocimiento Real en
el backend. Este reconocimiento es consentimiento, no una evaluación: la app
permite operar aunque el modelo o la estrategia no estén validados.

- `caffeinate -s` impide que la Mac se duerma; el bot solo opera mientras el
  proceso esté vivo.
- `--proxy-headers` es lo que hace que el backend vea el esquema y la IP reales
  cuando llega a través del túnel.
- Sin `--host`, uvicorn escucha solo en `127.0.0.1`. Para entrar desde otro
  dispositivo de la misma wifi, añade `--host 0.0.0.0` y abre
  `http://<ip-de-la-mac>:8000`.
- `MOCK=1` delante del comando arranca en modo simulado, sin credenciales.

Abre <http://localhost:8000>, pega el `BOT_API_TOKEN` y el panel carga.

## 4. Acceso desde fuera: Cloudflare Tunnel

```bash
brew install cloudflared
./scripts/tunnel.sh            # comprueba que el backend responde y abre el túnel
```

Imprime una URL `https://….trycloudflare.com` que apunta a este equipo. Es
**efímera**: cambia en cada arranque. Para una URL estable hace falta un dominio
en Cloudflare:

```bash
cloudflared tunnel login
cloudflared tunnel create bot
cloudflared tunnel route dns bot bot.tudominio.com
CLOUDFLARE_TUNNEL=bot ./scripts/tunnel.sh
```

Lo que protege la URL es el `BOT_API_TOKEN`: la página carga, pero no muestra
ningún dato hasta introducirlo, y el WebSocket rechaza el handshake sin él. Si
quieres una segunda barrera antes de que la petición llegue siquiera al bot,
Cloudflare Access permite exigir tu correo delante del túnel.

No hace falta tocar `BOT_ALLOWED_ORIGINS`: la interfaz y la API comparten origen,
y el backend acepta el WebSocket cuando `Origin` coincide con `Host` — lo que
vale igual para localhost, para la LAN y para cualquier hostname de túnel. Esa
variable solo interviene con `npm run dev`, que sirve el frontend aparte.

## 5. Dónde viven los datos

| Ruta | Contenido |
|---|---|
| `data/tradingbot-demo.db`, `-real.db`, `-sim.db` | operaciones, equity, estado y log. Una DB por modo, para que lo simulado no contamine las métricas reales |
| `data/models/<run_id>/` | modelos entrenados (`model.pt`, `meta.json`, `history.json`) y `active.json` |
| `data/fsr_cache/*.npz` | caché de features FSR, indexada por ventana |
| `data/history/*.csv` | históricos descargados de FXCM |
| `data/selection/*.json` | rankings de `scripts/select_market.py` |

Nada de esto está en git salvo modelos y caché. Un backup del bot es una copia
de `data/` más el `.env`.

## 6. Tareas pesadas

Se lanzan desde el panel o por CLI; corren en esta máquina:

```bash
uv run python scripts/download_history.py --symbols EUR/USD --timeframes h1 --years 2
uv run python scripts/precompute_fsr.py -j $(sysctl -n hw.ncpu)
uv run python scripts/train_fsrppo.py
uv run python scripts/check_connection.py     # verifica el login FXCM
```

## 7. Verificación

1. `uv run pytest` en verde.
2. `curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/api/status` → `401`;
   con `-H "Authorization: Bearer $BOT_API_TOKEN"` → `200`.
3. El panel muestra precios que cambian cada 2 s (WebSocket vivo, no polling).
4. Con el túnel abierto, la URL pide el token y luego muestra los mismos datos.
5. La cuenta Real mueve dinero real: valida primero en Demo, usa límites de
   riesgo pequeños y no dejes el bot iniciado sin supervisión. El backend pausa el
   bot automáticamente tanto al conectar una cuenta Real desde el panel como al
   arrancar con `EXECUTION_MODE=live` y `FXCM_CONNECTION=Real`.
6. Para probar la interfaz sin credenciales y sin riesgo, arranca con
   `MOCK=1` (modo simulado).
