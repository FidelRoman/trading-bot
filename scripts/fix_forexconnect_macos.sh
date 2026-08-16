#!/usr/bin/env bash
# El wheel forexconnect cp310 para macOS ARM64 fue enlazado contra el Python
# framework de python.org. Este script re-apunta esa referencia al libpython del
# intérprete del venv y re-firma el binario (obligatorio en ARM64 tras
# modificarlo). Ejecutar tras cada `uv sync` que reinstale forexconnect.
#
# CONDICIÓN IMPRESCINDIBLE: el intérprete debe cargar su libpython de forma
# DINÁMICA. Si el ejecutable lleva CPython enlazado estáticamente —el caso de las
# builds de uv, `cpython-3.10-macos-aarch64-none`— apuntar fxcorepy.so a un
# libpython3.10.dylib carga una SEGUNDA copia del runtime en el mismo proceso.
# fxcorepy inicializa contra esa copia, que no tiene estado de intérprete, y
# `PyCapsule_Import` revienta con SIGSEGV. Como es una señal y no una excepción,
# se lleva por delante el proceso entero (uvicorn incluido) sin traza útil.
# Por eso el script aborta si no encuentra una libpython ya cargada.
set -euo pipefail

VENV="${1:-.venv}"
PY="$VENV/bin/python"
SO="$VENV/lib/python3.10/site-packages/forexconnect/lib/fxcorepy.so"

[[ -x "$PY" ]] || { echo "No existe el intérprete $PY"; exit 1; }
[[ -f "$SO" ]] || { echo "No existe $SO — ¿falta un 'uv sync'?"; exit 1; }

# Ruta de la libpython REALMENTE cargada en el proceso, preguntándole a dyld.
# Es la única fuente fiable: `sysconfig` declara Py_ENABLE_SHARED=1 incluso en
# las builds de uv, cuyo ejecutable no enlaza el dylib por ningún sitio.
LIBPYTHON="$("$PY" - <<'PY'
import ctypes

libc = ctypes.CDLL(None)
libc._dyld_get_image_name.restype = ctypes.c_char_p
for i in range(libc._dyld_image_count()):
    name = libc._dyld_get_image_name(i).decode()
    if "libpython3.1" in name or name.endswith("Python.framework/Versions/3.10/Python"):
        print(name)
        break
PY
)"

if [[ -z "$LIBPYTHON" ]]; then
  cat >&2 <<EOF
El intérprete de $VENV lleva CPython enlazado estáticamente:

  $("$PY" -c 'import sys; print(sys.executable)')

Re-enlazar fxcorepy.so contra un libpython3.10.dylib cargaría un segundo runtime
y el proceso moriría con "Segmentation fault: 11" al conectar con FXCM.

Recrea el entorno con un Python 3.10 de libpython dinámica, por ejemplo:

  brew install python@3.10
  uv venv --python /opt/homebrew/opt/python@3.10/bin/python3.10
  uv sync
EOF
  exit 1
fi

# Referencia a Python que trae el .so ahora mismo: puede ser la de python.org
# recién instalada por el wheel, o la que dejó una ejecución anterior.
OLD_REF="$(otool -L "$SO" | awk 'NR > 1 { print $1 }' \
  | grep -E 'libpython3\.1|Python\.framework/Versions/3\.10/Python' | head -1 || true)"

if [[ -z "$OLD_REF" ]]; then
  echo "fxcorepy.so no referencia ninguna libpython; nada que re-enlazar" >&2
elif [[ "$OLD_REF" == "$LIBPYTHON" ]]; then
  echo "fxcorepy.so ya apunta a $LIBPYTHON"
else
  install_name_tool -change "$OLD_REF" "$LIBPYTHON" "$SO"
  # En ARM64 toda modificación invalida la firma y el binario deja de cargar.
  codesign -f -s - "$SO"
  echo "fxcorepy.so re-enlazado: $OLD_REF -> $LIBPYTHON"
fi

# Verificar de verdad. Un re-enlace "correcto" sobre el intérprete equivocado
# sigue produciendo un segfault, y sin esta comprobación el fallo no aparece
# hasta que el bot intenta conectar con dinero de por medio.
if "$PY" -c 'import forexconnect' 2>/dev/null; then
  echo "OK: 'import forexconnect' funciona"
else
  echo "FALLO: 'import forexconnect' termina con código $? — el entorno no sirve" >&2
  exit 1
fi
