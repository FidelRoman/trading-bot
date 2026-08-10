#!/bin/sh
set -eu

site_packages="$(python -c 'import site; print(site.getsitepackages()[0])')"
lib_dir="$site_packages/forexconnect/lib"

test -f "$lib_dir/libboost_python.so.1.64.0"
test -f "$lib_dir/libboost_system.so.1.64.0"

if [ ! -e "$lib_dir/libboost_python35.so.1.75.0" ]; then
  ln -s libboost_python.so.1.64.0 "$lib_dir/libboost_python35.so.1.75.0"
fi
if [ ! -e "$lib_dir/libboost_system.so.1.75.0" ]; then
  ln -s libboost_system.so.1.64.0 "$lib_dir/libboost_system.so.1.75.0"
fi

python -c "import forexconnect"
