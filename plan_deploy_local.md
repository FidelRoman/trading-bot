# Quitar el modo "paper": el bot opera de verdad, Demo o Real desde Ajustes

## Contexto

Hoy el bot tiene **tres** modos de ejecución (`src/tradingbot/web/app.py:68`): `sim`,
`paper` y `live`. `paper` toma precios reales de FXCM pero deja el bróker en
`read_only=True` y simula los fills con `PaperBroker`. Ese modo solo se elige por
variable de entorno (`EXECUTION_MODE`), no hay forma de cambiarlo desde la
interfaz, y `.env.example` lo trae puesto por defecto.

Lo que se quiere: **el bot manda órdenes de verdad siempre**, y desde `/settings`
se elige la cuenta contra la que las manda — **Demo** o **Real**. El modo papel
desaparece; solo queda el simulado (`MOCK=1`) como doble para tests y desarrollo
sin credenciales.

Además hay dos cosas que impiden que eso funcione hoy y que este plan arregla:

1. **`FxcmCredentials` congela el entorno en el import.** `config.py:237-242` usa
   `os.getenv(...)` como valor por defecto del `dataclass`, evaluado una sola vez
   al importar el módulo. Verificado: tras cambiar `os.environ["FXCM_USER"]`,
   `load_settings().fxcm.user` sigue devolviendo el valor viejo. Consecuencia
   directa: `POST /api/credentials` escribe el `.env`, cambia la DB (eso sí usa
   `default_factory`) y luego **reconstruye el bróker con las credenciales
   antiguas**. Cambiar de Real a Demo desde el panel hoy te deja conectado a Real.
2. **No hay un sitio donde guardar las dos cuentas.** El `.env` solo tiene un par
   `FXCM_USER`/`FXCM_PASS`, así que alternar Demo/Real obliga a reteclear la
   contraseña cada vez.

Cierre de la entrega: dejar **abierta una posición larga de EUR/USD de 1.000
unidades (0,01 lotes), sin SL ni TP, en la cuenta demo**, y el auto-trading
apagado (se enciende a mano desde el dashboard).

---

## Alcance

### 1. Un solo bróker simulado: `MockBroker` absorbe a `PaperBroker`

`PaperBroker` (`src/tradingbot/paper_broker.py`) ya hereda de `MockBroker` y solo
añade dos cosas que el simulado necesita igualmente: la **posición neta**
(`set_position`, la interfaz que exige FSRPPO en `engine.py:511-541`) y la
**persistencia de estado** entre reinicios.

- Mover a `src/tradingbot/mock.py`: `set_position`, `_realise`,
  `_update_entry_price`, `close_position`, `floating_pl`, `recent_fills`,
  `lot_size`, `units_for_lots`, `_restore`/`persistent_state`/`_persist`, y los
  parámetros de constructor `spec`, `persisted_state`, `state_callback`,
  `spread_pips`.
- **No** se porta `price_source`: era la esencia del modo papel.
- Fusionar los dos libros en vez de que uno tape al otro. Hoy
  `PaperBroker.open_trades` (paper_broker.py:192) sobrescribe el de `MockBroker`
  (mock.py:119) y esconde los trades con SL/TP. En el simulado unificado
  `open_trades()` devuelve **las operaciones con SL/TP más la fila de posición
  neta** (`trade_id` `"sim-net"`), y `account_info()` suma el flotante de ambos
  libros sobre un único `_equity`.
- `mode` se queda en `"simulado"`; `account_id` en `"SIM-0001"`.
- Borrar `src/tradingbot/paper_broker.py`.
- Clave de estado en el store: `"paper_broker"` → `"mock_broker"`, leyendo la
  vieja como respaldo en `_make_broker` para no perder el estado simulado ya
  guardado.

### 2. Dos modos de ejecución: `sim` y `live`

En `src/tradingbot/web/app.py`:

- `execution_mode()` (línea 68) pasa a devolver solo `"sim"` (con `MOCK=1` o sin
  credenciales) o `"live"`. Se elimina la lectura de `EXECUTION_MODE`.
- `_make_broker()` (línea 127) queda en dos ramas: `MockBroker(...)` o
  `FxcmBroker(settings.fxcm, instrument=symbol)`. Desaparece la construcción con
  `price_source=FxcmBroker(..., read_only=True)`.
- `pause_if_real()` (línea 109) se simplifica a `settings.fxcm.connection == "Real"`.
- `/api/instruments/refresh` (línea 928) ya no necesita `getattr(broker, "_source", …)`.
- `/api/instrument/subscribe` (línea 942) sigue con su `hasattr(broker, "subscribe")`:
  en simulado no hay nada que suscribir.

Se conserva el flag `read_only` de `FxcmBroker` y su `_assert_trading_enabled()`
(`broker.py:407`): ya no lo usa ningún modo, pero es la red que impide que un
camino nuevo mande órdenes por accidente, y `tests/test_net_position.py:220` lo
cubre.

