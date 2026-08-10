# Plan de despliegue y cómputo externo — FSRPPO

Tres agentes trabajando en paralelo sobre contratos definidos. Objetivos:

1. Sacar de tu máquina la descarga de histórico y el precálculo de FSR.
2. Desplegar el bot y su interfaz en infraestructura gratuita.
3. Que el proyecto pueda **elegir el mejor símbolo y periodicidad** en vez de
   estar clavado a EUR/USD H1.

Contexto de partida: [`PLAN.md`](PLAN.md) y la sección de resultados del
[`README.md`](README.md). FSRPPO obtuvo 0 de 10 semillas sobre EUR/USD H1 por
sobreajuste, y el diagnóstico fue que faltan datos y sobra ruido intradía — de ahí
que la búsqueda de símbolo y periodicidad sea parte del objetivo, no un extra.

---

## Restricciones verificadas que condicionan todo el plan

Comprobadas contra PyPI y el entorno real, no supuestas:

| Restricción | Dato | Consecuencia |
|---|---|---|
| `forexconnect` en Linux | Wheel más nuevo: **1.6.5.1, cp37, manylinux1_x86_64**. La versión actual (1.6.43) **no publica wheel de Linux** | Cualquier cosa que hable con FXCM en Linux corre en **Python 3.7 y x86_64**, con un SDK de varias versiones atrás |
| `forexconnect` y ARM | **No existe** wheel `aarch64` | Descarta las VMs ARM gratuitas (Oracle Ampere, la mayoría del free tier moderno) |
| PyTorch | 493 MB instalado; torch ≥2 exige Python ≥3.9 | **torch y forexconnect no pueden convivir** en el mismo intérprete Linux |
| Vercel | Funciones serverless: 250 MB descomprimido, sin procesos persistentes, sin servidor WebSocket propio, FS efímero | **El bot no puede vivir en Vercel.** La interfaz Next.js sí, perfectamente |
| El servidor actual | `web/app.py` **no tiene autenticación** (ya avisado en el README) | Exponerlo a internet = dar a cualquiera el control del bot. Bloqueante antes de desplegar |

### Las dos decisiones de arquitectura que salen de ahí

**1. Inferencia sin torch.** La política es un MLP de dos capas
(`53 → 256 → 256 → 4`, tanh, más softplus a la salida). Exportarla a un `.npz` y
evaluarla con numpy son ~20 líneas. Con eso el bot en producción necesita solo
`numpy`, `scipy`, `pandas` y `forexconnect` — compatible con Python 3.7 — y el
entrenamiento se queda donde haya torch. Esto desbloquea el despliegue y además
reduce la imagen de ~700 MB a ~80 MB.

**2. El bot no va a Vercel, la interfaz sí.** Frontend Next.js en Vercel (gratis,
encaja de forma nativa). Backend en un host que permita un proceso persistente
x86_64. Ver opciones en el Agente C.

---

## Reparto entre agentes

```
Agente A ── datos y cómputo externo ──┐
                                      ├──► artefactos (CSV + caché FSR)
Agente B ── multi-instrumento ────────┘         │
                y selección                     ▼
                                        Agente C ── despliegue
```

Los tres pueden empezar a la vez. Las únicas dependencias son los **contratos**
de la sección final, que hay que fijar antes de escribir código.

---

# Agente A — Datos y cómputo externo (GitHub Actions)

**Objetivo:** que descargar histórico y precalcular FSR ocurra en GitHub, no en tu
portátil, para cualquier símbolo y periodicidad.

## A1. Parametrizar la descarga

Hoy `INSTRUMENT = "EUR/USD"` es una constante de módulo usada en 6 puntos de
`src/tradingbot/broker.py` (líneas 58, 100, 122, 124, 159, 213, 230). Hay que
pasar el instrumento como argumento de `FxcmBroker.__init__`, manteniendo
EUR/USD como valor por defecto para no romper nada.

Coordinar con el Agente B: es el mismo refactor que él necesita. **Que lo haga A
y B lo consuma**, para no duplicarlo.

