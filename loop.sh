#!/bin/bash
# Demonio: un proceso vivo que chequea cada INTERVALO segundos.
#
# Por que no StartInterval: launchd agrupa los timers para ahorrar energia y
# los difiere. Medido con StartInterval=120 salieron corridas a 2m02s y 3m44s.
# Un proceso propio durmiendo con sleep respeta el intervalo de verdad.
cd "$(dirname "$0")" || exit 1
INTERVALO="${DUNA_INTERVALO:-120}"
while true; do
  /usr/bin/python3 watch.py || true
  sleep "$INTERVALO"
done
