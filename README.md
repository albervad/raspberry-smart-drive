# 🍓 Raspberry Pi Smart Drive

Un gestor de archivos web ligero, moderno y rápido diseñado para Raspberry Pi. Permite subir archivos, organizarlos en carpetas y gestionar tu almacenamiento USB desde cualquier navegador en tu red local.

<img width="762" height="900" alt="image" src="https://github.com/user-attachments/assets/aab1d20c-208d-48ec-ba30-9b0a97cc2289" />

## ✨ Características

- **Dashboard Visual:** Ver uso de disco y espacio libre en tiempo real.
- **Inbox & Clasificación:** Sube archivos a una bandeja de entrada y muévelos a carpetas organizadas.
- **Gestión de Carpetas:** Crea carpetas y subcarpetas con ordenación inteligente.
- **Árbol de Archivos:** Visualización jerárquica con recuento recursivo de archivos.
- **Iconos SVG:** Interfaz limpia y moderna (Glassmorphism Dark UI).
- **Backend Robusto:** Construido con Python (FastAPI).

## 🛠️ Requisitos

- Raspberry Pi (Cualquier modelo con Python 3).
- Un pendrive o disco duro USB (recomendado).

## 🚀 Instalación Rápida

1. **Clona este repositorio:**
   ```bash
   git clone https://github.com/albervad/raspberry-smart-drive.git
   cd raspberry-smart-drive
Dale permisos de ejecución al instalador:

Bash

chmod +x install.sh start.sh
Ejecuta el instalador:

Bash

./install.sh
(Opcional) Monta tu USB: El sistema espera que los datos estén en /mnt/midrive. Si usas un USB, asegúrate de montarlo:

Bash

sudo mount /dev/sda1 /mnt/midrive
# Recuerda darle permisos de escritura si es NTFS/FAT32
▶️ Uso
Inicia el servidor con:

Bash

./start.sh
Abre tu navegador y entra en: http://TU_IP:8000

📂 Estructura del Proyecto
/inbox: Donde aterrizan los archivos recién subidos.

/files: Donde se catalogan y ordenan los archivos finales.

🤝 Contribuir
¡Los Pull Requests son bienvenidos!