Nuevo `scripts/download_history.py`:

```
--symbols EUR/USD,XAU/USD,GBP/USD --timeframes h4,d1 --years 10
```

Sale un CSV por combinación en `data/history/` con el nombre ya usado:
`{symbol_slug}_{tf}_{desde}_{hasta}.csv`.

## A2. Workflow de descarga

`.github/workflows/download.yml`, disparo manual (`workflow_dispatch`) con
símbolos, timeframes y años como inputs.

Punto crítico: **el job corre dentro de un contenedor `python:3.7-slim`**, no en
el runner directamente. El runner `ubuntu-latest` es 24.04 y ya no ofrece Python
3.7; el contenedor lo hace independiente de la imagen del runner.

```yaml
jobs:
  download:
    runs-on: ubuntu-latest
    container: python:3.7-slim
    steps:
      - uses: actions/checkout@v4
      - run: pip install "forexconnect==1.6.5.1" "pandas<2" "numpy<1.22"
      - run: python scripts/download_history.py --symbols "${{ inputs.symbols }}" ...
        env:
          FXCM_USER: ${{ secrets.FXCM_USER }}
          FXCM_PASS: ${{ secrets.FXCM_PASS }}
          FXCM_CONNECTION: Demo
      - uses: actions/upload-artifact@v4
```

**Riesgo número uno de todo el plan:** ese SDK 1.6.5.1 es de varias versiones
atrás y no está garantizado que los servidores de FXCM lo sigan aceptando.
**Primera tarea del Agente A, antes de construir nada más:** un job mínimo que
solo se conecte y baje 10 velas. Si falla, el plan B es descargar el histórico en
tu Mac (donde el SDK actual sí funciona) y subir solo los CSV; el precálculo, que
es la parte cara, se queda igualmente en Actions porque **no necesita
forexconnect**.

## A3. Workflow de precálculo FSR

`.github/workflows/precompute.yml`. Aquí no hay restricción de versión: solo
`numpy`, `scipy` y `pandas`, así que Python 3.11 y `ubuntu-latest` a secas.

- Matriz sobre (símbolo × timeframe) para paralelizar entre jobs.
- `-j $(nproc)`: en Actions saturar la máquina no cuesta nada, es lo que quieres.
- El `cached_features` ya trae checkpointing y caché incremental, así que un job
  que se corte no pierde el trabajo si se restaura la caché previa
  (`actions/cache` sobre `data/fsr_cache/`).

**Presupuesto de minutos, que conviene mirar antes de lanzar barridos.** Con el
coste medido de 0,94 s por ventana:

| Timeframe | Barras en 10 años | Minutos en 4 vCPU |
|---|---|---|
| D1 | ~2.600 | ~10 |
| H4 | ~15.600 | ~61 |
| H1 | ~62.000 | ~243 |

El plan Free da **2.000 min/mes en repos privados** e ilimitado en públicos. Un
barrido de 4 símbolos en D1+H4 son ~285 min: cabe. El mismo barrido en H1 se
come 16 horas y no cabe. **Otra razón para trabajar en D1/H4**, además de que es
lo que el diagnóstico de sobreajuste recomienda.

## A4. Publicación y consumo de artefactos

La caché de FSR pesa 4-8 MB por combinación. Opciones, de mejor a peor:

1. **GitHub Release** con tag `cache-YYYYMMDD`: permanente, descargable sin
   autenticación, versionado. Recomendada.
2. Artifacts: caducan a los 90 días y requieren token para descargar.
3. Commitear al repo: infla el historial con binarios. Evitar.

Nuevo `scripts/fetch_cache.py` que baja el Release y deja los ficheros en
`data/fsr_cache/` y `data/history/`. Con eso, en tu Mac o en el servidor solo
haces `fetch` y entrenas.

## A5. Seguridad de las credenciales

Van como **GitHub Secrets**, nunca en el repo. Tres reglas que no son opcionales:

- **Solo credenciales de la cuenta demo.** Un secret de CI es accesible a
  cualquiera con permiso de escritura en el repo y a cualquier workflow que
  alguien logre inyectar.
