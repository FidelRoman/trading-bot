# Plan — Bot de trading FSRPPO (EUR/USD H1) con interfaz web

## Contexto

**Qué se quiere.** Implementar la estrategia del paper *"An adaptive financial trading strategy based
on proximal policy optimization and financial signal representation"* (Lin Wang, Xuerui Wang —
*Engineering Applications of Artificial Intelligence* 138 (2024) 109365, DOI
`10.1016/j.engappai.2024.109365`) dentro de un bot con interfaz visual para configurar la cuenta,
arrancar/pausar, ver resultados, backtestear y consultar el historial.

**Por qué ahora.** Tu bot anterior (`~/GitHub/trading-bot-obs`, Bollinger 15m sobre FXCM) está
pausado a propósito: el grid search con validación train/test no encontró ninguna combinación con
Profit Factor ≥ 1 en ambos tramos. La estrategia de reversión con TP en banda media no tiene ventaja
en EUR/USD 2024-2026. FSRPPO es un enfoque distinto: en vez de una regla fija, un agente PPO aprende
la política de posicionamiento sobre una señal de precio *denoised*.

**Resultado esperado.** Un proyecto nuevo en `~/GitHub/trading-bot` que reutiliza toda la
infraestructura ya probada (FastAPI + WebSocket, broker ForexConnect, store SQLite, UI Next.js 14) y
añade el núcleo del paper: FSR (CEESMDAN + MRS), entorno de trading RL, PPO propio, registro de
modelos y una pestaña de entrenamiento. **Alcance de ejecución: backtest + trading en cuentas Demo/Real.**

### Decisiones ya tomadas

| Decisión | Elección |
|---|---|
| Base de código | Fork de `trading-bot-obs` → `trading-bot` |
| Mercado / timeframe | EUR/USD, **H1** por defecto (configurable) |
| Ejecución | Backtest + trading Demo/Real |
| Stack RL | PyTorch + PPO propio (Algoritmo 1 del paper) |
| Benchmarks | Se conservan Bollinger/RSI/Wyckoff + se añade Buy&Hold |
| Instrumentos | Solo EUR/USD (arquitectura preparada para más) |

---

## Qué dice el paper (resumen operativo)

**FSR — representación de la señal financiera** (§2.1, Algoritmos 2-4 del apéndice):

1. **ESMD** (Alg. 2): tamiza la señal; en cada iteración busca los extremos locales, calcula los
   puntos medios de los segmentos que unen extremos adyacentes, interpola `C` splines cúbicos sobre
   esos puntos medios, promedia (`CSI`) y resta. Se detiene cuando `max|CSI| ≤ δ` o `d > D`.
   `IMF_i = CSI`, residuo `L_i = X − IMF_i`. Repite mientras el residuo tenga > `Φ` extremos.
2. **CEESMDAN** (Alg. 3): en cada nivel `i` añade ruido blanco adaptativo
   `X + ξ_{i-1}·G_{i-1}(W_j)` para `j = 1..J`, descompone con ESMD y promedia el primer IMF sobre las
   `J` realizaciones. Elimina el *mode mixing* del ESMD.
3. **MRS** (Alg. 4): R/S reescalado modificado con la corrección de Anis-Lloyd/Peters
   (`E(R/S)_v`, con dos ramas según `v ≤ 340`). Regresión de `ln H_v` sobre `ln v` → exponente de Hurst.
4. **Reconstrucción**: se descartan las IMFs con `0 ≤ H ≤ 0.5` (ruido de alta frecuencia) y se suman
   las de `0.5 < H ≤ 1` (memoria larga) + residuo. Ese es el estado limpio.

**PPO sobre el estado FSR** (§2.2-2.3, Algoritmo 1):

- Estado: `s_t = (p_{t-49}, …, p_t) ∈ R^50` pasado por FSR.
- Acción continua `a_t = (a₁, a₂) ∈ [0,1]²`. `a₁ ∈ [0,⅓)` compra, `[⅓,⅔]` mantiene, `(⅔,1]` vende.
  `a₂` es la fracción del importe: `α_trade = a₂·(α_max − α_min)`.
