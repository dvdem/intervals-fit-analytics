#!/usr/bin/env bash
# ==============================================================================
# Setup Automatizado de Intervals Fit Analytics en Oracle Cloud VPS (Ubuntu)
# ==============================================================================
set -euo pipefail

echo "===================================================================="
echo "🚴 APROVISIONAMIENTO DE INTERVALS FIT ANALYTICS EN ORACLE CLOUD"
echo "===================================================================="

# Verificar privilegios de sudo/root
if [ "$EUID" -ne 0 ]; then
    echo "❌ Este script debe ejecutarse con privilegios de superusuario (sudo)."
    exit 1
fi

APP_USER="${SUDO_USER:-ubuntu}"
APP_DIR="/var/www/intervals_fit_analytics"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "ℹ️ Usuario de la aplicación: ${APP_USER}"
echo "ℹ️ Directorio destino: ${APP_DIR}"

# ------------------------------------------------------------------------------
# 1. Configuración de Memoria Swap (Vital para instancias AMD Micro de 1GB)
# ------------------------------------------------------------------------------
TOTAL_RAM_MB=$(free -m | awk '/^Mem:/{print $2}')
CURRENT_SWAP_MB=$(free -m | awk '/^Swap:/{print $2}')

echo "📊 Memoria RAM detectada: ${TOTAL_RAM_MB} MB | Swap actual: ${CURRENT_SWAP_MB} MB"
if [ "${TOTAL_RAM_MB}" -lt 2500 ] && [ "${CURRENT_SWAP_MB}" -lt 1000 ]; then
    echo "⚡ RAM menor a 2.5GB detectada. Configurando 2GB de Swap para estabilidad..."
    if [ ! -f /swapfile ]; then
        fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
        chmod 600 /swapfile
        mkswap /swapfile
        swapon /swapfile
        if ! grep -q "/swapfile" /etc/fstab; then
            echo '/swapfile none swap sw 0 0' >> /etc/fstab
        fi
        echo "✅ Archivo Swap de 2GB activado y persistido en /etc/fstab."
    fi
else
    echo "✅ Capacidad de memoria suficiente o Swap ya configurado."
fi

# ------------------------------------------------------------------------------
# 2. Desbloqueo de Cortafuegos Interno de Oracle Cloud (iptables)
# ------------------------------------------------------------------------------
echo "🛡️ Configurando cortafuegos de Oracle Cloud (puertos 80 HTTP y 443 HTTPS)..."
export DEBIAN_FRONTEND=noninteractive

apt-get update -y
apt-get install -y iptables-persistent netfilter-persistent

# Insertar reglas de aceptación antes de las reglas de REJECT / DROP si no existen
REJECT_LINE=$(iptables -L INPUT -n --line-numbers | grep -E "REJECT|DROP" | head -n 1 | awk '{print $1}')
if ! iptables -C INPUT -p tcp --dport 80 -j ACCEPT 2>/dev/null; then
    if [ -n "${REJECT_LINE}" ]; then
        iptables -I INPUT "${REJECT_LINE}" -p tcp -m state --state NEW --dport 80 -j ACCEPT
        REJECT_LINE=$((REJECT_LINE + 1))
    else
        iptables -A INPUT -p tcp -m state --state NEW --dport 80 -j ACCEPT
    fi
fi

if ! iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null; then
    if [ -n "${REJECT_LINE}" ]; then
        iptables -I INPUT "${REJECT_LINE}" -p tcp -m state --state NEW --dport 443 -j ACCEPT
    else
        iptables -A INPUT -p tcp -m state --state NEW --dport 443 -j ACCEPT
    fi
fi

netfilter-persistent save
echo "✅ Reglas de iptables persistidas."

# ------------------------------------------------------------------------------
# 3. Instalación de Paquetes y Dependencias del Sistema Operativo
# ------------------------------------------------------------------------------
echo "📦 Instalando paquetes del sistema..."
apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    git \
    build-essential \
    libjpeg-dev \
    zlib1g-dev \
    libfreetype6-dev \
    nginx \
    certbot \
    python3-certbot-nginx \
    curl \
    unzip

# Instalar Chromium headless para rasterizado de SVG vectorial si está disponible
if apt-get install -y chromium-browser 2>/dev/null; then
    echo "✅ Chromium browser instalado para renderizado de gráficos/logos."
elif apt-get install -y chromium 2>/dev/null; then
    echo "✅ Chromium instalado."
fi

