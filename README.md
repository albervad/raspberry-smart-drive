# Smart Drive 🛡️📁

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=flat&logo=fastapi)
![Linux](https://img.shields.io/badge/Linux-Compatible-FCC624?logo=linux&logoColor=black)
![Security](https://img.shields.io/badge/Security-Hardened-red.svg)

Proyecto de web personal con frontend web y backend FastAPI, diseñado con enfoque en **seguridad defensiva aplicada**: validación de rutas, control de superficie de búsqueda de contenido y despliegue seguro sin exponer puertos.

<details>
  <summary><b>📸 Ver capturas de pantalla de la interfaz (Desplegar)</b></summary>
  <br>
  <img width="1874" height="921" alt="Dashboard Principal" src="https://github.com/user-attachments/assets/2c68bc8e-df0c-4c71-ac89-945f049241aa" />
  <img width="1856" height="922" alt="Explorador de Archivos" src="https://github.com/user-attachments/assets/6441ce17-93fd-42b0-8043-ed325f7f3305" />
  <img width="1872" height="917" alt="Vista de Búsqueda" src="https://github.com/user-attachments/assets/d50e3108-e7ce-481e-b111-279776226d9d" />
  <img width="1871" height="921" alt="Panel de Control" src="https://github.com/user-attachments/assets/a4d22c7e-e6f8-4d94-8707-5f5278a589a0" />
  <img width="1866" height="915" alt="Detalles Adicionales" src="https://github.com/user-attachments/assets/ce3f7b16-e11e-4dd2-a3ae-4f7bb2785209" />
</details>

---

## 📑 Tabla de contenidos

- [🎯 Objetivo del proyecto](#objetivo-del-proyecto)
- [🧩 Funcionalidades principales](#funcionalidades-principales)
- [🔐 Controles de seguridad implementados](#controles-de-seguridad-implementados)
- [⚠️ Riesgos conocidos / límites actuales](#riesgos-conocidos-limites-actuales)
- [🌐 Exposición segura (recomendado)](#exposicion-segura-recomendado)
- [🛠️ Requisitos e instalación](#requisitos-e-instalacion)
- [▶️ Ejecución y entornos](#ejecucion-y-entornos)
- [🗂️ Estructura de datos](#estructura-de-datos)
- [🛂 Panel de control de accesos](#panel-de-control-de-accesos)
- [🛣️ Roadmap de seguridad (portfolio)](#roadmap-de-seguridad-portfolio)

---

<a id="objetivo-del-proyecto"></a>
## 🎯 Objetivo del proyecto

Construir un servicio de archivos autohospedado que sea útil en casa/lab y, al mismo tiempo, sirva como pieza de portfolio orientada a ciberseguridad:

- Diseño de controles básicos de hardening en backend.
- Reducción de riesgos típicos (Path Traversal, lectura fuera de base, abuso de búsqueda).
- Exposición remota con acceso seguro (Zero Trust / red privada).

<a id="funcionalidades-principales"></a>
## 🧩 Funcionalidades principales

- **Estructura de navegación:** Portfolio público en `/` (alias legacy: `/portfolio`), dashboard de entrada en `/dashboard` y drive operativo bajo `/drive`.
- **Dashboard unificado:** Selector de entorno (local `192.168.1.47` / remoto `199.68.161.18`) con accesos directos a Seerr, Jellyfin, Radarr, Sonarr, Jackett y qBittorrent.
- **Monitorización del sistema:** Métricas en vivo (temperatura, CPU, RAM, disco, carga media, uptime) y consumo energético si el hardware lo expone.
- **Estimación de costes:** Cálculo eléctrico configurable (`static/data/energy_rates.json`) por hora/día/mes y uso de GPU (soporta múltiples gráficas).
- **Gestión de archivos (Drive):** Subida por chunks con reintentos, inbox + catálogo en árbol y operaciones completas (mover, renombrar, borrar, descargar, abrir y descargar en ZIP).
- **Búsqueda avanzada:** Por nombre y contenido con selector de modo.

<a id="controles-de-seguridad-implementados"></a>
## 🔐 Controles de seguridad implementados

### 1) Validación estricta de rutas

Se normalizan rutas con `realpath` y se verifica que permanezcan dentro de las bases permitidas (`/mnt/midrive/inbox` y `/mnt/midrive/files`). Esto evita acceso fuera de la "jaula" (mitigación de Path Traversal / LFI).

### 2) Defensa adicional en búsqueda de contenido

Se ignoran symlinks durante el recorrido de archivos y se verifica que cada `realpath` siga dentro del directorio base antes de procesarlo.

### 3) Reducción de superficie de parsing

La búsqueda de contenido se limita a formatos legibles permitidos (texto y documentos extraíbles), excluyendo imágenes y vídeos. Se aplican límites de tamaño por archivo y número máximo de resultados para evitar abuso de recursos.

### 4) Validación de parámetros de entrada

Longitud máxima de consulta, validación del modo de búsqueda (`both`, `name`, `content`) y respuestas con códigos HTTP adecuados ante anomalías.

### 5) Operación de servicio controlada

Ejecución en `systemd` con reinicio automático. Limpieza programada de archivos temporales `.part` gestionada por `cron`.

### 6) Segmentación de superficie expuesta

- Zona funcional concentrada en `/drive`.
- Endpoints de documentación FastAPI deshabilitados en producción: `/docs`, `/redoc`, `/openapi.json`.
- Assets estáticos aislados en `/static`.

<a id="riesgos-conocidos-limites-actuales"></a>
## ⚠️ Riesgos conocidos / límites actuales

> [!WARNING]
> **Autenticación y auditoría**
> - No incluye autenticación/autorización nativa en la app web.
> - No hay registro de auditoría completo de acciones (quién hizo qué y cuándo a nivel detallado).

> [!WARNING]
> **Procesamiento de archivos**
> - No hay antimalware ni DLP en subidas.
> - **Riesgo de ZIP bomb / compresión abusiva:** No existe una defensa específica para detectar archivos comprimidos maliciosos durante extracción de contenido o cargas diseñadas para agotar recursos.

Esto se mitiga recomendando despliegue detrás de una capa segura de acceso.

<a id="exposicion-segura-recomendado"></a>
## 🌐 Exposición segura (recomendado)

> [!IMPORTANT]
> Nunca expongas directamente el puerto `:8000` a Internet sin una capa de seguridad intermedia.

### Cloudflare WAF (producción actual)

La política WAF debe configurarse para bloquear rutas no permitidas y usar una allowlist para:
`/`, `/portfolio`, `/dashboard`, `/static/`, `/drive`, `/favicon.ico`, `/cdn-cgi/` (login/challenge de Cloudflare).

### Alternativas de despliegue seguro

- **Opción A: Cloudflare Zero Trust (Tunnel).** Publicación sin abrir puertos en router. Control de acceso y políticas Zero Trust.
- **Opción B: Tailscale.** Acceso por red privada mesh (WireGuard). Menor superficie pública, ideal para uso personal/lab.

<a id="requisitos-e-instalacion"></a>
## 🛠️ Requisitos e instalación

### Requisitos previos

- Linux con `sudo`, `systemd` y `cron` (o `crond`).
- Python 3 y `git`.
- Disco/pendrive montado en `/mnt/midrive`.
- Opcional: para métricas de GPU Intel, paquete `intel-gpu-tools` o `igt-gpu-tools` según distro.

### Sistemas operativos compatibles

El instalador detecta la plataforma automáticamente:

- Raspberry Pi OS / Debian / Ubuntu Server (`apt`).
- Fedora / RHEL derivados (`dnf` o `yum`).
- Arch Linux (`pacman`).
- openSUSE (`zypper`).
- Alpine Linux (`apk`).

### Instalación rápida

1. Clonar el repositorio:

```bash
git clone https://github.com/albervad/raspberry-smart-drive.git
cd raspberry-smart-drive
```

2. Dar permisos de ejecución:

```bash
chmod +x install.sh start.sh
```

3. Ejecutar instalador:

```bash
sudo ./install.sh
```

<a id="ejecucion-y-entornos"></a>
## ▶️ Ejecución y entornos

### Producción

El servicio público corre desde un directorio aislado (`/home/alberto/mydrive-prod-main`). La web pública solo se actualiza cuando publicas explícitamente.

```bash
# Gestión del servicio
sudo systemctl start smartdrive
sudo systemctl status smartdrive

# Desplegar cambios a producción
./deploy_main_to_public.sh [rama_opcional]
```

### Desarrollo

El puerto `8000` está reservado para producción (`main`). Para desarrollo local, usa `8001`.

```bash
./start.sh 8001
```

> [!TIP]
> Parámetros opcionales: `./start.sh [PORT] [HOST] [BASE_MOUNT]`

Variables de entorno útiles para debug:

- `SMARTDRIVE_DEBUG=1`: activa modo debug.
- `SMARTDRIVE_REQUEST_LOGGING=1`: activa middleware de trazas HTTP.
- `SMARTDRIVE_BASE_MOUNT=/tmp/smartdrive-dev`: aísla los datos para no tocar el disco principal.

Ejemplo de arranque seguro para depuración:

```bash
SMARTDRIVE_DEBUG=1 SMARTDRIVE_REQUEST_LOGGING=1 SMARTDRIVE_BASE_MOUNT=/tmp/smartdrive-dev ./start.sh 8001 127.0.0.1
```

<a id="estructura-de-datos"></a>
## 🗂️ Estructura de datos

- `/mnt/midrive/inbox`: archivos recién subidos.
- `/mnt/midrive/files`: archivos catalogados.

<a id="panel-de-control-de-accesos"></a>
## 🛂 Panel de control de accesos

- URL: `/control`.
- Muestra usuarios detectados pasivamente (cookie técnica + IP + user-agent + idioma).
- Permite bloquear/desbloquear usuarios y gestionar roles `admin` para excluir sus visitas de analíticas.
- Registra acciones clave (subidas, borrados, descargas ZIP, etc.).
- Protegido mediante CSRF estricto en endpoints mutables (`POST`/`PUT`/`PATCH`/`DELETE`).

<a id="roadmap-de-seguridad-portfolio"></a>
## 🛣️ Roadmap de seguridad (portfolio)

- [ ] Autenticación fuerte (OIDC/SSO o MFA) y roles mínimos.
- [ ] Logging de auditoría estructurado y centralizado.
- [ ] Rate limiting por endpoint sensible.
- [ ] Escaneo de ficheros subidos (AV) y política de cuarentena.
- [ ] Hardening HTTP (cabeceras, CORS estricto, CSP en frontend).

## 🤝 Contribuciones

Pull Requests bienvenidos.
