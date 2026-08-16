# FSRPPO·BOT — operación multi-instrumento sobre FXCM

Bot de trading multi-instrumento que implementa la estrategia **FSRPPO** del paper
*"An adaptive financial trading strategy based on proximal policy optimization and
financial signal representation"* (Lin Wang, Xuerui Wang — *Engineering Applications
of Artificial Intelligence* 138 (2024) 109365), con dashboard web en tiempo real.

Alcance actual: **backtest y trading en cuentas Demo/Real**. Envía órdenes reales.

Plan de implementación completo y decisiones de diseño: [`PLAN.md`](PLAN.md).

## Estrategia FSRPPO

Dos piezas encadenadas:

1. **FSR — representación de la señal financiera.** La ventana de los últimos `M`
   cierres se descompone con **CEESMDAN** (ESMD con ruido blanco adaptativo y
   ensamblado) en funciones de modo intrínseco. A cada IMF se le estima el
   exponente de **Hurst** por análisis R/S modificado (**MRS**): las de `H ≤ 0.5`
   son ruido de alta frecuencia y se descartan; las de `H > 0.5` tienen memoria
   larga y se suman. El resultado es la señal limpia que ve el agente.
2. **PPO.** Un agente de refuerzo decide en el cierre de cada barra una acción
   continua `(a₁, a₂)`: `a₁` la dirección (aumentar largo / mantener / aumentar
   corto, por tercios) y `a₂` el tamaño del ajuste. La recompensa combina el P&L
   de la posición con el coste de operar, de modo que mantener posición sale
   gratis y el agente no sobreopera.

El cálculo de FSR es **causal** (solo mira la ventana que termina en la barra
actual) y se **precalcula y cachea** por dataset e hiperparámetros: el
entrenamiento lee de memoria.

Sobre el agente actúa el mismo **overlay de riesgo** del bot anterior: filtro de
sesión, spread máximo, límite de operaciones diarias y límite de pérdida diaria
(→ pausa hasta el día siguiente). El agente propone; el overlay veta.

### Desviaciones respecto al paper

El paper opera **acciones chinas en barras diarias, solo largo y con caja**;
aquí se opera **EUR/USD en H1, con posición neta y apalancamiento**. Cada
diferencia está marcada en el código junto a su motivo. Las que cambian
resultados:

| Punto | Paper | Aquí | Por qué |
|---|---|---|---|
| Posición | Caja + acciones, solo largo | Posición neta con signo | En FX se puede vender en corto |
| Coste | `α_tax · p · μ` (impuesto 0,015 %) | `spread × |Δunidades|` | El coste real en divisas es el spread |
| Estado | 50 precios | 50 valores FSR + 3 rasgos de cuenta | Sin conocer su posición, el agente no observa un MDP completo |
| Escala | Precios en bruto | Rendimientos relativos al último cierre | Sin normalizar, la política no generaliza de train a test |
| Umbral δ del tamizado | Absoluto (0,001) | Relativo al rango de la ventana | Un δ absoluto calibrado para decenas de yuanes detiene el tamizado en la primera pasada sobre precios de 1,08 |
| Fin del tamizado | Última de `D=100` pasadas | La mejor de las `D` pasadas | Sobre precios reales `max\|CSI\|` toca mínimo hacia la 9ª pasada y **después crece**: quedarse con la última devuelve una IMF degradada |
| Actualización PPO | Una por iteración | Varias épocas sobre el lote | Con una sola, el cociente de probabilidades vale 1 y el recorte de PPO nunca actúa |
| Distribución | Implícita | Beta(α, β) por dimensión | Soporte natural en [0,1]²; una normal recortada sesga las acciones extremas |
| Escala de la entrada | Precios de acciones en bruto (escala unidad) | Features FSR × 200 | Los rendimientos relativos tienen σ≈5e-3 frente a rasgos de cuenta de orden 1. Sin reescalar se midió una política cuya acción variaba **0,0004** entre barras completamente distintas: la red ignoraba la observación |
| Learning rate | 1e-5 | Configurable (`--learning-rate`) | Con 1e-5 el agente **nunca llega a operar** en EUR/USD H1 (0 operaciones en 200 iteraciones). Ver la sección de resultados |
| Anualización | 250 días | Barras por año del timeframe | 6.240 barras H1/año; usar 250 daría cifras sin sentido |
| `R_f` en Sortino | Anual, restado a rendimientos por barra | Prorrateado por barra | Tal cual está escrito, la desviación bajista sería casi constante |

