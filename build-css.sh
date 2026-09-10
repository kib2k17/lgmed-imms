#!/bin/sh
# Compile the LGMED-iMMS stylesheet. Pass --watch to rebuild on change.
set -e
cd "$(dirname "$0")"
[ -x tools/tailwindcss.exe ] || { echo "tools/tailwindcss.exe not found - see README.md"; exit 1; }
if [ "$1" = "--watch" ]; then
  exec ./tools/tailwindcss.exe -i static/css/app.src.css -o static/css/app.css --watch
fi
exec ./tools/tailwindcss.exe -i static/css/app.src.css -o static/css/app.css --minify
