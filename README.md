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

Parámetros en `src/tradingbot/config.py` y `.env`.

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

## Advertencia

Ninguna estrategia garantiza rentabilidad. Este bot puede perder dinero.
Flujo recomendado: backtest → semanas en demo → evaluar → recién entonces real,
empezando con el riesgo mínimo.