# ------------------------------------------------------------------------------
# 4. Despliegue de Archivos del Proyecto
# ------------------------------------------------------------------------------
echo "📂 Preparando directorio de la aplicación en ${APP_DIR}..."
mkdir -p "${APP_DIR}"

if [ "${SOURCE_DIR}" != "${APP_DIR}" ]; then
    echo "📋 Sincronizando código fuente..."
    rsync -av --exclude='.venv' --exclude='__pycache__' --exclude='.git' --exclude='node_modules' "${SOURCE_DIR}/" "${APP_DIR}/"
fi

mkdir -p "${APP_DIR}/data" "${APP_DIR}/output" "${APP_DIR}/logs" "${APP_DIR}/assets"

# Crear .env si no existe a partir del ejemplo
if [ ! -f "${APP_DIR}/.env" ]; then
    if [ -f "${APP_DIR}/.env.example" ]; then
        cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
        echo "⚠️ Se ha creado ${APP_DIR}/.env con valores de ejemplo. Recuerda editarlo con tus credenciales."
    fi
fi

# ------------------------------------------------------------------------------
# 5. Configuración del Entorno Virtual de Python
# ------------------------------------------------------------------------------
echo "🐍 Configurando entorno virtual de Python (.venv)..."
cd "${APP_DIR}"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

.venv/bin/pip install --upgrade pip
if [ -f "requirements.txt" ]; then
    .venv/bin/pip install -r requirements.txt
else
    echo "❌ No se encontró requirements.txt en ${APP_DIR}."
    exit 1
fi

# Asegurar permisos correctos (lectura/escritura para SQLite y carpetas de salida)
chmod -R u+rwX,g+rwX "${APP_DIR}"
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"

# ------------------------------------------------------------------------------
# 6. Configuración del Servicio Systemd (intervals-web)
# ------------------------------------------------------------------------------
echo "⚙️ Configurando servicio Systemd intervals-web..."
SERVICE_FILE="/etc/systemd/system/intervals-web.service"

sed -e "s|User=ubuntu|User=${APP_USER}|g" \
    -e "s|Group=ubuntu|Group=${APP_USER}|g" \
    -e "s|/var/www/intervals_fit_analytics|${APP_DIR}|g" \
    "${APP_DIR}/deploy/intervals-web.service" > "${SERVICE_FILE}"

systemctl daemon-reload
systemctl enable intervals-web
systemctl restart intervals-web

# Verificar que el servicio esté activo
sleep 2
if systemctl is-active --quiet intervals-web; then
    echo "✅ Servicio intervals-web iniciado correctamente y en ejecución."
else
    echo "⚠️ El servicio intervals-web falló al arrancar. Mostrando log reciente:"
    journalctl -u intervals-web -n 20 --no-pager
fi

# ------------------------------------------------------------------------------
# 7. Configuración de Nginx
# ------------------------------------------------------------------------------
echo "🌐 Configurando Nginx Reverse Proxy..."
NGINX_AVAILABLE="/etc/nginx/sites-available/intervals"
NGINX_ENABLED="/etc/nginx/sites-enabled/intervals"

sed -e "s|/var/www/intervals_fit_analytics|${APP_DIR}|g" \
    "${APP_DIR}/deploy/nginx_intervals.conf" > "${NGINX_AVAILABLE}"

ln -sf "${NGINX_AVAILABLE}" "${NGINX_ENABLED}"

# Deshabilitar sitio por defecto si existe para evitar conflictos
if [ -f /etc/nginx/sites-enabled/default ]; then
    rm -f /etc/nginx/sites-enabled/default
fi

nginx -t
systemctl reload nginx
echo "✅ Nginx configurado y recargado."

# ------------------------------------------------------------------------------
# 8. Resumen Final
# ------------------------------------------------------------------------------
PUBLIC_IP=$(curl -s -4 ifconfig.me || curl -s -4 icanhazip.com || echo "<IP_PUBLICA>")

echo "===================================================================="
echo "🎉 ¡DESPLIEGUE COMPLETADO CON ÉXITO!"
echo "===================================================================="
echo "🌐 Portal accesible en: http://${PUBLIC_IP}"
echo "📁 Directorio del proyecto: ${APP_DIR}"
echo "⚙️ Control del servicio: sudo systemctl restart intervals-web"
echo "📜 Ver logs en vivo: sudo journalctl -u intervals-web -f"
echo ""
echo "🔒 Para activar HTTPS con certificado Let's Encrypt gratuito:"
echo "   sudo certbot --nginx -d tu-dominio.com"
echo "===================================================================="