### 3. Credenciales por cuenta, resueltas en caliente

En `src/tradingbot/config.py`:

- Convertir `FxcmCredentials` para que **lea el entorno en cada instancia**
  (`field(default_factory=...)` o un `from_env()` que use `load_settings()`),
  eliminando el congelado de import. Esto es lo que hace que el conmutador de
  Ajustes tenga efecto real.
- Resolución por conexión, con respaldo al par genérico:
  `Demo` → `FXCM_USER_DEMO`/`FXCM_PASS_DEMO`, si no `FXCM_USER`/`FXCM_PASS`;
  `Real` → `FXCM_USER_REAL`/`FXCM_PASS_REAL`, si no `FXCM_USER`/`FXCM_PASS`.
  El `.env` actual ya trae `FXCM_USER_DEMO`/`FXCM_PASS_DEMO` (los usa hoy solo
  `scripts/probe_offers.py`), así que el esquema encaja con lo que hay.
- `_db_path()` (línea 252) no se toca: ya separa `tradingbot-demo.db` de
  `tradingbot-real.db`.

En `web/app.py`:

- `POST /api/credentials` (línea 394) admite un cuerpo con **solo**
  `{"connection": "Demo"|"Real"}`: recupera el par guardado de esa cuenta, valida
  con login real, escribe `FXCM_CONNECTION` con `update_env_file` y hace el swap
  en caliente. Cuando vengan `user`/`password`, los guarda en las claves de esa
  conexión (`FXCM_USER_DEMO`/…) además del par genérico.
- Se elimina el comentario de las líneas 458-460 sobre el modo paper; el motivo
  de reconstruir con `_make_broker` en vez de asignar el candidato pasa a ser el
  instrumento y la spec seleccionados.
- `GET /api/credentials` (línea 369) añade qué conexiones tienen credenciales
  guardadas, para que la UI sepa si puede conmutar sin pedir contraseña.

### 4. Órdenes manuales sin SL/TP

Hoy `BotEngine.manual_order` (`engine.py:226`) rechaza `sl_pips <= 0 or tp_pips <= 0`,
y `FxcmBroker.open_position` (`broker.py:427`) siempre manda `PEG_OFFSET_STOP` y
`RATE_LIMIT`. Para poder dejar la posición larga desnuda que se pide:

- `manual_order`: `sl_pips`/`tp_pips` iguales a 0 significan "sin protección";
  solo se rechazan los negativos. El texto del log lo dice explícitamente.
- `FxcmBroker.open_position`: construir los `kwargs` de `create_order_request` y
  añadir `PEG_TYPE_STOP`/`PEG_OFFSET_STOP` solo si `stop_pips > 0`, y `RATE_LIMIT`
  solo si `take_profit > 0`.
- `open_position_pips` (`broker.py:448`): calcular `tp` solo si `tp_pips > 0`.
- Mismo trato en el simulado (`mock.py:147`/`:168`): sin `stop`/`limit`,
  `_check_sl_tp` (mock.py:183) debe saltarse esa operación en vez de romper.

### 5. Interfaz

- `web-ui/lib/types.ts:191`: `execution_mode: "sim" | "live"`.
- `web-ui/components/InstrumentPicker.tsx:148-150`: fuera la rama `"paper"` y el
  texto `"PAPEL — precios reales, ejecución simulada"`. Quedan dos:
  `ÓRDENES REALES — cuenta {connection}` (rojo) y `SIMULADO — precios sintéticos`.
- `web-ui/app/settings/page.tsx`: nueva tarjeta **CUENTA DE EJECUCIÓN** encima de
  los campos numéricos, con un selector Demo/Real que hace
  `postJSON("/api/credentials", { connection })` reutilizando el cliente de
  `web-ui/lib/api.ts`. Elegir **Real** exige un `confirm()` explícito (mismo
  patrón que `StrategyControls.tsx:62`) y muestra el aviso de que las órdenes van
  a dinero real. El array `FIELDS` de esa página no se toca.
- `web-ui/components/AccountCard.tsx`: refleja qué cuenta está activa y cuáles
  tienen credenciales guardadas, en lugar de asumir un único par.

### 6. Tests

- `tests/test_paper_broker.py` → `tests/test_mock_broker.py`, adaptado a
  `MockBroker` (mismo contenido de contabilidad de posición neta y persistencia)
  y ampliado con el caso nuevo: SL/TP y posición neta conviviendo en
  `open_trades()`.
- `tests/test_execution_mode.py`: eliminar los casos de `paper` y de
  `EXECUTION_MODE`; dejar `sim` vs `live` y la pausa en Real. Añadir:
  - **regresión de credenciales**: cambiar `os.environ` y comprobar que
    `load_settings().fxcm` refleja el cambio (hoy falla);
  - resolución por conexión (`FXCM_USER_DEMO` con `FXCM_CONNECTION=Demo`, y el
    respaldo al par genérico).
