#!/bin/bash

set -euo pipefail

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

if [[ "$(uname -s)" != "Linux" ]]; then
    echo -e "${RED}Este instalador solo está soportado en Linux.${NC}"
    exit 1
fi

# Detectar si estamos en una Raspberry Pi
IS_RASPBERRY_PI=0
if grep -qi "raspberry pi" /proc/device-tree/model 2>/dev/null; then
    IS_RASPBERRY_PI=1
elif grep -qi "raspberry pi" /proc/cpuinfo 2>/dev/null; then
    IS_RASPBERRY_PI=1
fi

if [[ "$IS_RASPBERRY_PI" == "1" ]]; then
    echo -e "${GREEN}>>> Plataforma detectada: ${CYAN}Raspberry Pi${NC}"
else
    echo -e "${GREEN}>>> Plataforma detectada: ${CYAN}Linux genérico (no Raspberry Pi)${NC}"
fi

# Detectar gestor de paquetes disponible
PKG_MANAGER=""
if command -v apt-get >/dev/null 2>&1; then
    PKG_MANAGER="apt"
elif command -v dnf >/dev/null 2>&1; then
    PKG_MANAGER="dnf"
elif command -v yum >/dev/null 2>&1; then
    PKG_MANAGER="yum"
elif command -v pacman >/dev/null 2>&1; then
    PKG_MANAGER="pacman"
elif command -v zypper >/dev/null 2>&1; then
    PKG_MANAGER="zypper"
elif command -v apk >/dev/null 2>&1; then
    PKG_MANAGER="apk"
else
    echo -e "${RED}No se encontró un gestor de paquetes soportado (apt, dnf, yum, pacman, zypper, apk).${NC}"
    exit 1
fi

echo -e "${GREEN}>>> Gestor de paquetes detectado: ${CYAN}$PKG_MANAGER${NC}"

install_dependencies() {
    case "$PKG_MANAGER" in
        apt)
            apt-get update
            if [[ "$IS_RASPBERRY_PI" == "1" ]]; then
                apt-get install -y python3 python3-pip python3-venv git dphys-swapfile cron
            else
                apt-get install -y python3 python3-pip python3-venv git cron
            fi
            ;;
        dnf)
            dnf -y install python3 python3-pip git cronie
            ;;
        yum)
            yum -y install python3 python3-pip git cronie
            ;;
        pacman)
            pacman -Sy --noconfirm python python-pip git cronie
            ;;
        zypper)
            zypper --non-interactive install python3 python3-pip python3-virtualenv git cron
            ;;
        apk)
            apk update
            apk add python3 py3-pip py3-virtualenv git dcron
            ;;
    esac
}

has_intel_gpu() {
    for vendor_file in /sys/class/drm/card*/device/vendor; do
        if [[ ! -f "$vendor_file" ]]; then
            continue
        fi
        if grep -qi "0x8086" "$vendor_file"; then
            return 0
        fi
    done
    return 1
}

install_intel_gpu_tools() {
    if ! has_intel_gpu; then
        echo -e "${GREEN}>>> GPU Intel no detectada. Se omite intel-gpu-tools.${NC}"
        return
    fi

    echo -e "${YELLOW}>>> Detectada GPU Intel. Intentando instalar herramientas de telemetria (intel_gpu_top)...${NC}"

    case "$PKG_MANAGER" in
        apt)
            if ! apt-get install -y intel-gpu-tools; then
                echo -e "${YELLOW}>>> No se pudo instalar intel-gpu-tools automaticamente (apt).${NC}"
            fi
            ;;
        dnf)
            if ! dnf -y install intel-gpu-tools; then
                if ! dnf -y install igt-gpu-tools; then
                    echo -e "${YELLOW}>>> No se pudo instalar intel-gpu-tools/igt-gpu-tools automaticamente (dnf).${NC}"
                fi
            fi
            ;;
        yum)
            if ! yum -y install intel-gpu-tools; then
                if ! yum -y install igt-gpu-tools; then
                    echo -e "${YELLOW}>>> No se pudo instalar intel-gpu-tools/igt-gpu-tools automaticamente (yum).${NC}"
                fi
            fi
            ;;
        pacman)
            if ! pacman -Sy --noconfirm intel-gpu-tools; then
                echo -e "${YELLOW}>>> No se pudo instalar intel-gpu-tools automaticamente (pacman).${NC}"
            fi
            ;;
        zypper)
            if ! zypper --non-interactive install intel-gpu-tools; then
                if ! zypper --non-interactive install igt-gpu-tools; then
                    echo -e "${YELLOW}>>> No se pudo instalar intel-gpu-tools/igt-gpu-tools automaticamente (zypper).${NC}"
                fi
            fi
            ;;
        apk)
            if ! apk add intel-gpu-tools; then
                if ! apk add igt-gpu-tools; then
                    echo -e "${YELLOW}>>> No se pudo instalar intel-gpu-tools/igt-gpu-tools automaticamente (apk).${NC}"
                fi
            fi
            ;;
    esac

    if command -v intel_gpu_top >/dev/null 2>&1; then
        echo -e "${GREEN}>>> intel_gpu_top disponible para metricas de GPU Intel en dashboard.${NC}"
    else
        echo -e "${YELLOW}>>> intel_gpu_top no esta disponible. El dashboard no mostrara uso de GPU Intel hasta instalarlo.${NC}"
    fi
}