La reproducción del paper que sí se verifica en los tests: CEESMDAN corrige el
*mode mixing* de ESMD (fuga de energía fuera de una ráfaga intermitente: 90,9×
con ESMD frente a 0,23× con CEESMDAN) y el filtro de Hurst separa las escalas
como describe §2.1.4 — sobre ventanas reales de EUR/USD H1, la IMF más rápida
tiene H≈0,32 y se descarta siempre, mientras que las lentas rondan H≈0,60-0,67 y
se conservan, tirando en torno al 27 % de la varianza como ruido.

### Estrategias de referencia

Se conservan Bollinger, RSI y Wyckoff, y se añade Buy&Hold, para comparar FSRPPO
contra ellas con las siete métricas del paper (CRR, ARR, AVR, MD, Sharpe, Calmar,
Sortino).

## Dashboard web (Next.js)

Todo corre en local. El frontend **Next.js** (`web-ui/`) se compila a un export
estático que sirve el propio backend FastAPI, de modo que interfaz, `/api/*` y
`/ws` comparten un único origen en el puerto 8000:

- **Dashboard**: velas con la señal FSR reconstruida superpuesta, ticker en vivo,
  posición neta y P&L, toggle de auto-trading, logs.
- **FSR**: visor de la descomposición (IMFs con su Hurst, cuáles se descartan) y
  precálculo de la caché con progreso en vivo.
- **Entrenamiento**: lanzar runs de PPO, curvas de recompensa y pérdida en vivo,
  checkpoints, promoción del modelo a activo.
- **Modelos**: registro de modelos entrenados con sus métricas de test.
- **Backtesting**: FSRPPO frente a los benchmarks sobre histórico FXCM real,
  datos sintéticos o un CSV, eligiendo rango de fechas y timeframe.
- **Historial** y **Monitor de Actividad**: trades cerrados, curva de equity, log.

## Resultados de la validación (2026-08-09)

**FSRPPO no supera el criterio de aceptación en EUR/USD H1.** El repositorio
conserva un modelo histórico activo para poder ejecutar pruebas operativas. La
aplicación permite usarlo —también en Real— bajo responsabilidad explícita del
operador y lo rotula como no validado; esta condición no bloquea órdenes.

Datos: 12.659 velas H1 reales de FXCM (2024-07-08 → 2026-07-08). Train hasta
2026-01-08 (9.458 barras), test 2026-01-08 → 2026-07-08 (3.152 barras). Spread
1,2 pips, exposición máxima 20.000 unidades.

### El learning rate del paper no llega a operar

| lr | CRR train | CRR test | Sharpe test | operaciones |
|---|---|---|---|---|
| 1e-5 (el del paper) | 0,00 % | 0,00 % | — | **0** |
| 3e-4 | +6,63 % | −1,49 % | −0,442 | 145 |
| 1e-3 | **+29,42 %** | −4,92 % | −0,968 | 603 |

Cuanto más aprende el tramo de entrenamiento, peor le va fuera de muestra. Eso
es sobreajuste, no falta de aprendizaje: la maquinaria funciona (PPO alcanza el
100 % del óptimo en un entorno de juguete y la política reacciona a la
observación), pero lo aprendido de 2024-2026 no transfiere a 2026.

### Diez semillas con lr = 3e-4, la configuración que sí opera

| | CRR | ARR | MD | Sharpe | Calmar | Sortino | ops |
|---|---|---|---|---|---|---|---|
| Buy & Hold | −5,19 % | −10,01 % | 13,24 % | −0,863 | −0,756 | −1,244 | 1 |
| **FSRPPO (mediana)** | **−5,50 %** | — | — | **−1,059** | — | — | 288 |
| Mejor semilla (0) | −1,49 % | −2,94 % | 9,44 % | −0,442 | −0,311 | −0,638 | 145 |
| Peor semilla (6) | −13,39 % | −24,78 % | 14,40 % | −2,278 | −1,721 | −3,053 | 1.117 |