- Recompensa (ec. 11): `Δp·μ_t` (participación operada) + `Δp·(κ_t − μ_t)` (posición mantenida)
  `− α_tax·p_t·μ_t` (coste). Mantener posición ⇒ solo el segundo término, coste 0.
- Redes: política y valor **separadas**, MLP 2 capas ocultas de 256, activación tanh, Adam lr=1e-5,
  entropía `c`=0.01, GAE `λ`=1, 200 épocas. `α_initial`=10 000, `α_max`=10 000, `α_min`=1 000,
  `α_tax`=0.015 %, `C`=2, `δ`=0.001, `D`=100, `Φ`=`Φ'`=6.
- Métricas (Tabla 2): CRR, ARR, AVR, MD, Sharpe (Rf=2.7855 %), Calmar, Sortino.
- Ablaciones (§4): sin FSR o con EMD/ESMD el rendimiento se hunde; BiLSTM/LSTM sobreajustan y CNN
  infraajusta ⇒ **el MLP 256-256 es la elección correcta, no un atajo**.

### Adaptaciones necesarias (paper = acciones long-only; nosotros = FX)

Cada desviación va documentada en el código y es configurable:

| Paper | Nuestra implementación | Motivo |
|---|---|---|
| Caja + acciones, long-only | Posición neta con signo (largo/plano/corto) en unidades de EUR | En FX se puede vender en corto; limitar a long-only tiraría la mitad de las oportunidades |
| `α_tax`·p·μ (impuesto) | `spread_pips · PIP · |Δunidades|` + swap opcional | El coste real en FX es el spread, no un impuesto |
| Estado = solo precios | FSR(50) **+ 3 features de cuenta** (posición neta normalizada, P&L no realizado, exposición usada) | Sin saber su posición actual el agente no observa el MDP completo |
| Sin normalizar | FSR dividido por el último precio de la ventana (retornos relativos) | Con niveles absolutos la política no generaliza del tramo de train al de test |
| Anualización con 250 días | `bars_per_year` según timeframe (H1 ≈ 6 240) | Para que ARR/AVR/Sharpe sean comparables |
| Gaussiana implícita | Distribución **Beta(α,β)** por dimensión | Soporte natural en [0,1]²; una Gaussiana recortada sesga las acciones extremas |

---

## Arquitectura

### Paso 0 — Fork del repo

```
rsync -a --exclude .venv --exclude node_modules --exclude .next --exclude History \
      --exclude 'data/*.db' --exclude .env --exclude .DS_Store \
      ~/GitHub/trading-bot-obs/ ~/GitHub/trading-bot/
```

Se conserva `.git` (historial) pero se comprueba y elimina cualquier `git remote` heredado.
`trading-bot-obs` queda intacto como archivo. Se actualizan `pyproject.toml`
(nombre, descripción, `+torch>=2.2`, `+scipy>=1.11`) y `README.md`.
Python sigue fijado a **3.10** por el wheel de `forexconnect`; torch 2.x soporta 3.10 en macOS ARM
(backend MPS). Tras cada `uv sync` hay que volver a correr `scripts/fix_forexconnect_macos.sh`.

### Módulos nuevos

