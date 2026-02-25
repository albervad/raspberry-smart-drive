import shutil
import os
import asyncio
from contextlib import asynccontextmanager
from urllib.parse import quote, unquote
from fastapi import FastAPI, Request, File, UploadFile, HTTPException, Form, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse 
from pydantic import BaseModel
from natsort import natsorted

# ==========================================
# 1. CONFIGURACIÓN Y CONSTANTES GLOBALES
# ==========================================
BASE_MOUNT = "/mnt/midrive"
INBOX_DIR = os.path.join(BASE_MOUNT, "inbox")
FILES_DIR = os.path.join(BASE_MOUNT, "files")

# ==========================================
# 2. GESTIÓN DEL ARRANQUE (LIFESPAN)
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Se ejecuta al iniciar el servidor.
    Crea las carpetas necesarias y verifica permisos.
    """
    carpetas = [INBOX_DIR, FILES_DIR]
    print(f"--> Iniciando Smart Drive. Verificando rutas...")
    
    for folder in carpetas:
        if not os.path.exists(folder):
            try:
                os.makedirs(folder, exist_ok=True)
                print(f"    [OK] Creada carpeta: {folder}")
            except PermissionError:
                print(f"    [ERROR] Sin permisos para crear: {folder}")
        else:
            print(f"    [OK] Detectada: {folder}")
            
    yield
    print("--> Apagando Smart Drive...")

# ==========================================
# 3. INICIALIZACIÓN DE LA APP
# ==========================================
app = FastAPI(lifespan=lifespan)

# Montaje de archivos estáticos y plantillas
# Nota: Si el disco no está montado, /data podría fallar, pero el servidor arrancará.
if os.path.exists(BASE_MOUNT):
    app.mount("/data", StaticFiles(directory=BASE_MOUNT), name="datos")

# Importante: Montar la carpeta static local para el JS/CSS
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")


# ==========================================
# 4. FUNCIONES AUXILIARES (HELPERS)
# ==========================================

def sanitizar_ruta_entrada(user_input: str, base_dir: str) -> str:
    """Evita ataques de Path Traversal asegurando que la ruta esté dentro del base_dir."""
    if not user_input:
        return base_dir # Si es vacío, devolvemos la base (ej: raíz)

    # Combinar y resolver ruta absoluta
    requested_path = os.path.join(base_dir, user_input)
    safe_path = os.path.realpath(requested_path)
    
    # Verificar que seguimos dentro de la jaula
    if not safe_path.startswith(os.path.realpath(base_dir)):
        raise HTTPException(
            status_code=403, 
            detail=f"Forbidden: Acceso denegado a {user_input}"
        )
    return safe_path

def formatear_tamano(size: int) -> str:
    """Convierte bytes a formato legible (KB, MB, GB)."""
    for unidad in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.2f} {unidad}"
        size /= 1024
    return f"{size:.2f} PB"

def obtener_uso_disco():
    """Devuelve espacio usado, libre y porcentaje."""
    try:
        if not os.path.exists(BASE_MOUNT):
            return "0 B", "0 B", "0"
            
        total, used, free = shutil.disk_usage(BASE_MOUNT)
        return formatear_tamano(used), formatear_tamano(free), f"{(used / total) * 100:.1f}"
    except Exception:
        return "Error", "Error", "0"

def listar_archivos_inbox():
    """Lista archivos planos del Inbox."""
    if not os.path.exists(INBOX_DIR):
        return []
        
    archivos = natsorted(os.listdir(INBOX_DIR))
    lista = []
    
    for nombre in archivos:
        ruta = os.path.join(INBOX_DIR, nombre)
        if os.path.isfile(ruta):
            # Ignoramos los archivos temporales .part de las subidas
            if nombre.endswith(".part"):
                continue
                
            lista.append({
                "nombre": nombre,
                "tamano": formatear_tamano(os.path.getsize(ruta)),
                "url_encoded": quote(nombre),
                "url_descarga": quote(nombre) 
            })
    return lista


def obtener_arbol_recursivo(ruta_base, ruta_relativa=""):
    estructura = {
        "nombre": os.path.basename(ruta_base),
        "ruta_relativa": ruta_relativa,
        "archivos": [],
        "subcarpetas": []
    }

    if os.path.exists(ruta_base):
        try:
            items = natsorted(os.listdir(ruta_base))
            for item in items:
                ruta_completa = os.path.join(ruta_base, item)
                nueva_relativa = os.path.join(ruta_relativa, item) if ruta_relativa else item

                if os.path.isdir(ruta_completa):
                    estructura["subcarpetas"].append(
                        obtener_arbol_recursivo(ruta_completa, nueva_relativa)
                    )
                elif os.path.isfile(ruta_completa):
                    estructura["archivos"].append({
                        "nombre": item,
                        "tamano": formatear_tamano(os.path.getsize(ruta_completa)),
                        "url_descarga": quote(nueva_relativa.replace("\\", "/"))
                    })
        except PermissionError:
            pass # Ignoramos carpetas sin acceso
            
    return estructura

def obtener_lista_plana_carpetas(path_base):
    """Devuelve una lista plana de todas las carpetas para el <select> del frontend."""
    lista = ["."]
    if os.path.exists(path_base):
        for root, dirs, _ in os.walk(path_base):
            dirs.sort() # Orden alfabético simple para os.walk
            relative_root = os.path.relpath(root, path_base)
            
            for d in dirs:
                full_rel = os.path.join(relative_root, d)
                if full_rel != ".":
                    clean = full_rel.replace("\\", "/")
                    if clean.startswith("./"): clean = clean[2:]
                    lista.append(clean)
    return natsorted(lista)

def generar_nombre_unico(base_path, filename):
    nombre, extension = os.path.splitext(filename)
    contador = 1
    nuevo_filename = filename
    ruta_final = os.path.join(base_path, nuevo_filename)
    
    while os.path.exists(ruta_final):
        nuevo_filename = f"{nombre}({contador}){extension}"
        ruta_final = os.path.join(base_path, nuevo_filename)
        contador += 1
    
    return nuevo_filename, ruta_final

# ==========================================
# 5. ENDPOINTS PRINCIPALES (HOME & DELETE)
# ==========================================

@app.get("/")
def home(request: Request):
    used, free, percent = obtener_uso_disco()
    inbox_files = listar_archivos_inbox()
    tree = obtener_arbol_recursivo(FILES_DIR)

    return templates.TemplateResponse("index.html", {
        "request": request,
        "espacio_usado": used,
        "espacio_libre": free,
        "porcentaje": percent,
        "archivos_inbox": inbox_files,
        "arbol_archivos": tree["subcarpetas"]
    })

# ==========================================
# ENDPOINT UNIFICADO DE BORRADO
# ==========================================

@app.delete("/delete/{zone}/{filepath:path}")
def delete_item(zone: str, filepath: str):

    if zone == "inbox":
        base_dir = INBOX_DIR
    elif zone == "catalog":
        base_dir = FILES_DIR
    else:
        raise HTTPException(status_code=400, detail="Zona de borrado inválida")

    try:
        filepath = unquote(filepath)
        path = sanitizar_ruta_entrada(filepath, base_dir)
        
        if os.path.exists(path) and os.path.isfile(path):
            os.remove(path)
            return {"info": f"Archivo eliminado de {zone}"}
        
        raise HTTPException(status_code=404, detail="El archivo no existe")
        
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Error al borrar: {str(e)}")

# ==========================================
# 6. GESTIÓN DE SUBIDAS (CHUNKED UPLOAD)
# ==========================================

@app.get("/upload_status")
def get_upload_status(filename: str):
    """Verifica si hay una subida a medias (.part) y devuelve el tamaño actual."""
    filename = os.path.basename(filename) # Seguridad básica
    ruta_parcial = sanitizar_ruta_entrada(f"{filename}.part", INBOX_DIR)
    
    if os.path.exists(ruta_parcial):
        return {"offset": os.path.getsize(ruta_parcial)}
    return {"offset": 0}

@app.post("/upload_chunk")
def upload_chunk(
    file: UploadFile = File(...), 
    filename: str = Form(...), 
    chunk_offset: int = Form(...)
):

    filename = os.path.basename(filename)
    ruta_parcial = os.path.join(INBOX_DIR, f"{filename}.part")

    try:
        with open(ruta_parcial, 'ab', buffering=16 * 1024 * 1024) as f:
            shutil.copyfileobj(file.file, f, length=16 * 1024 * 1024)
        return {"received": "ok"}
    except Exception as e:
        print(f"[ERROR] Fallo escribiendo {filename}: {e}") # Print error
        raise HTTPException(status_code=500, detail=f"Error I/O: {str(e)}")
    finally:
        file.file.close()

@app.post("/upload_finish")
def finish_upload(
    filename: str = Form(...), 
    action: str = Form("check") 
):

    filename = os.path.basename(filename)
    ruta_parcial = os.path.join(INBOX_DIR, f"{filename}.part")
    ruta_final = sanitizar_ruta_entrada(filename, INBOX_DIR)

    if not os.path.exists(ruta_parcial):
        raise HTTPException(status_code=404, detail="Archivo parcial no encontrado")

    # Gestión de Conflictos
    if os.path.exists(ruta_final):
        if action == "check":
            raise HTTPException(status_code=409, detail="El archivo ya existe")
        
        elif action == "rename":
            nuevo_nombre, nueva_ruta = generar_nombre_unico(INBOX_DIR, filename)
            filename = nuevo_nombre
            ruta_final = nueva_ruta
            
        elif action == "overwrite":
            os.remove(ruta_final)

    try:
        os.rename(ruta_parcial, ruta_final)
        return {"info": f"Completado: {filename}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al finalizar: {str(e)}")
    
# ==========================================
# 7. GESTIÓN DE CARPETAS Y MOVIMIENTOS
# ==========================================

class FolderSchema(BaseModel):
    folder_name: str

@app.post("/create-folder")
def create_folder(folder: FolderSchema):
    try:
        new_path = sanitizar_ruta_entrada(folder.folder_name, FILES_DIR)
        if not os.path.exists(new_path):
            os.makedirs(new_path)
            return {"info": "Carpeta creada"}
        return {"error": "La carpeta ya existe"}
    except Exception as e:
        return {"error": str(e)}

@app.get("/all-folders")
def get_all_folders():
    return {"folders": obtener_lista_plana_carpetas(FILES_DIR)}

@app.get("/scan-folders/{filename}")
def scan_folders(filename: str):
    folders = obtener_lista_plana_carpetas(FILES_DIR)
    
    # Heurística simple para sugerir carpeta
    ext = filename.split('.')[-1].lower() if '.' in filename else ""
    sugerencia = "."
    
    if ext in ['jpg', 'png', 'jpeg', 'gif', 'webp', 'svg']:
        sugerencia = "Imagenes"
    elif ext in ['pdf', 'doc', 'docx', 'txt', 'xls', 'xlsx']:
        sugerencia = "Documentos"
    elif ext in ['mp4', 'mkv', 'avi', 'mov']:
        sugerencia = "Videos"
    elif ext in ['py', 'js', 'html', 'css', 'json']:
        sugerencia = "Programacion"
        
    return {"folders": folders, "suggested": sugerencia}

class MoveSchema(BaseModel):
    source_path: str
    source_zone: str
    destination_folder: str


class RenameSchema(BaseModel):
    zone: str
    item_path: str
    new_name: str

def move_file_sync(src, dst):
    shutil.move(src, dst)

@app.post("/move")
async def move_file(data: MoveSchema):
    """
    Mueve archivos de forma explícita según la zona de origen.
    """
    try:
        source_clean = unquote(data.source_path)
        dest_clean = unquote(data.destination_folder)
        
        # 1. Determinar ORIGEN exacto según la zona
        if data.source_zone == "inbox":
            path_origen_final = sanitizar_ruta_entrada(source_clean, INBOX_DIR)
        elif data.source_zone == "catalog":
            path_origen_final = sanitizar_ruta_entrada(source_clean, FILES_DIR)
        else:
            return {"error": "Zona de origen desconocida"}

        # Verificar existencia
        if not os.path.isfile(path_origen_final):
            return {"error": f"El archivo origen no existe en {data.source_zone}"}

        # 2. Determinar DESTINO (Igual que antes)
        if dest_clean == ".":
            path_destino_folder = FILES_DIR
        else:
            path_destino_folder = sanitizar_ruta_entrada(dest_clean, FILES_DIR)
            
        if not os.path.exists(path_destino_folder):
            os.makedirs(path_destino_folder, exist_ok=True)

        nombre_archivo = os.path.basename(path_origen_final)
        path_destino_final = os.path.join(path_destino_folder, nombre_archivo)

        # 3. Evitar sobreescribir
        if os.path.exists(path_destino_final):
             return {"error": "El archivo ya existe en la carpeta destino"}

        # 4. Mover
        await asyncio.to_thread(move_file_sync, path_origen_final, path_destino_final)
        
        return {"info": f"Movido a {dest_clean}"}

    except Exception as e:
        return {"error": f"Error al mover: {str(e)}"}


@app.post("/rename")
def rename_item(data: RenameSchema):
    try:
        if data.zone not in ["catalog", "folder"]:
            raise HTTPException(status_code=400, detail="Zona inválida")

        clean_path = unquote(data.item_path).strip()
        new_name = data.new_name.strip()

        if not new_name:
            raise HTTPException(status_code=400, detail="El nuevo nombre es obligatorio")

        if "/" in new_name or "\\" in new_name:
            raise HTTPException(status_code=400, detail="Nombre inválido")

        source_path = sanitizar_ruta_entrada(clean_path, FILES_DIR)

        if not os.path.exists(source_path):
            raise HTTPException(status_code=404, detail="Elemento no encontrado")

        if data.zone == "folder" and not os.path.isdir(source_path):
            raise HTTPException(status_code=400, detail="La ruta no es una carpeta")

        if data.zone == "catalog" and not os.path.isfile(source_path):
            raise HTTPException(status_code=400, detail="La ruta no es un archivo")

        parent_dir = os.path.dirname(source_path)
        target_path = os.path.join(parent_dir, new_name)
        target_rel = os.path.relpath(target_path, FILES_DIR)
        safe_target = sanitizar_ruta_entrada(target_rel, FILES_DIR)

        if os.path.exists(safe_target):
            raise HTTPException(status_code=409, detail="Ya existe un elemento con ese nombre")

        os.rename(source_path, safe_target)
        new_relative = os.path.relpath(safe_target, FILES_DIR).replace("\\", "/")
        return {"info": "Renombrado correctamente", "new_path": new_relative}

    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Error al renombrar: {str(e)}")

# ==========================================
# GESTIÓN AVANZADA DE CARPETAS (ZIP & BORRAR)
# ==========================================

# 1. BORRAR CARPETA VACÍA
@app.delete("/delete-folder/{path:path}")
def delete_folder(path: str):
    try:
        clean_path = unquote(path)
        full_path = sanitizar_ruta_entrada(clean_path, FILES_DIR)
        
        # Seguridad: No borrar la raíz
        if full_path == FILES_DIR:
             raise HTTPException(status_code=403, detail="No se puede borrar la raíz")

        if os.path.exists(full_path) and os.path.isdir(full_path):
            try:
                # CAMBIO: os.rmdir solo funciona si la carpeta está vacía
                os.rmdir(full_path) 
                return {"info": "Carpeta eliminada"}
            except OSError:
                # Si salta error, es que tiene cosas dentro
                raise HTTPException(status_code=409, detail="La carpeta NO está vacía.")
        
        raise HTTPException(status_code=404, detail="Carpeta no encontrada")
    except Exception as e:
        if isinstance(e, HTTPException): raise e
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

# 2. DESCARGAR CARPETA COMO ZIP
def remove_file(path: str):
    try:
        os.remove(path)
    except Exception:
        pass

@app.get("/download-folder/{path:path}")
def download_folder_zip(path: str, background_tasks: BackgroundTasks):
    try:
        clean_path = unquote(path)
        full_path = sanitizar_ruta_entrada(clean_path, FILES_DIR)
        folder_name = os.path.basename(full_path)
        
        if not os.path.isdir(full_path):
            raise HTTPException(status_code=404, detail="Carpeta no encontrada")

        # Zip temporal en /tmp
        zip_filename = f"{folder_name}.zip"
        zip_path = os.path.join("/tmp", zip_filename)
        
        # Crear ZIP (shutil lo hace nativo)
        shutil.make_archive(zip_path.replace('.zip', ''), 'zip', full_path)
        
        # Programar borrado automático al terminar
        background_tasks.add_task(remove_file, zip_path)
        
        return FileResponse(zip_path, media_type='application/zip', filename=zip_filename)
    except Exception as e:
        print(f"Error ZIP: {e}")
        raise HTTPException(status_code=500, detail="Error creando ZIP")

@app.get("/tree-html")
def get_tree_html(request: Request):
    tree = obtener_arbol_recursivo(FILES_DIR)
    return templates.TemplateResponse("tree_fragment.html", {
        "request": request,
        "arbol_archivos": tree["subcarpetas"]
    })