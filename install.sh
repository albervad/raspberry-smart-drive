#!/bin/bash

# ==========================================
# INSTALADOR RASPBERRY PI SMART DRIVE v3
# ==========================================

# Colores para output visual
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

# Comprobar si se ejecuta como root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Por favor, ejecuta este script como root (usando sudo).${NC}"
  echo "Ejemplo: sudo ./install.sh"
  exit
fi

# Detectar el usuario real (el que invocó sudo) para el servicio systemd
REAL_USER=${SUDO_USER:-$(whoami)}
CURRENT_DIR=$(pwd)

echo -e "${GREEN}>>> Iniciando instalación para el usuario: ${CYAN}$REAL_USER${NC}"
echo -e "${GREEN}>>> Directorio de instalación: ${CYAN}$CURRENT_DIR${NC}"

# ---------------------------------------------------------
# 1. ACTUALIZACIÓN Y DEPENDENCIAS
# ---------------------------------------------------------
echo -e "${YELLOW}[1/5] Actualizando sistema e instalando paquetes necesarios...${NC}"
apt update
# git: control de versiones
# python3-venv: entornos virtuales
# dphys-swapfile: gestor de swap fácil
# htopy/iotop (opcionales pero recomendados para monitorizar): los añado como extra
apt install -y python3-pip python3-venv git dphys-swapfile

# ---------------------------------------------------------
# 2. CONFIGURACIÓN INTERACTIVA DE SWAP
# ---------------------------------------------------------
echo -e "${YELLOW}[2/5] Configuración de Memoria Virtual (SWAP)${NC}"
echo "La Raspberry Pi necesita SWAP extra para procesar subidas de archivos grandes."
echo -e "Recomendado: ${CYAN}2048${NC} (2GB) para uso normal."

read -p "Introduce el tamaño de SWAP en MB (Enter para usar 2048): " SWAP_INPUT

# Validación: Si está vacío o no es un número, usar default
if [[ -z "$SWAP_INPUT" ]]; then
    SWAP_SIZE=2048
    echo -e ">> Usando valor por defecto: ${CYAN}2048 MB${NC}"
elif [[ ! $SWAP_INPUT =~ ^[0-9]+$ ]]; then
    SWAP_SIZE=2048
    echo -e "${RED}>> Entrada inválida. Usando valor seguro por defecto: 2048 MB${NC}"
else
    SWAP_SIZE=$SWAP_INPUT
    echo -e ">> Configurando SWAP a: ${CYAN}$SWAP_SIZE MB${NC}"
fi

# Aplicar configuración de SWAP
dphys-swapfile swapoff
if grep -q "^CONF_SWAPSIZE=" /etc/dphys-swapfile; then
    sed -i "s/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=$SWAP_SIZE/" /etc/dphys-swapfile
else
    echo "CONF_SWAPSIZE=$SWAP_SIZE" >> /etc/dphys-swapfile
fi
dphys-swapfile setup
dphys-swapfile swapon

# ---------------------------------------------------------
# 3. CREACIÓN DE CARPETAS Y PERMISOS
# ---------------------------------------------------------
echo -e "${YELLOW}[3/5] Configurando almacenamiento en /mnt/midrive...${NC}"
mkdir -p /mnt/midrive/inbox
mkdir -p /mnt/midrive/files

# Permisos
chmod -R 777 /mnt/midrive
echo -e "${GREEN}>>> Carpetas listas.${NC}"

# ---------------------------------------------------------
# 4. ENTORNO VIRTUAL PYTHON
# ---------------------------------------------------------
echo -e "${YELLOW}[4/5] Instalando entorno Python...${NC}"

# Creamos el venv como el usuario REAL, no como root, para evitar problemas de permisos futuros
# Usamos 'su' para ejecutar el comando como el usuario normal
if [ ! -d "venv" ]; then
    su - $REAL_USER -c "cd $CURRENT_DIR && python3 -m venv venv"
    echo "Venv creado."
else
    echo "Venv ya existía."
fi

echo "Instalando librerías..."
# Ejecutamos pip dentro del venv
su - $REAL_USER -c "cd $CURRENT_DIR && source venv/bin/activate && pip install --upgrade pip && pip install fastapi uvicorn python-multipart jinja2 natsort aiofiles pypdf"

# ---------------------------------------------------------
# 5. CREAR SERVICIO SYSTEMD (AUTO-ARRANQUE)
# ---------------------------------------------------------
echo -e "${YELLOW}[5/5] Creando servicio de auto-arranque...${NC}"

SERVICE_FILE="/etc/systemd/system/smartdrive.service"

cat > $SERVICE_FILE <<EOF
[Unit]
Description=Raspberry Pi Smart Drive Server
After=network.target

[Service]
User=$REAL_USER
Group=$REAL_USER
WorkingDirectory=$CURRENT_DIR
# Usamos la ruta absoluta al python del venv
ExecStart=$CURRENT_DIR/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Recargar y activar
systemctl daemon-reload
systemctl enable smartdrive.service

# Obtener IP para mostrar al final
MY_IP=$(hostname -I | awk '{print $1}')


# ---------------------------------------------------------
# 6. CONFIGURAR LIMPIEZA AUTOMÁTICA (CRON)
# ---------------------------------------------------------
echo -e "${YELLOW}[6/6] Configurando limpieza automática de archivos temporales...${NC}"

# Tarea: Ejecutar cada día a las 04:00 AM
# Comando: Buscar en inbox archivos terminados en .part modificados hace más de 1 día (+1) y borrarlos.
(crontab -l 2>/dev/null; echo "0 4 * * * find /mnt/midrive/inbox -name '*.part' -type f -mtime +1 -delete") | sort -u | crontab -

echo -e "${GREEN}>>> Tarea programada: Limpieza de .part antiguos (24h) a las 04:00 AM.${NC}"
echo -e "${GREEN}==============================================${NC}"
echo -e "${GREEN}   ¡INSTALACIÓN COMPLETADA CON ÉXITO!  ${NC}"
echo -e "${GREEN}==============================================${NC}"
echo -e "1. SWAP configurada a: ${CYAN}${SWAP_SIZE} MB${NC}"
echo -e "2. Servicio instalado como usuario: ${CYAN}$REAL_USER${NC}"
echo -e "3. Accede a tu nube aquí: ${CYAN}http://$MY_IP:8000${NC}"
echo -e ""
echo -e "Para iniciar el servicio ahora mismo ejecuta:"
echo -e "${YELLOW}sudo systemctl start smartdrive${NC}"