```
src/tradingbot/
  fsr/
    esmd.py        Algoritmo 2 — ESMD (splines cúbicos vía scipy.interpolate.CubicSpline)
    ceesmdan.py    Algoritmo 3 — ensemble con ruido adaptativo
    mrs.py         Algoritmo 4 — R/S modificado → Hurst
    represent.py   fsr_window(prices) -> np.ndarray  (descompone, filtra H>0.5, suma)
    cache.py       precálculo paralelo (ProcessPoolExecutor) + caché .npz por hash de params
  rl/
    env.py         FxTradingEnv — estado, acción (a₁,a₂), recompensa ec. 11 adaptada
    networks.py    PolicyNet (Beta) y ValueNet: MLP 256-256 tanh, separadas
    ppo.py         Algoritmo 1 — GAE(λ=1), clip ε, entropía, Adam
    train.py       bucle de entrenamiento, checkpoints, curvas, evaluación en test
    registry.py    modelos versionados en data/models/<run_id>/
    policy.py      carga de modelo + inferencia de una acción (para engine y backtest)
  metrics.py       CRR, ARR, AVR, MD, SPR, CR, STR (Tabla 2 del paper)
  web/
    training_job.py  job de entrenamiento en hilo (mismo patrón que backtest_job.py)
```

### Módulos que se modifican

- **`config.py`**: `TIMEFRAME = "H1"`; nuevas dataclasses `FsrParams` (M=50, J, ξ, C=2, δ=0.001,
  D=100, Φ=6, hurst_threshold=0.5, normalize) y `PpoParams` (γ, λ=1, ε_clip=0.2, c_entropy=0.01,
  lr=1e-5, NI, NE, T, hidden=(256,256)) y `EnvParams` (α_initial, α_max, α_min, max_units,
  spread_pips). Se reutiliza `update_env_file()` y el patrón de `_db_path()`.
- **`engine.py`**: `_candle_tick()` bifurca según `active_strategy`. Con `"fsrppo"` calcula la
  ventana FSR de la última barra cerrada, invoca `rl.policy.act()`, y **el overlay de riesgo
  existente sigue siendo el que manda**: `entry_allowed()`, `spread_ok()`, `daily_loss_limit`,
  `halted_until`, `max_trades_per_day`. El agente propone; el overlay veta.
- **`store.py`**: tablas `training_runs` (id, params, estado, métricas train/test, ruta) y
  `models` (id, run_id, activo, métricas). Se reutilizan `get_state`/`set_state`/`log`.
- **`backtest.py`**: se conserva íntegro para los benchmarks; se añade `buy_and_hold()` y
  `run_fsrppo_backtest()` que **reutiliza `FxTradingEnv`** en modo replay — el mismo simulador que
  entrena es el que backtestea, así no hay dos verdades.
- **`web/app.py`**: nuevos endpoints siguiendo los patrones ya existentes —
  `GET/POST /api/fsr/precompute` (progreso por WS), `GET/POST /api/training`,
  `GET /api/training/curve`, `GET /api/models`, `POST /api/models/{id}/activate`,
  `GET /api/fsrppo/state` (última descomposición: IMFs + Hurst, para el visor).

### Interfaz visual (Next.js 14, `web-ui/`)

Se conserva el shell actual (`Sidebar.tsx`, `Shell.tsx`, `lib/live.tsx` con WebSocket,
`components/charts.tsx`). Nuevas entradas en `NAV` de `Sidebar.tsx`:

| Página | Contenido |
|---|---|
| `/` Dashboard *(existente, extendido)* | Velas H1 + **señal FSR reconstruida superpuesta**, posición neta actual, acción del agente en la última barra, toggle arrancar/pausar, P&L del día, logs |
| `/fsr` **(nueva)** | Visor de la descomposición: IMFs apiladas con su Hurst, cuáles se descartan y por qué, señal reconstruida vs precio crudo. Botón "Precalcular caché" con barra de progreso |
| `/train` **(nueva)** | Formulario de entrenamiento (rango train/test, hiperparámetros PPO, nº de semillas), progreso en vivo por WS, curva de recompensa y de pérdida, tabla de checkpoints, botón "Promover a modelo activo" |
| `/models` **(nueva)** | Registro de modelos: métricas de test (las 7 del paper), fecha, hiperparámetros, activar/archivar |
| `/strategies` *(existente, extendido)* | Backtesting con **tabla comparativa** FSRPPO vs B&H / MACD / VMA / Turtle / Bollinger / RSI / Wyckoff, con CRR, ARR, AVR, MD, Sharpe, Calmar, Sortino y curvas de equity superpuestas |
| `/settings` *(existente)* | Credenciales FXCM (ya autodetecta Demo/Real), parámetros de riesgo, timeframe |
| `/history` y `/activity` *(existentes)* | Trades cerrados, curva de equity, log |

