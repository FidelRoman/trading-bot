# PRODUCT.md — FSRPPO·BOT

Verdad de producto para el trabajo de diseño de `web-ui/`. No contiene decisiones
visuales: esas viven en DESIGN.md.

## Qué es

Un bot de trading multi-instrumento sobre FXCM que implementa la estrategia FSRPPO
(representación de la señal financiera + PPO) del paper de Wang & Wang (2024), junto a
tres estrategias de referencia (Bollinger, RSI, Wyckoff) y Buy&Hold. `web-ui/` es su
única interfaz: un panel Next.js exportado estáticamente que sirve el propio backend
FastAPI en el puerto 8000, de modo que interfaz, `/api/*` y `/ws` comparten origen.

**Mecanismo único:** el agente propone y el overlay de riesgo veta. FSR limpia la
señal de precio descartando los modos intrínsecos sin memoria larga; PPO decide una
acción continua en el cierre de cada barra; encima, un filtro de sesión, spread máximo,
límite de operaciones diarias y límite de pérdida diaria pueden anular esa decisión.
La interfaz existe para hacer visible esa cadena y poder intervenir en ella.

## Quién lo usa y en qué escena

Un operador único —el autor— en su propia Mac, y desde el móvil a través de un túnel
Cloudflare. No hay equipo, ni roles, ni cuentas: el backend no autentica `/api/*` de
forma deliberada, porque el puerto solo es alcanzable desde localhost y la tailnet.

La escena real es de dos tipos, y la interfaz sirve a ambos:

- **Vigilancia**: la pestaña abierta durante horas mientras el bot opera. Mirada
  periférica, consultas de un segundo: ¿sigue conectado? ¿cuánto llevo hoy? ¿hay algo
  abierto? ¿estoy en real o en demo?
- **Trabajo**: sesiones de investigación en las que se descarga histórico, se entrena
  un modelo, se comparan métricas y se decide si un run merece activarse.

## Qué está en juego

Dinero real. Con `FXCM_CONNECTION=Real` el bot manda órdenes reales a una cuenta real,
y la interfaz tiene botones que abren y cierran posiciones a mercado. La consecuencia
de diseño es una sola, y manda sobre cualquier consideración estética:

**El modo de cuenta (Real / Demo / Simulado) y el estado del motor deben ser legibles
sin buscarlos, en todos los anchos, en todas las rutas.** Hoy no se cumple en móvil.

Las acciones destructivas o irreversibles ya pasan por `ConfirmDialog` con copy
específico —enviar orden, cerrar posición, cerrar todas, cambiar instrumento, activar
un instrumento en FXCM, iniciar en real—. Esa protección se conserva íntegra.

## Tareas que la interfaz debe soportar

| Superficie | Tarea |
|---|---|
| Operación | Ver el mercado, saber qué opera el bot, arrancarlo/pararlo, enviar órdenes manuales, cerrar posiciones, cambiar de instrumento |
| Historial | Revisar operaciones cerradas y estadísticas acumuladas |
| Actividad | Seguir la curva de capital y el registro completo del bot |
| Señal FSR | Inspeccionar la descomposición: IMFs, su Hurst, cuáles se descartan; precalcular la caché |
| Entrenamiento | Descargar histórico, lanzar un run, seguirlo en vivo, leer si bate a comprar-y-mantener fuera de muestra |
| Modelos | Comparar runs con las siete métricas del paper, activar o desactivar el modelo por instrumento |
| Estrategias | Configurar parámetros por estrategia y simular (backtest) sobre histórico o datos sintéticos |
| Ajustes | Fijar límites de riesgo y el reloj de decisión; ver la cuenta |

## Restricciones

- **Idioma**: español. Toda la interfaz, incluidos mensajes de error y ayuda.
- **Contratos**: `/api/*` y `/ws` no se tocan. La lógica de trading, riesgo y
  entrenamiento vive en el backend Python y queda fuera del alcance del diseño.
- **Build**: export estático de Next (`output: "export"`), sin servidor Node en
  producción. Nada que dependa de renderizado en servidor o de rutas de API de Next.
- **Local primero**: la app corre sin internet. Ninguna dependencia de red externa en
  tiempo de ejecución (fuentes, CDNs, telemetría).
- **Datos en vivo**: `lib/live.tsx` mantiene un WebSocket con reconexión; la interfaz
  debe comportarse bien mientras `status` es nulo y cuando la conexión se cae.
- **Densidad**: es una consola operativa, no una landing. Cabe mucha información en
  pantalla y así debe seguir siendo.
- **Tema**: oscuro y claro, ambos completos, con detección del sistema.

## Contenido que no se inventa

Cifras de cuenta, precios, métricas, resultados de entrenamiento y estado del mercado
vienen del backend. Las explicaciones factuales de la estrategia (desviaciones respecto
al paper, por qué el reloj lo fija el modelo, por qué no se puede cambiar de
instrumento con posiciones abiertas) son verdad de producto ya escrita en la interfaz y
en el README: se conservan, se reubican si mejora la lectura, no se reescriben para que
suenen mejor.

## Preferencia de ejecución

`buildPath`: code-led. Esta máquina no tiene generación de imágenes disponible, así que
la ambición viaja en el contrato de dirección escrito y se audita en la revisión final.
