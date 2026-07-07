# BOLLINGER·BOT — EUR/USD M15 sobre FXCM

Bot de trading automático para EUR/USD con Bandas de Bollinger (20, 2) en velas
de 15 minutos, ejecutando contra la API ForexConnect de FXCM, con dashboard web
en tiempo real.

## Estrategia

Reversión a la media, evaluada solo sobre velas cerradas (sin repintado):

- **Entrada larga**: la vela anterior cierra bajo la banda inferior y la actual
  cierra de vuelta dentro. Corto: simétrico contra la banda superior.
- **TP**: banda media (SMA20) al momento de la señal. **SL**: 1.5 × ATR(14),
  adjunto a la orden en el servidor de FXCM (protege aunque el bot se caiga).
- **Riesgo**: 0.5% del equity por operación; máx. 1 posición; máx. 4 trades/día;
  spread máx. 1.5 pips; sin entradas viernes tarde ni en rollover;
  **límite de pérdida diaria 3%** → pausa hasta el día siguiente.

Parámetros en `src/tradingbot/config.py` y `.env`, **editables en caliente desde
la pestaña "Ajustes del Bot"** (validados y acotados en el servidor; aplican
desde la próxima vela).

## Dashboard web

Interfaz estilo FX Command Center con gestión completa del bot:

- **Dashboard**: velas 15m con bandas (timeframes M5/M15/H1/H4), ticker en vivo,
  posiciones activas con P&L y cierre individual/CLOSE ALL, órdenes manuales
  (Force Buy/Sell con lote, TP y SL en pips), toggle auto-trading, logs.
- **Ajustes del Bot**: estrategia y riesgo editables en runtime.
- **Backtesting**: simula la estrategia (con los ajustes actuales) sobre
  histórico FXCM real, datos sintéticos o un CSV subido; métricas, veredicto,
  curva de equity y tabla de trades. Corre en segundo plano.
- **Historial** y **Monitor de Actividad**: trades cerrados, curva de equity, log.

## Requisitos

- macOS ARM64 (o Linux x64 con Python 3.7 — ver wheels de `forexconnect`)
- [uv](https://docs.astral.sh/uv/)
- Cuenta FXCM **demo** (gratis en fxcm.com) o real

## Instalación

```bash
uv sync                                # instala Python 3.10 + dependencias
./scripts/fix_forexconnect_macos.sh    # re-enlaza el binario FXCM (solo macOS)
cp .env.example .env                   # y completa FXCM_USER / FXCM_PASS
```

## Uso

```bash
uv run pytest                                  # tests de la estrategia
uv run python scripts/check_connection.py      # smoke test de conexión FXCM
uv run python scripts/run_backtest.py          # backtest con histórico FXCM (~2 años)
uv run python scripts/run_backtest.py --synthetic   # prueba del pipeline sin cuenta

# Dashboard + bot (http://localhost:8000)
uv run uvicorn tradingbot.web.app:app --port 8000

# Dashboard en modo simulado (sin credenciales, precios random-walk)
MOCK=1 uv run uvicorn tradingbot.web.app:app --port 8000
```

Sin credenciales en `.env` el bot arranca automáticamente en modo **SIMULADO**
(se indica en el dashboard). Con credenciales usa la conexión de `FXCM_CONNECTION`
(`Demo` por defecto; **solo** poner `Real` tras validar semanas en demo).

El bot opera mientras la Mac esté despierta: `caffeinate -s uv run uvicorn …`.

## Advertencias

- Ninguna estrategia garantiza rentabilidad. Este bot puede perder dinero.
  Flujo recomendado: backtest → semanas en demo → evaluar → recién entonces
  real, empezando con el riesgo mínimo.
- El servidor **no tiene autenticación**: mantenerlo en `localhost` (default de
  uvicorn). No exponerlo a internet ni a la red local sin poner un proxy con
  auth delante.