---

## Riesgos técnicos y cómo se abordan

1. **Coste de CEESMDAN.** Es el cuello de botella: `J` realizaciones de ruido × varias
   descomposiciones ESMD con splines, por cada barra. Mitigación: `fsr_window(prices)` depende
   **solo** de la ventana de 50 cierres que termina en `t` (es causal), así que se precalcula una vez
   por (instrumento, timeframe, rango, hiperparámetros FSR), se cachea en `.npz` indexado por hash y
   el entrenamiento lee de memoria. Precálculo paralelo con `ProcessPoolExecutor`. Estimación para
   2 años de H1 (~12 000 barras): 20-40 min la primera vez, instantáneo después.
2. **Hurst sobre 50 puntos es ruidoso.** El Algoritmo 4 recorre `v = 2..⌊N/2⌋`; con N=50 hay poquísimos
   subintervalos y el `H` estimado tiene varianza alta. Mitigación: `M` es configurable (50 como el
   paper, pero probaremos 128/256) y se valida con el test de fBm sintético descrito abajo. Si a 50
   el Hurst no separa señal de ruido, se sube `M` y se documenta.
3. **Fuga de futuro.** Es el error clásico al portar este tipo de papers. Defensas: FSR estrictamente
   causal (test automatizado), normalización solo con estadísticos de la ventana, ejecución a la
   apertura de la barra siguiente a la decisión, split temporal estricto y sin barajar.
4. **Los resultados del paper no se trasladan solos.** El paper reporta CRR de 150-600 % en 6 acciones
   chinas 2019-2022, con `α_tax` de 0.015 %. En EUR/USD H1 el spread (~1,2 pips) es un coste mucho
   mayor en relación al movimiento por barra. **Criterio de aceptación explícito antes de pasar a
   paper trading continuo: Sharpe > 0 y CRR > Buy&Hold en el tramo de test, en ≥ 7 de 10 semillas.**
   Si no se cumple, se reporta y el bot se queda en backtest — igual que hiciste con Bollinger.

---

## Fases de implementación

| # | Fase | Entregable | Días |
|---|---|---|---|
| 1 | Fork y limpieza | Repo arrancando (`uv run pytest`, backend y UI levantan) | 0,5 |
| 2 | FSR | `esmd.py`, `ceesmdan.py`, `mrs.py`, `represent.py`, `cache.py` + tests + CLI de precálculo | 3 |
| 3 | Entorno y métricas | `rl/env.py`, `metrics.py` + tests de conservación de caja y de recompensa | 2 |
| 4 | PPO | `networks.py`, `ppo.py`, `train.py`, `registry.py` + test de convergencia en entorno de juguete | 3 |
| 5 | Backtest y comparativa | `run_fsrppo_backtest()`, `buy_and_hold()`, tabla de 7 métricas vs benchmarks | 2 |
| 6 | Integración en el bot | `engine.py` modo fsrppo, `mock.py`, endpoints nuevos | 2 |
| 7 | Interfaz | Páginas `/fsr`, `/train`, `/models`; dashboard y backtesting extendidos | 3 |
| 8 | Validación | Entrenamiento train/test con 10 semillas, walk-forward, veredicto documentado | 2 |

Las fases 2-4 son independientes de la 6-7: se puede empezar a ver UI mientras se afina el modelo.

---

## Tests

Fase 2 (los que evitan que todo lo demás sea humo):

- `test_esmd_reconstruction`: `sum(IMFs) + residuo == señal original` con error < 1e-9.
- `test_esmd_imf_properties`: cada IMF cumple las dos condiciones de §2.1.1 (nº de máximos y mínimos
  difiere en ≤ 1; envolventes aproximadamente simétricas).
