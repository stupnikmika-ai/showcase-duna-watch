#!/bin/bash
# Wrapper para el cron/launchd: fija el directorio y usa el python del sistema.
cd "$(dirname "$0")" || exit 1
exec /usr/bin/python3 watch.py "$@"
