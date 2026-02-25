# 🍓 Raspberry Pi Smart Drive (Security-Focused)

Proyecto de almacenamiento personal en Raspberry Pi con frontend web y backend FastAPI, diseñado con enfoque en **seguridad defensiva aplicada**: validación de rutas, control de superficie de búsqueda de contenido y despliegue seguro sin exponer puertos.

<img width="611" height="788" alt="image" src="https://github.com/user-attachments/assets/5ba5e4e8-aa9d-4787-ae77-c98848e4fe53" />

## 🎯 Objetivo del proyecto

Construir un servicio de archivos autohospedado que sea útil en casa/lab y, al mismo tiempo, sirva como pieza de portfolio orientada a ciberseguridad:

- Diseño de controles básicos de hardening en backend.
- Reducción de riesgos típicos (Path Traversal, lectura fuera de base, abuso de búsqueda).
- Exposición remota con acceso seguro (Zero Trust / red privada).

## 🧩 Funcionalidades principales

- Subida de archivos por chunks con reintentos y cierre controlado.
- Inbox + catálogo en árbol de carpetas.
- Operaciones de archivo/carpeta: mover, renombrar, borrar, descargar y abrir.
- Búsqueda por nombre y contenido con selector de modo.
- Descarga de carpetas en ZIP.

## 🔐 Controles de seguridad implementados

### 1) Validación estricta de rutas

- Se normalizan rutas con `realpath` y se verifica que permanezcan dentro de las bases permitidas (`/mnt/midrive/inbox` y `/mnt/midrive/files`).
- Se evita acceso fuera de la “jaula” (mitigación de Path Traversal / LFI).

### 2) Defensa adicional en búsqueda de contenido

- Se ignoran symlinks durante el recorrido de archivos.
- Se verifica que cada `realpath` siga dentro del directorio base antes de procesarlo.

### 3) Reducción de superficie de parsing

- La búsqueda de contenido se limita a formatos legibles permitidos (texto y documentos extraíbles), excluyendo imágenes/vídeos.
- Se aplican límites de tamaño por archivo y número máximo de resultados para evitar abuso de recursos.

### 4) Validación de parámetros de entrada

- Longitud máxima de consulta en búsqueda.
- Validación del modo de búsqueda (`both`, `name`, `content`).
- Respuestas con códigos HTTP adecuados ante parámetros inválidos.

### 5) Operación de servicio controlada

- Ejecución en `systemd` con reinicio automático.
- Limpieza programada de archivos temporales `.part` por `cron`.

## ⚠️ Riesgos conocidos / límites actuales

- No incluye autenticación/autorización nativa en la app web.
- No hay registro de auditoría completo de acciones (quién hizo qué y cuándo).
- No hay antimalware ni DLP en subidas.

Esto se mitiga recomendando despliegue detrás de una capa segura de acceso.

## 🌐 Exposición segura (recomendado)

### Opción A: Cloudflare Zero Trust (Tunnel)

- Publicación sin abrir puertos en router.
- Control de acceso, políticas y capa Zero Trust.

### Opción B: Tailscale

- Acceso por red privada mesh (WireGuard).
- Menor superficie pública, ideal para uso personal/lab.

> Recomendación: no exponer directamente `:8000` a Internet.

## 🛠️ Requisitos

- Raspberry Pi con Python 3.
- Debian/Raspberry Pi OS con `sudo`.
- Disco/pendrive montado en `/mnt/midrive`.

## 🚀 Instalación rápida

1. Clonar:

   ```bash
   git clone https://github.com/albervad/raspberry-smart-drive.git
   cd raspberry-smart-drive
   ```

2. Dar permisos:

   ```bash
   chmod +x install.sh start.sh
   ```

3. Instalar:

   ```bash
   sudo ./install.sh
   ```

El instalador configura dependencias, entorno virtual, carpetas de datos, servicio `smartdrive` y limpieza diaria de temporales.

## ▶️ Ejecución

### Producción

```bash
sudo systemctl start smartdrive
sudo systemctl status smartdrive
```

### Desarrollo

```bash
./start.sh
```

Acceso local:

- `http://TU_IP:8000`

## 🗂️ Estructura de datos

- `/mnt/midrive/inbox`: archivos recién subidos.
- `/mnt/midrive/files`: archivos catalogados.

## 🛣️ Roadmap de seguridad (portfolio)

- Autenticación fuerte (OIDC/SSO o MFA) y roles mínimos.
- Logging de auditoría estructurado y centralizado.
- Rate limiting por endpoint sensible.
- Escaneo de ficheros subidos (AV) y política de cuarentena.
- Hardening HTTP (cabeceras, CORS estricto, CSP en frontend).

## 🤝 Contribuciones

Pull Requests bienvenidos.