- Si el repo es **público**, no habilitar workflows que corran con secrets desde
  `pull_request` de terceros (es la vía clásica de exfiltración).
- `FXCM_CONNECTION` fijado a `Demo` en el workflow, no como input configurable.

## Entregables del Agente A

- `broker.py` con instrumento parametrizado (contrato compartido con B)
- `scripts/download_history.py` multi-símbolo
- `scripts/fetch_cache.py`
- `.github/workflows/{smoke-fxcm,download,precompute}.yml`
- Tests: nombres de fichero, parseo de argumentos, e integridad del artefacto descargado

---

# Agente B — Multi-instrumento y selección de símbolo/periodicidad

**Objetivo:** que el bot opere cualquier símbolo, y que elija cuál con un
protocolo que no se engañe a sí mismo.

## B1. Sacar el instrumento de las constantes globales

Hoy hay dos constantes de módulo que rompen todo lo que no sea EUR/USD:

- `PIP = 0.0001` en `config.py`, usada en `backtest.py`, `broker.py`, `mock.py`,
  `rl/env.py` y `rl/train.py`. En XAU/USD el pip es 0,01: **el coste de spread
  saldría 100× mal**.
- `min_lot = 1000` en `RiskParams` (micro-lote FX). El oro no se lotea así.

Además el dimensionamiento del entorno se rompe de forma silenciosa. En
`rl/env.py::target_position`:

```python
units = int(amount / price // params.min_lot) * params.min_lot
```

Con oro a ~4.000 $/oz y `max_trade_amount = 10.000`: `10000/4000 = 2,5`, que al
redondear a múltiplos de 1.000 da **0 unidades**. El agente no podría abrir
posición y el fallo no daría ningún error, solo un CRR de 0,00 % — exactamente
el síntoma que ya nos costó una tarde diagnosticar con las features sin escalar.

**Solución: `InstrumentSpec`** en `config.py`, y que `EnvParams` lo lleve dentro:

```python
@dataclass(frozen=True)
class InstrumentSpec:
    symbol: str            # "EUR/USD", "XAU/USD"
    pip: float             # 0.0001 | 0.01
    min_lot: int           # unidades mínimas negociables
    typical_spread_pips: float
    quote_currency: str = "USD"
```

Con un pequeño catálogo (`INSTRUMENTS = {...}`) y `PIP` conservado solo como
alias de EUR/USD para no romper las estrategias de referencia.

**Test obligatorio** — el que habría cazado el fallo de las 0 unidades:
para cada instrumento del catálogo, `target_position` con `a₂ = 1` debe devolver
una posición distinta de cero. Y otro: el coste en dinero de mover N unidades
debe escalar con el `pip` correcto del instrumento.

## B2. Normalizar la escala de las features por instrumento

`EnvParams.feature_scale = 200.0` se calibró midiendo σ ≈ 5,12e-3 en EUR/USD H1.
El oro tiene volatilidad relativa 3-5× mayor y D1 mucho más que H1, así que un
200 fijo devuelve el problema que ya arreglamos, en otro sitio.

Calcularlo del **tramo de entrenamiento** (nunca del de test) y guardarlo en el
`ModelRecord`: `feature_scale = 1 / std(features_train)`. Ya hay precedente —
`FsrppoPolicy.from_record` reconstruye los parámetros con los que se entrenó.

## B3. Protocolo de selección — el punto delicado

Elegir "el mejor símbolo y periodicidad" probando N combinaciones y quedándose
con la que mejor puntúa en test **no mide nada**: con 12 combinaciones y 10
semillas son 120 sorteos, y el ganador es sobre todo el más afortunado. Es
exactamente el error que el veredicto actual (0/10) nos permitió evitar.

**Partición en tres tramos, cronológica:**

```
├──────── train 60 % ────────┤── validación 20 % ──┤──── test 20 % ────┤
         entrena aquí          elige aquí            se mide UNA vez
```