configure_intel_gpu_runtime_access() {
    if ! has_intel_gpu; then
        return
    fi

    if ! command -v intel_gpu_top >/dev/null 2>&1; then
        echo -e "${YELLOW}>>> intel_gpu_top no disponible. Se omite configuracion avanzada de telemetria Intel GPU.${NC}"
        return
    fi

    if ! command -v sudo >/dev/null 2>&1 || ! command -v visudo >/dev/null 2>&1; then
        echo -e "${YELLOW}>>> sudo/visudo no disponible. Se omite regla NOPASSWD para intel_gpu_top.${NC}"
        return
    fi

    for group_name in video render; do
        if getent group "$group_name" >/dev/null 2>&1; then
            if usermod -aG "$group_name" "$REAL_USER"; then
                echo -e "${GREEN}>>> Usuario ${CYAN}$REAL_USER${GREEN} agregado a grupo ${CYAN}$group_name${GREEN}.${NC}"
            fi
        fi
    done

    INTEL_GPU_TOP_BIN="$(command -v intel_gpu_top)"
    SUDOERS_FILE="/etc/sudoers.d/smartdrive-intel-gpu-top"

    cat > "$SUDOERS_FILE" <<EOF
# Smart Drive: permite telemetria Intel GPU sin password para el usuario del servicio
Defaults:${REAL_USER} !requiretty
${REAL_USER} ALL=(root) NOPASSWD: ${INTEL_GPU_TOP_BIN}
EOF
    chmod 440 "$SUDOERS_FILE"

    if visudo -cf "$SUDOERS_FILE" >/dev/null 2>&1; then
        echo -e "${GREEN}>>> Regla sudoers instalada para intel_gpu_top: ${CYAN}$SUDOERS_FILE${NC}"
    else
        echo -e "${RED}>>> Error validando sudoers para intel_gpu_top. Eliminando archivo por seguridad.${NC}"
        rm -f "$SUDOERS_FILE"
        return
    fi

    GPU_TEST_OUT="/tmp/smartdrive_intel_gpu_top_test.out"
    su - "$REAL_USER" -c "timeout 2s sudo -n ${INTEL_GPU_TOP_BIN} -J -s 120 > ${GPU_TEST_OUT} 2>/dev/null || true"

    if grep -q '"engines"' "$GPU_TEST_OUT" 2>/dev/null; then
        echo -e "${GREEN}>>> Telemetria Intel GPU verificada correctamente para ${CYAN}$REAL_USER${GREEN}.${NC}"
    else
        echo -e "${YELLOW}>>> No se pudo verificar salida JSON de intel_gpu_top en modo no interactivo. El backend aplicara fallback de ejecucion.${NC}"
    fi
}

ensure_cron_service() {
    if ! command -v systemctl >/dev/null 2>&1; then
        echo -e "${YELLOW}>>> systemctl no disponible. Revisa manualmente el servicio de cron en tu sistema.${NC}"
        return
    fi

    for service in cron crond; do
        if systemctl list-unit-files | grep -q "^${service}\.service"; then
            systemctl enable --now "$service" || true
            echo -e "${GREEN}>>> Servicio ${CYAN}${service}${GREEN} habilitado para tareas programadas.${NC}"
            return
        fi
    done

    echo -e "${YELLOW}>>> No se encontró un servicio cron reconocido (cron/crond).${NC}"
}

# ---------------------------------------------------------
# 1. ACTUALIZACIÓN Y DEPENDENCIAS
# ---------------------------------------------------------
echo -e "${YELLOW}[1/6] Actualizando sistema e instalando paquetes necesarios...${NC}"
install_dependencies
install_intel_gpu_tools
configure_intel_gpu_runtime_access

