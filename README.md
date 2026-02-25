# 🍓 Raspberry Pi Smart Drive

Gestor de archivos web ligero para Raspberry Pi. Permite subir, organizar y mover archivos en un almacenamiento montado (USB o local) desde cualquier navegador de tu red.

<img width="611" height="788" alt="image" src="https://github.com/user-attachments/assets/5ba5e4e8-aa9d-4787-ae77-c98848e4fe53" />

## ✨ Características

- **Dashboard de almacenamiento:** muestra espacio usado/libre y porcentaje.
- **Subida robusta por chunks:** soporta archivos grandes con reintentos y finalización segura.
- **Inbox + catálogo:** los archivos llegan a Inbox y se mueven al árbol de carpetas.
- **Acciones por archivo:** **Descargar** (directo) y **Abrir** (nueva pestaña) como acciones separadas.
- **Gestión de carpetas:** crear, renombrar, borrar carpeta vacía y descarga como ZIP.
- **Drag & drop:** mover archivos de Inbox al catálogo soltando en carpeta destino.
- **Backend FastAPI:** API simple y rápida para operaciones de archivos.

## 🛠️ Requisitos

- Raspberry Pi con Python 3.
- Disco/pendrive (recomendado) montado en `/mnt/midrive`.

## 🚀 Instalación rápida

1. Clona el repositorio:

   ```bash
   git clone https://github.com/albervad/raspberry-smart-drive.git
   cd raspberry-smart-drive
   ```

2. Da permisos de ejecución:

   ```bash
   chmod +x install.sh start.sh
   ```

3. Ejecuta el instalador:

   ```bash
   sudo ./install.sh
   ```

   El instalador se encarga de:
   - Instalar dependencias del sistema (`python3-venv`, `python3-pip`, etc.).
   - Crear y configurar `venv`.
   - Instalar librerías Python necesarias.
   - Crear carpetas `/mnt/midrive/inbox` y `/mnt/midrive/files`.
   - Crear el servicio `systemd` (`smartdrive.service`) para autoarranque.
   - Programar limpieza diaria de archivos temporales `.part` vía `cron`.

4. (Opcional) Monta tu USB en `/mnt/midrive`:

   ```bash
   sudo mount /dev/sda1 /mnt/midrive
   ```

   Si usas NTFS/FAT32, asegúrate de tener permisos de escritura.

## ▶️ Uso

### Producción (recomendado)

Tras la instalación:

```bash
sudo systemctl start smartdrive
sudo systemctl status smartdrive
```

### Desarrollo

Inicia el servidor en modo desarrollo (con `--reload`):

```bash
./start.sh
```

Luego abre en el navegador:

- `http://TU_IP:8000`

## 📂 Estructura de datos

- `/mnt/midrive/inbox`: archivos recién subidos.
- `/mnt/midrive/files`: archivos catalogados en carpetas.

## 🌐 Acceso remoto (portfolio)


- **Cloudflare Zero Trust (Tunnel):** exposición segura sin abrir puertos en el router.
- **Tailscale:** acceso privado tipo VPN mesh entre tus dispositivos.

Recomendación: deja aquí el resumen y, si quieres, crea luego una guía más sdetallada en `docs/deployment.md`.

## 🔒 Nota de seguridad

- No expongas `:8000` directamente a Internet.
- Usa autenticación y una capa de acceso seguro (Cloudflare Zero Trust o Tailscale).

## 🤝 Contribuir

Pull Requests bienvenidos.