- Se entrenan todas las combinaciones (símbolo × timeframe × semilla) en *train*.
- Se elige la combinación ganadora por su métrica en *validación*.
- Se reporta **solo** el resultado de la ganadora en *test*, y ese número es el
  que cuenta. El tramo de test no se toca hasta el final, y se toca una vez.

Criterio de selección en validación: Sharpe mediano entre semillas, no el mejor
—la mediana es robusta al afortunado— exigiendo además CRR > Buy & Hold.

Nuevo `scripts/select_market.py`:

```
uv run python scripts/select_market.py \
    --symbols EUR/USD,XAU/USD,GBP/USD,USD/JPY \
    --timeframes h4,d1 --seeds 5
```

Salida: tabla por combinación con métricas de validación, la ganadora marcada, y
su resultado en test con el veredicto de siempre (Sharpe > 0 y CRR > B&H en ≥7
de cada 10 semillas). Guardar el barrido completo en
`data/selection/<fecha>.json` para poder auditarlo después.

**Registrar también las que pierden.** Si 12 de 12 combinaciones fallan, ese es
el resultado y hay que publicarlo, igual que se publicó el 0/10.

## B4. Interfaz

Añadir a `/models` un selector de instrumento y una pestaña con el ranking del
último barrido. `ModelRecord` ya tiene el campo `instrument`; hoy siempre vale
`"EUR/USD"`.

## Entregables del Agente B

- `InstrumentSpec` + catálogo, con `PIP` global retirado del camino de FSRPPO
- `feature_scale` calculado del tramo de entrenamiento
- `Dataset.split_three_way()` y `scripts/select_market.py`
- Tests: sizing por instrumento distinto de cero, escalado del coste por `pip`,
  y que el tramo de test **no** influye en la selección
- UI: selector de instrumento y ranking

---

# Agente C — Despliegue

**Objetivo:** interfaz en Vercel, bot corriendo 24/5 en algo gratuito, y sin
regalar el control del bot a internet.

## C1. Inferencia sin torch (hacer esto primero — desbloquea el resto)

Exportar la política entrenada a numpy:

```python
# rl/export.py
def export_policy(agent, path):     # -> policy.npz con W1,b1,W2,b2,W3,b3
def load_numpy_policy(path):        # -> NumpyPolicy con .act(obs)
```

El forward es literalmente `tanh(tanh(x@W1+b1)@W2+b2)@W3+b3`, y luego
`softplus(·)+1` para (α, β) de la Beta. La acción determinista es la media
`α/(α+β)`, que es lo único que usa el bot en producción.

**Test irrenunciable:** para 1.000 observaciones aleatorias, `NumpyPolicy.act`
debe coincidir con `PPOAgent.act(deterministic=True)` dentro de 1e-6. Es el mismo
tipo de test que ya validó el spline propio contra scipy.

Con esto `requirements-bot.txt` queda en numpy + scipy + pandas + fastapi +
uvicorn + forexconnect: instalable en Python 3.7 y ~80 MB.

## C2. Autenticación — bloqueante

Hoy cualquiera que alcance el puerto puede pausar el bot, cambiar credenciales y
lanzar órdenes. En localhost es asumible; expuesto, no.

Mínimo imprescindible antes de abrir nada:

- Token en cabecera (`Authorization: Bearer …`) leído de variable de entorno,
  verificado con `secrets.compare_digest`, en un middleware que cubra todo
  `/api/*` y el WebSocket.
- CORS restringido al dominio de Vercel (hoy está fijo a `localhost:3000`).
- HTTPS por delante, siempre.

## C3. Frontend en Vercel

Encaja sin fricción: `web-ui/` es Next.js 14 y ya compila (11 rutas estáticas).

- Root directory: `web-ui`
- `NEXT_PUBLIC_BACKEND_URL` apuntando al backend público
- Los `rewrites` de `next.config.js` hoy apuntan a `localhost:8000`: hay que
  hacerlos configurables por entorno
- El WebSocket debe ir a `wss://` del backend, no a Vercel

## C4. Dónde vive el backend