# ---------------------------------------------------------
# 2. CONFIGURACIÓN INTERACTIVA DE SWAP
# ---------------------------------------------------------
echo -e "${YELLOW}[2/6] Configuración de Memoria Virtual (SWAP)${NC}"
echo "Se recomienda SWAP extra para procesar subidas de archivos grandes."
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

if [[ "$IS_RASPBERRY_PI" == "1" ]] && command -v dphys-swapfile >/dev/null 2>&1; then
    # --- Raspberry Pi: usar dphys-swapfile ---
    dphys-swapfile swapoff
    if grep -q "^CONF_SWAPSIZE=" /etc/dphys-swapfile; then
        sed -i "s/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=$SWAP_SIZE/" /etc/dphys-swapfile
    else
        echo "CONF_SWAPSIZE=$SWAP_SIZE" >> /etc/dphys-swapfile
    fi
    dphys-swapfile setup
    dphys-swapfile swapon
else
    # --- Linux genérico o Raspberry sin dphys-swapfile: usar swapfile estándar ---
    SWAPFILE="/swapfile"
    SWAP_BYTES=$(( SWAP_SIZE * 1024 * 1024 ))
    if swapon --show | grep -q "$SWAPFILE"; then
        echo -e ">> Swapfile ${CYAN}$SWAPFILE${NC} ya está activo. Se omite la creación."
    else
        if [[ -f "$SWAPFILE" ]]; then
            echo -e ">> Swapfile ${CYAN}$SWAPFILE${NC} ya existe. Actualizando tamaño..."
            swapoff "$SWAPFILE" 2>/dev/null || true
            rm -f "$SWAPFILE"
        fi
        echo ">> Creando swapfile de ${SWAP_SIZE} MB en $SWAPFILE..."
        fallocate -l "$SWAP_BYTES" "$SWAPFILE"
        chmod 600 "$SWAPFILE"
        mkswap "$SWAPFILE"
        swapon "$SWAPFILE"
        # Añadir a /etc/fstab si no está ya
        if ! grep -q "^$SWAPFILE " /etc/fstab; then
            echo "$SWAPFILE none swap sw 0 0" >> /etc/fstab
            echo ">> Entrada añadida a /etc/fstab para persistencia."
        fi
    fi
fi

# ---------------------------------------------------------
# 3. CREACIÓN DE CARPETAS Y PERMISOS
# ---------------------------------------------------------
echo -e "${YELLOW}[3/6] Configurando almacenamiento en /mnt/midrive...${NC}"
mkdir -p /mnt/midrive/inbox
mkdir -p /mnt/midrive/files

# Permisos
chmod -R 777 /mnt/midrive
echo -e "${GREEN}>>> Carpetas listas.${NC}"

# ---------------------------------------------------------
# 4. ENTORNO VIRTUAL PYTHON
# ---------------------------------------------------------
echo -e "${YELLOW}[4/6] Instalando entorno Python...${NC}"

# Creamos el venv como el usuario REAL, no como root, para evitar problemas de permisos futuros
# Usamos 'su' para ejecutar el comando como el usuario normal
if [ ! -d "venv" ]; then
    su - $REAL_USER -c "cd $CURRENT_DIR && python3 -m venv venv"
    echo "Venv creado."
else
    echo "Venv ya existía."
fi

echo "Instalando librerías..."
if [ ! -f "$CURRENT_DIR/requirements.txt" ]; then
    echo -e "${RED}No se encontró requirements.txt en $CURRENT_DIR${NC}"
    exit 1
fi

# Ejecutamos pip dentro del venv usando requirements.txt
su - "$REAL_USER" -c "cd \"$CURRENT_DIR\" && . venv/bin/activate && python -m pip install --upgrade pip && python -m pip install -r requirements.txt"

# ---------------------------------------------------------
# 5. CREAR SERVICIO SYSTEMD (AUTO-ARRANQUE)
# ---------------------------------------------------------
echo -e "${YELLOW}[5/6] Creando servicio de auto-arranque...${NC}"

if ! command -v systemctl >/dev/null 2>&1; then
    echo -e "${RED}Este instalador requiere systemd (systemctl) para configurar el servicio smartdrive.${NC}"
    exit 1
fi

SERVICE_FILE="/etc/systemd/system/smartdrive.service"

cat > $SERVICE_FILE <<EOF
[Unit]
Description=Smart Drive Server
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
if ! command -v crontab >/dev/null 2>&1; then
    echo -e "${RED}No se encontró crontab. Instala un servicio cron y vuelve a ejecutar el instalador.${NC}"
    exit 1
fi

(crontab -l 2>/dev/null; echo "0 4 * * * find /mnt/midrive/inbox -name '*.part' -type f -mtime +1 -delete") | sort -u | crontab -
ensure_cron_service

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