**Semillas que cumplen Sharpe > 0 y CRR > Buy & Hold: 0 de 10.** Las diez pierden
dinero, y en mediana lo hacen algo peor que no hacer nada. El tramo de test fue
bajista (−5,19 % en el par), así que ni siquiera se trata de un agente al que le
tocó un mercado imposible: tenía la opción de ponerse corto y no supo aprovecharla
de forma consistente.

### Qué significa

No invalida el paper: sus resultados son sobre acciones chinas en barras diarias,
donde el coste por operación es 0,015 % y los movimientos diarios son grandes. En
EUR/USD H1 el spread de 1,2 pips pesa muchísimo más en relación al recorrido de
cada barra, y el número de operaciones que hace el agente (145 a 1.117 en seis
meses) multiplica ese coste.

Coincide además con lo que ya sabías de este par: la estrategia Bollinger anterior
tampoco encontró ventaja en EUR/USD. Antes de volver a intentarlo, lo que tiene
sentido probar es cambiar el terreno, no afinar el modelo: barras diarias en vez
de H1 (menos peso del spread, más parecido al paper), o directamente acciones, que
es donde el método está validado.

## Requisitos

- macOS ARM64 con Python 3.10 para el wheel local de `forexconnect`
- Node.js 24.11.1 recomendado (`nvm use` lee `.nvmrc`; Next exige ≥20.9)
- [uv](https://docs.astral.sh/uv/)
- Cuenta FXCM **demo** (gratis en fxcm.com) para datos en vivo — opcional: sin
  credenciales el bot arranca en modo **SIMULADO**

## Instalación

```bash
uv sync                                     # instala Python 3.10 + dependencias
./scripts/fix_forexconnect_macos.sh         # re-enlaza el binario FXCM (solo macOS)
cp .env.example .env                        # y completa FXCM_USER / FXCM_PASS
echo "BOT_API_TOKEN=$(openssl rand -hex 32)" >> .env
cd web-ui && npm install && npm run build   # compila la interfaz a web-ui/out/
```

Python está fijado a **3.10** por el único wheel de `forexconnect` para macOS
ARM64. Hay que re-ejecutar `fix_forexconnect_macos.sh` después de cada `uv sync`.

## Uso

```bash
uv run pytest                                  # batería completa

# Modo Simulado (pruebas locales, sin credenciales o en fines de semana):
MOCK=1 uv run uvicorn tradingbot.web.app:app --port 8000 \
  --proxy-headers --forwarded-allow-ips="*"

# Modo Conectado FXCM (Demo/Real según .env):
caffeinate -s uv run uvicorn tradingbot.web.app:app --port 8000 \
  --proxy-headers --forwarded-allow-ips="*"
```

 ### Cómo dejarlo corriendo:

  Puedes dejar el proceso activo directamente con:

    caffeinate -s uv run uvicorn tradingbot.web.app:app --port 8000 --proxy-headers --forwarded-allow-ips="*"
    
Abre <http://localhost:8000> e introduce el `BOT_API_TOKEN`. El bot opera
mientras el proceso esté vivo y la Mac despierta (de ahí `caffeinate -s`).

Para acceder desde fuera de casa, `./scripts/tunnel.sh` publica ese puerto en una
URL HTTPS de Cloudflare sin abrir puertos del router; los datos no salen del
disco local. Detalles, túnel con URL estable y desarrollo con recarga en caliente
(`npm run dev`): [`docs/local.md`](docs/local.md).

## Advertencias

- Ninguna estrategia garantiza rentabilidad, y el rendimiento que el paper reporta
  sobre acciones chinas en barras diarias **no se traslada automáticamente** a
  EUR/USD intradía, donde el spread pesa mucho más. El criterio para dar por buena
  la estrategia está escrito en `PLAN.md`: Sharpe > 0 y CRR > Buy&Hold en el tramo
  de test, en al menos 7 de 10 semillas. Si no se cumple, el bot se queda en
  backtest.
- El servidor protege `/api/*` y `/ws` con `BOT_API_TOKEN` y falla cerrado si no
  está configurado. Al exponer el puerto por un túnel, ese token es lo único que
  separa tus datos de Internet: genéralo largo y no lo compartas.