Aquí es donde "gratuito" se complica, y conviene ser explícito. Recordatorio:
**x86_64 + Python 3.7**, proceso persistente, 24/5.

| Opción | Gratis | Sirve | Observaciones |
|---|---|---|---|
| **Cloudflare Tunnel a tu Mac** | Sí | **Sí** | El bot sigue donde ya funciona, con el SDK actual y sin el riesgo del 1.6.5.1. Sales a internet sin abrir puertos. Depende de que la Mac esté encendida (`caffeinate`) |
| **Oracle Cloud Always Free (AMD x86 micro)** | Sí, permanente | Sí | 1/8 OCPU y 1 GB de RAM: justo, pero el bot sin torch cabe. **Las instancias Ampere ARM no valen**: no hay wheel |
| Google Cloud e2-micro free tier | Sí | Sí | x86, similar a lo anterior |
| Fly.io / Render / Railway | Parcial | **No** para free | Los planes gratuitos duermen el servicio por inactividad, y un bot que duerme se pierde el cierre de vela |
| Vercel | Sí | **No** | Serverless, 250 MB, sin proceso persistente |

**Recomendación: empezar por el túnel a tu Mac.** Entrega interfaz pública y bot
funcionando sin apostar por el SDK antiguo, y deja la migración a Oracle como
paso 2, ya con el smoke test del Agente A resuelto.

## C5. Empaquetado

`Dockerfile` sobre `python:3.7-slim` para el bot (sin torch), y un `compose` con
el volumen de `data/` para que la base SQLite y los modelos persistan.

El entrenamiento **no** va en esa imagen: corre en Actions o en tu Mac, y publica
el `policy.npz` que el bot consume.

## Entregables del Agente C

- `rl/export.py` + `NumpyPolicy` + test de equivalencia con torch
- Middleware de autenticación por token + CORS por entorno
- `Dockerfile` y `requirements-bot.txt` sin torch
- Frontend desplegado en Vercel con backend configurable
- Documento de operación: cómo publicar un modelo nuevo al bot en producción

---

## Contratos entre agentes (fijar antes de escribir código)

Sin esto los tres se pisan:

1. **Instrumento parametrizado** (A1/B1): lo escribe **A**, lo consume B. Firma
   acordada: `FxcmBroker(creds, instrument="EUR/USD")`.
2. **Nombre de los ficheros de datos**:
   `data/history/{symbol_slug}_{tf}_{YYYYMMDD}_{YYYYMMDD}.csv`, con
   `symbol_slug = symbol.replace("/","").lower()`. Ya es el formato existente.
3. **Clave de la caché FSR**: no tocar. `fsr_{params.cache_key()}.npz`, indexada
   por ventana. Cambiarla obliga a recalcular todo.
4. **`ModelRecord`**: B añade `feature_scale` e `instrument` real; C solo lee.
   Los campos existentes no se renombran.
5. **Formato del modelo publicado**: `policy.npz` (C) más el `meta.json` que ya
   escribe el registro.

## Orden sugerido

```
Semana 1   A: smoke test FXCM en py3.7  ← resuelve el riesgo mayor
           B: InstrumentSpec y sizing
           C: exportador numpy y autenticación
Semana 2   A: workflows de descarga y precálculo
           B: split en tres tramos y select_market.py
           C: Vercel + túnel, bot en producción sin torch
Semana 3   Barrido de selección con el cómputo ya en Actions, y veredicto
```

## Cómo se sabe que funcionó

- `scripts/fetch_cache.py` trae de un Release datos y caché que tú no calculaste.
- `select_market.py` produce un ranking en validación y **un solo** número de test.
- La interfaz en Vercel enseña el estado del bot en producción, con token.
- El bot lleva 5 días operando en papel sin caerse y sin torch instalado.
- Y el criterio de siempre sigue mandando: si ninguna combinación da Sharpe > 0
  y CRR > Buy & Hold en ≥7 de 10 semillas en el tramo de test, **no se activa
  auto-trading**, se publica el resultado negativo y ya está.
