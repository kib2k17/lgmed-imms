#!/bin/sh
# Compile the LGMED-IMMS stylesheet (and its dark theme). Pass --watch to
# rebuild on change; run once more without it before committing, so dark.css
# follows.
set -e
cd "$(dirname "$0")"
[ -x tools/tailwindcss.exe ] || { echo "tools/tailwindcss.exe not found - see README.md"; exit 1; }
if [ "$1" = "--watch" ]; then
  exec ./tools/tailwindcss.exe -i static/css/app.src.css -o static/css/app.css --watch
fi
./tools/tailwindcss.exe -i static/css/app.src.css -o static/css/app.css --minify
# The dark theme is derived from the compiled stylesheet; rebuild it too.
PY=venv/Scripts/python.exe; [ -x "$PY" ] || PY=venv/bin/python
"$PY" manage.py build_dark_css