- `tests/test_net_position.py`, `tests/test_runtime.py`,
  `tests/test_engine_settings.py:50`: actualizar los imports de `PaperBroker`.
- Nuevo caso en el test del engine: orden manual con `sl_pips=0, tp_pips=0`
  aceptada, y con valores negativos rechazada.

### 7. Documentación

Quitar el modo papel de: `.env.example` (bloque `EXECUTION_MODE`, líneas 10-14),
`README.md:8` ("Alcance actual: backtest y paper trading. No envía órdenes
reales."), `docs/local.md:55-67` (tabla de modos) y `:149-151`,
`docs/runbook.md:41`, `:120-135`, `:200-210` (el playbook "papel → demo → real"
pasa a "demo → real"), y `PLAN.md:20,29,115,189`.

**Ojo:** en este repo "paper" también significa *el artículo científico* FSRPPO.
`PaperMetrics`, `metrics.py`, `web-ui/components/metrics.tsx`,
`web-ui/app/models/page.tsx` y casi todas las menciones de `README.md` y
`PLAN.md` son eso y **no se tocan**.

---

## La posición larga en demo

Después de que la batería pase, y como paso operativo aparte:

1. Verificar que el par demo del `.env` (`FXCM_USER_DEMO` / `FXCM_PASS_DEMO`)
   entra: `uv run python scripts/check_connection.py` con `FXCM_CONNECTION=Demo`.
   Si el login falla, paro y te pido credenciales demo válidas.
2. Comprobar el estado de suscripción de EUR/USD en esa cuenta; si no está en
   `"T"`, `uv run python scripts/subscribe_instrument.py EUR/USD`
   (las cuentas demo traen instrumentos en `"V"`/`"D"`).
3. Arrancar el backend, entrar en `/settings` y **seleccionar Demo desde la
   interfaz** — es la prueba de que el conmutador funciona de verdad. Verificar
   en `GET /api/instrument` que devuelve `execution_mode: "live"`,
   `connection: "Demo"`, y en la barra lateral el chip `FXCM-DEMO`.
4. Dejar el bot **pausado** (`POST /api/control/pause`).
5. Abrir la posición: `POST /api/manual/long` con
   `{"lots": 0.01, "sl_pips": 0, "tp_pips": 0}` → 0,01 × 100.000 = **1.000
   unidades**, sin protecciones.
6. Confirmar contra el bróker, no contra nuestra propia UI: `GET /api/positions`
   y `broker.open_trades()` deben mostrar la operación con su `trade_id` de FXCM,
   y `account_info()` el margen usado.

Riesgo asumido y explícito: la posición queda abierta y sin stop en la cuenta
demo hasta que la cierres desde el panel (`POST /api/close/{trade_id}`).

---

## Verificación

```bash
uv run pytest -q                                   # la batería completa (227 casos hoy)
grep -rn --include="*.py" --include="*.ts*" "PaperBroker\|EXECUTION_MODE" src tests web-ui
# ^ debe salir vacío; las menciones de "paper" que queden son las del artículo

cd web-ui && npm run build                         # el export estático que sirve FastAPI
caffeinate -s uv run uvicorn tradingbot.web.app:app --port 8000
```

Recorrido manual en <http://localhost:8000>:

1. `/settings` → conmutar a **Demo**; el chip de la barra lateral pasa a
   `FXCM-DEMO` y la banda del selector de instrumento dice `ÓRDENES REALES —
   cuenta Demo` en rojo.
2. Conmutar a **Real** → aparece la confirmación, el bot se pausa solo y la banda
   avisa. Volver a Demo.
3. `/` → abrir la larga de 0,01 lotes sin SL/TP; aparece en `PositionsPanel` con
   su `trade_id` de FXCM y P&L flotante moviéndose con el precio real.
4. Con `MOCK=1`, el mismo recorrido funciona sobre `MockBroker`: banda
   `SIMULADO`, órdenes simuladas, y la posición neta persiste tras reiniciar el
   proceso (clave `mock_broker` del store).
5. `/history` y `/activity` registran la orden manual.

## Lo que este plan NO hace

- No activa el auto-trading. El bot queda pausado y se enciende con el toggle del
  dashboard, según lo que elegiste.
- No toca la estrategia ni el veredicto de validación: `data/models/` sigue sin
  `active.json`, así que aunque se le dé a INICIAR con FSRPPO, el motor loguea
  "no hay modelo entrenado seleccionado" y no ordena nada. Si quieres que el bot
  opere solo de verdad, hay que promover un modelo o cambiar a una de las
  estrategias clásicas — dímelo y lo hago aparte.
