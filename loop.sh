#!/bin/bash
# Demonio: un proceso vivo que chequea cada INTERVALO segundos.
#
# Por que no StartInterval: launchd agrupa los timers para ahorrar energia y
# los difiere. Medido con StartInterval=120 salieron corridas a 2m02s y 3m44s.
# Un proceso propio durmiendo con sleep respeta el intervalo de verdad.
cd "$(dirname "$0")" || exit 1
# El intervalo sale del .env (launchd no lo carga solo). Cambiarlo ahi y
# recargar con: launchctl kickstart -k gui/$(id -u)/com.mika.showcase-duna-watch
if [ -f .env ]; then
  val=$(grep -E '^DUNA_INTERVALO=' .env | tail -1 | cut -d= -f2 | tr -d ' "'"'"'')
  [ -n "$val" ] && DUNA_INTERVALO="$val"
fi
INTERVALO="${DUNA_INTERVALO:-300}"
while true; do
  /usr/bin/python3 watch.py || true
  sleep "$INTERVALO"
done
