#!/bin/bash
# ==============================================================================
# Script de auto-arranque en Modo Kiosco para Pantalla LCD de 4" en Raspberry Pi
# Oculta cursor, desactiva protector de pantalla y abre la interfaz mágica a 800x480
# ==============================================================================

# Desactivar reposo de pantalla
xset -dpms 2>/dev/null || true
xset s off 2>/dev/null || true
xset s noblank 2>/dev/null || true

# Ocultar cursor del mouse tras 1 segundo de inactividad
unclutter -idle 1 &

# Esperar a que el backend de BSplayer esté activo
echo "[Kiosk] Esperando que BSplayer inicie..."
until curl -s http://localhost:8000/api/status > /dev/null; do
  sleep 0.5
done

echo "[Kiosk] Iniciando Interfaz Mágica en pantalla LCD..."
chromium-browser \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --disable-pinch \
  --overscroll-history-navigation=0 \
  --check-for-update-interval=31536000 \
  http://localhost:8000/screen
