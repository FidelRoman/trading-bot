# Operacion a costo cero

La produccion usa tres servicios y no necesita un servidor persistente:

- Vercel Hobby sirve `web-ui/` y la API autenticada de lectura/control.
- GitHub Actions ejecuta una evaluacion cada hora de lunes a viernes.
- Firestore conserva estado, operaciones, equity, logs y el snapshot del panel.

El proyecto de Google Cloud debe permanecer **sin cuenta de facturacion**. De
ese modo Firestore deja de aceptar trafico al agotar la cuota gratuita en lugar
de generar un cobro. El repositorio debe seguir publico para que los runners
estandar de GitHub Actions no consuman minutos facturables.

## 1. Firestore

Crea una base `(default)` en modo nativo y una cuenta de servicio con unicamente
`roles/datastore.user`. Guarda su clave fuera del repositorio. Variables usadas
por ambos runtimes:

```dotenv
FIRESTORE_PROJECT_ID=<project-id>
FIRESTORE_COLLECTION_PREFIX=tradingbot
GOOGLE_SERVICE_ACCOUNT_JSON=<json-completo-en-una-linea>
```

Verifica periodicamente que la facturacion continua deshabilitada:

```bash
gcloud beta billing projects describe "$FIRESTORE_PROJECT_ID"
```

La salida esperada contiene `billingEnabled: false`.

## 2. GitHub Actions

Configura las credenciales de Trading Station y la clave de Firestore:

```bash
gh secret set FXCM_USER
gh secret set FXCM_PASS
gh secret set GOOGLE_SERVICE_ACCOUNT_JSON < /ruta/privada/service-account.json
```

`.github/workflows/scheduled-tick.yml` usa `python:3.7-slim`, porque el ultimo
wheel de ForexConnect para Linux requiere CPython 3.7 x86_64. Cada ejecucion es
idempotente: procesa como maximo una vela cerrada, persiste el paper broker y
publica el snapshot consumido por Vercel. La conexion FXCM de produccion tiene
`read_only=True`: sus tres rutas de ordenes fallan antes de crear una solicitud.
La cuenta real aporta precios e historico, nunca ejecucion.

Prueba el job sin esperar al cron:

```bash
gh workflow run scheduled-tick.yml --ref main
gh run watch
```

El cron corre al minuto 7 de cada hora, de lunes a viernes. GitHub puede
retrasarlo; la frontera persistida impide procesar dos veces la misma vela.

## 3. Vercel

El proyecto usa `web-ui/` como Root Directory y Node 24. Variables de produccion:

```dotenv
BOT_API_TOKEN=<token-aleatorio-largo>
FIRESTORE_PROJECT_ID=<project-id>
FIRESTORE_COLLECTION_PREFIX=tradingbot
GOOGLE_SERVICE_ACCOUNT_JSON=<json-completo-en-una-linea>
```

No configures `BACKEND_URL`: sin esa variable, `/api/*` se resuelve en las
funciones de Vercel que leen Firestore directamente. El token se introduce en
la interfaz y queda en `sessionStorage`; nunca debe tener prefijo `NEXT_PUBLIC_`.

La interfaz consulta `/api/snapshot` cada 60 segundos. Los comandos de pausa y
cierre escriben una orden en Firestore; el siguiente tick programado la aplica.
Entrenar, precalcular o descargar historicos se hace mediante los workflows
manuales, no dentro de una funcion de Vercel.

## 4. Verificacion

1. Confirma `billingEnabled: false` en el proyecto de Firestore.
2. Confirma que el repositorio GitHub siga en visibilidad `PUBLIC`.
3. Comprueba que la URL Vercel devuelve `401` sin token y `200` con token.
4. Ejecuta manualmente `scheduled-tick.yml` y revisa que termine en verde.
5. Abre el panel y confirma que `updated_at` cambia tras el workflow.

Este alcance es paper trading. `FXCM_CONNECTION` esta fijado a `Real`, pero la
cuenta se abre mediante el adaptador de solo lectura y todas las posiciones se
mantienen exclusivamente en `PaperBroker`.
