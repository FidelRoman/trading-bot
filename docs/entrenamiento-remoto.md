# Entrenar en otra máquina

El entrenamiento (`precompute_fsr` + `train_fsrppo`) satura la CPU durante horas.
No necesita FXCM ni la interfaz: solo un CSV de histórico. Así que se puede hacer
en cualquier equipo y traer de vuelta un directorio pequeño.

```
   esta Mac                     máquina de entrenamiento
  ┌──────────┐   1. CSV        ┌──────────────────────┐
  │ data/    │ ──────────────► │ uv sync              │
  │ history/ │                 │ precompute_fsr       │
  │          │ ◄────────────── │ train_fsrppo         │
  └──────────┘   2. modelo     └──────────────────────┘
                 (~650 KB)
```

Lo único que viaja de vuelta son tres ficheros por run: `model.pt`, `meta.json` y
`history.json`.

---

## 1. En esta Mac: generar el histórico

El entrenamiento parte de un CSV, no de FXCM. Descárgalo aquí (necesita
credenciales) y esto es lo único que hay que copiar:

```bash
uv run python scripts/download_history.py \
  --symbols EUR/USD --timeframes h1 --years 2
ls -la data/history/
```

Produce `data/history/eurusd_h1_<desde>_<hasta>.csv`, del orden de unos MB.

> Para otro instrumento, cambia `--symbols` (por ejemplo `XAU/USD`, `US30`,
> `AAPL`). El nombre del fichero sale de `symbol_slug`, así que `XAU/USD` genera
> `xauusd_h1_….csv`.

## 2. Preparar la máquina de entrenamiento

No hace falta `forexconnect` (es solo para hablar con FXCM), pero `uv sync`
lo instala igualmente y en Linux o Windows el wheel puede fallar. Dos caminos:

**Opción A — el repo completo (más simple):**

```bash
git clone <tu-repo> trading-bot && cd trading-bot
uv sync
# En macOS ARM64, y solo ahí:
./scripts/fix_forexconnect_macos.sh
```

Si `uv sync` falla por `forexconnect` en Linux, instala solo lo que el
entrenamiento necesita:

```bash
uv pip install torch numpy "pandas<3" scipy python-dotenv
```

**Opción B — sin credenciales ni .env.** El entrenamiento no lee `.env`, así que
no copies secretos a la otra máquina. Basta con el repo y el CSV.

Copia el histórico:

```bash
scp data/history/eurusd_h1_*.csv usuario@maquina:~/trading-bot/data/history/
```

## 3. Entrenar

```bash
cd trading-bot

# 3a. Caché de features FSR. Es lo más lento; sin ella cada época recalcula
#     la señal. Se cachea por ventana, así que solo se paga una vez por CSV.
uv run python scripts/precompute_fsr.py -j $(nproc)      # macOS: $(sysctl -n hw.ncpu)

# 3b. Prueba corta primero: confirma que el pipeline entero funciona (~minutos)
uv run python scripts/train_fsrppo.py --seeds 1 --iterations 20

# 3c. Entrenamiento de verdad: 10 semillas, como promedia el paper
uv run python scripts/train_fsrppo.py --train-end 2026-01-01 --seeds 10 -j $(nproc)
```

Argumentos que importan:

| Argumento | Para qué |
|---|---|
| `--csv` | otro histórico; por defecto `data/history/eurusd_h1_20240708_20260708.csv` |
| `--instrument` | instrumento del modelo. **Tiene que coincidir con el que operará el bot**: el motor se niega a operar un modelo entrenado en otro activo |
| `--timeframe` | marco temporal; debe coincidir con el CSV |
| `--train-end` | corte train/test (por defecto, el 75 % del histórico) |
| `--seeds` | repeticiones. Un solo run puede salir bien por azar |
| `--iterations` | iteraciones de PPO por run |
| `--learning-rate` | el 1e-5 del paper no llega a operar en EUR/USD H1; ver README |
| `-j` | procesos en paralelo |
| `--activate-best` | promueve el mejor run por Sharpe de test. **No lo uses en la máquina remota**: el puntero de modelo activo es local de la máquina que opera |

El criterio de aceptación que imprime al final (de `PLAN.md`): Sharpe > 0 y CRR
mejor que comprar-y-mantener en el tramo de test, en al menos 7 de cada 10
semillas. Si no lo cumple, **ese modelo no vale para operar** aunque el
entrenamiento haya terminado sin errores.

## 4. Traer el modelo de vuelta

Cada run deja un directorio en `data/models/<run_id>/` con tres ficheros
(`model.pt` ≈ 650 KB, `meta.json`, `history.json`):

```bash
# En la máquina de entrenamiento: ver qué runs salieron
ls data/models/

# Desde esta Mac: traer el run elegido
scp -r usuario@maquina:~/trading-bot/data/models/fsrppo-XXXXXXXX-XXXXXX \
      data/models/
```

**No copies `active.json`.** Es el mapa de modelos activos —una entrada por
instrumento, `{"EUR/USD": "fsrppo-…", "XAU/USD": "fsrppo-…"}`— y es local. Copiarlo
no solo apuntaría a runs que esta máquina quizá no tiene: **se llevaría por delante
los activos del resto de instrumentos**, no solo el que acabas de entrenar.

La caché `data/fsr_cache/*.npz` tampoco hace falta traerla para operar: solo
acelera reentrenamientos. Son cientos de MB.

## 5. Activarlo aquí

```bash
uv run uvicorn tradingbot.web.app:app --port 8000
```

En el panel, **Modelos** → localiza el `run_id` → **Activar**. O por API:

```bash
TOKEN=$(grep '^BOT_API_TOKEN=' .env | cut -d= -f2)
curl -s -H "Authorization: Bearer $TOKEN" localhost:8000/api/models \
  | python3 -m json.tool | head -40

curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  localhost:8000/api/models/fsrppo-XXXXXXXX-XXXXXX/activate
```

Comprueba que quedó activo y que el instrumento cuadra:

```bash
curl -s -H "Authorization: Bearer $TOKEN" localhost:8000/api/status \
  | python3 -c "import json,sys; d=json.load(sys.stdin); \
print('modelo', d.get('active_model'), '| instrumento', d.get('instrument'))"
```

Si el modelo se entrenó en un instrumento distinto al que opera el bróker, el
motor **no operará** y lo dirá en el log: la política dimensiona para el activo de
entrenamiento y ejecutar en otro sería mezclar dos escalas. Cambia el instrumento
en el panel o activa otro modelo.

## 6. Comprobación final

1. `uv run pytest -q` en verde en esta máquina.
2. `/api/status` devuelve `active_model` no nulo y `instrument` coincidente.
3. Estrategia activa `fsrppo` en el panel.
4. **Empieza en Demo.** Deja correr unas sesiones y compara las operaciones del
   log con lo que esperabas antes de tocar la cuenta Real.

---

## Nota sobre qué esperar

El backtest de la estrategia Bollinger sobre 24 meses de M15 reales dio PF 0.69, y
el grid search con validación train/test no encontró ninguna combinación con
PF ≥ 1 en ambos tramos. FSRPPO es el intento de superar eso, pero **hasta que un
entrenamiento pase el criterio de aceptación de arriba, no hay evidencia de
ventaja**. Entrenar sin errores no es lo mismo que entrenar algo rentable.
