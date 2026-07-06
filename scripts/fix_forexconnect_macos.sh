#!/usr/bin/env bash
# El wheel forexconnect cp310 para macOS ARM64 fue enlazado contra el Python
# framework de python.org, que no existe en instalaciones gestionadas por uv.
# Este script re-apunta esa referencia al libpython del Python de uv y re-firma
# el binario (obligatorio en ARM64 tras modificarlo).
# Ejecutar tras cada `uv sync` que reinstale forexconnect.
set -euo pipefail

VENV="${1:-.venv}"
SO="$VENV/lib/python3.10/site-packages/forexconnect/lib/fxcorepy.so"
OLD_REF="/Library/Frameworks/Python.framework/Versions/3.10/Python"

PYBIN="$(readlink -f "$VENV/bin/python")"
LIBPYTHON="$(dirname "$(dirname "$PYBIN")")/lib/libpython3.10.dylib"

[[ -f "$SO" ]] || { echo "No existe $SO"; exit 1; }
[[ -f "$LIBPYTHON" ]] || { echo "No existe $LIBPYTHON"; exit 1; }

if otool -L "$SO" | grep -q "$OLD_REF"; then
  install_name_tool -change "$OLD_REF" "$LIBPYTHON" "$SO"
  codesign -f -s - "$SO"
  echo "fxcorepy.so re-enlazado a $LIBPYTHON"
else
  echo "fxcorepy.so ya estaba corregido"
fi
