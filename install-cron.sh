#!/bin/bash
# Instala el vigia como agente de launchd (cada 2 minutos, sobrevive reinicios).
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.mika.showcase-duna-watch"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$HOME/Library/LaunchAgents"
sed "s|__DIR__|$DIR|g" "$DIR/$LABEL.plist" > "$DEST"
launchctl unload "$DEST" 2>/dev/null || true
launchctl load "$DEST"
echo "Instalado: $DEST"
echo "Corre cada 2 minutos. Para ver el estado:  launchctl list | grep $LABEL"
echo "Para desinstalar:                        launchctl unload $DEST && rm $DEST"