- `test_ceesmdan_reduces_mode_mixing`: sobre `sin(2πf₁t) + sin(2πf₂t)` con `f₂ ≫ f₁`, CEESMDAN separa
  las dos frecuencias en IMFs distintas mejor que ESMD (energía cruzada menor).
- `test_mrs_hurst`: `H ≈ 0.5 ± 0.1` para ruido blanco; `H > 0.65` para fBm con `H=0.75`;
  `H < 0.4` para una serie anticorrelacionada.
- `test_fsr_is_causal`: **el más importante.** El vector FSR en `t` no cambia si se modifican
  arbitrariamente los datos posteriores a `t`.
- `test_fsr_cache_invalidation`: cambiar cualquier hiperparámetro cambia el hash y recalcula.

Fases 3-5:

- `test_env_reward_equals_equity_delta`: en una trayectoria fijada, `Σ recompensas == ΔEquity` salvo costes.
- `test_env_no_leverage_breach`: la posición neta nunca supera `max_units`.
- `test_env_hold_is_free`: acción "mantener" ⇒ coste de transacción 0 (es lo que el paper busca).
- `test_ppo_learns_toy_env`: en un entorno determinista de juguete (precio que sube en escalones),
  PPO alcanza ≥ 90 % del retorno óptimo en < 200 iteraciones.
- `test_metrics_table2`: CRR/ARR/AVR/MD/SPR/CR/STR contra valores calculados a mano.
- Los tests existentes `tests/test_strategy.py`, `test_backtest.py` y `test_engine_settings.py` deben
  seguir en verde (los benchmarks no se tocan).

---

## Verificación end-to-end

```bash
cd ~/GitHub/trading-bot
uv sync && ./scripts/fix_forexconnect_macos.sh
uv run pytest                                        # toda la batería anterior

# 1. Descargar histórico y precalcular FSR (una vez, ~20-40 min)
uv run python scripts/download_history.py --tf H1 --years 3
uv run python scripts/precompute_fsr.py --tf H1      # progreso en consola; deja data/fsr_cache/*.npz

# 2. Entrenar (train hasta 2025-06-30, test desde 2025-07-01)
uv run python scripts/train_fsrppo.py --train-end 2025-06-30 --seeds 10

# 3. Backtest comparativo del modelo activo frente a los benchmarks
uv run python scripts/run_backtest.py --strategy fsrppo --compare

# 4. Backend + UI (un solo puerto: el backend sirve el export de web-ui/out)
cd web-ui && npm install && npm run build
MOCK=1 uv run uvicorn tradingbot.web.app:app --port 8000   # http://localhost:8000
```

Recorrido manual en la UI, que es lo que cierra el círculo:

1. `/settings` → guardar credenciales FXCM; el chip de la barra lateral pasa a **CONECTADO / DEMO**.
2. `/fsr` → "Precalcular caché", ver la barra de progreso avanzar por WebSocket y, al terminar, las
   IMFs con su Hurst y cuáles se descartan.
3. `/train` → lanzar un entrenamiento corto (NI=20) y ver la curva de recompensa actualizarse en vivo.
4. `/models` → el run aparece con sus 7 métricas de test; "Promover a modelo activo".
5. `/strategies` → backtest comparativo: tabla FSRPPO vs B&H/MACD/VMA/Turtle/Bollinger y curvas de
   equity superpuestas.
6. `/` → arrancar el bot en paper trading, comprobar que en el cierre de la siguiente barra H1
   aparece la acción del agente en el log y que la posición neta se actualiza; pausar y comprobar
   que deja de operar.
7. `/history` y `/activity` → los trades simulados y la curva de equity quedan registrados.

Adicionalmente, comparar la salida de `fsr_window()` sobre una serie sintética con una
implementación de referencia de EMD (`PyEMD`, solo como dependencia de test) para confirmar que la
descomposición se comporta como se espera antes de confiar en ella.
