#!/bin/bash
# ==============================================================================
# Script de instalación desatendida para Raspberry Pi (Raspberry Pi OS Lite / Desktop)
# Convierte la Raspberry Pi en un reproductor hardware dedicado (Appliance Mode)
# ==============================================================================

set -e

echo "=========================================================="
echo "    Instalador Autónomo de BSplayer para Raspberry Pi     "
echo "=========================================================="

if [ "$EUID" -ne 0 ]; then
  echo "Por favor ejecuta este script con permisos de superusuario: sudo bash install_rpi.sh"
  exit 1
fi

INSTALL_USER=${SUDO_USER:-pi}
TARGET_DIR="/home/$INSTALL_USER/BSplayer"

echo "[1/5] Actualizando paquetes e instalando dependencias del sistema de audio..."
apt-get update
apt-get install -y python3-pip python3-numpy python3-sounddevice libportaudio2 \
                   libasound2-plugins i2c-tools python3-rpi.gpio git alsa-utils

echo "[2/5] Instalando dependencias de Python..."
sudo -u "$INSTALL_USER" pip3 install fastapi uvicorn soundfile luma.oled --break-system-packages

echo "[3/5] Configurando permisos de usuario para Audio de baja latencia y GPIO..."
usermod -a -G audio,gpio,i2c,spi "$INSTALL_USER"

# Configurar prioridades de tiempo real para ALSA / PortAudio
if ! grep -q "@audio - rtprio 95" /etc/security/limits.conf; then
  cat << 'EOF' >> /etc/security/limits.conf
@audio - rtprio 95
@audio - memlock unlimited
EOF
fi

echo "[4/5] Habilitando I2C para pantalla OLED..."
raspi-config nonint do_i2c 0

echo "[5/5] Configurando modo Kiosco para pantalla LCD de 4 pulgadas y servicio..."
chmod +x "$TARGET_DIR/deploy/start_kiosk.sh"
apt-get install -y chromium-browser unclutter 2>/dev/null || true

SERVICE_PATH="/etc/systemd/system/bsplayer.service"
cp "$TARGET_DIR/deploy/bsplayer.service" "$SERVICE_PATH"
sed -i "s|/home/pi/BSplayer|$TARGET_DIR|g" "$SERVICE_PATH"
sed -i "s|User=pi|User=$INSTALL_USER|g" "$SERVICE_PATH"

systemctl daemon-reload
systemctl enable bsplayer.service
systemctl restart bsplayer.service

echo "=========================================================="
echo "  ¡BSplayer instalado y corriendo con éxito en Raspberry! "
echo "  El reproductor iniciará automáticamente al encender el equipo."
echo "  Pantalla LCD de 4\": http://localhost:8000/screen"
echo "  Consola móvil: http://$(hostname -I | awk '{print $1}'):8000"
echo "=========================================================="
