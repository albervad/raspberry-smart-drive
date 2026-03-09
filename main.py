import os
import json
import shutil
import asyncio
from contextlib import asynccontextmanager
from urllib.parse import unquote

from fastapi import FastAPI, Request, File, UploadFile, HTTPException, Form, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from smartdrive.config import (
    BASE_MOUNT,
    INBOX_DIR,
    FILES_DIR,
    WRITEUPS_MAX_FILE_BYTES,
)
from smartdrive.schemas import FolderSchema, MoveSchema, ClipboardSchema, RenameSchema
from smartdrive.helpers import (
    normalizar_writeups_data,
    leer_portapapeles_compartido,
    guardar_portapapeles_compartido,
    sanitizar_ruta_entrada,
    obtener_uso_disco,
    listar_archivos_inbox,
    obtener_arbol_recursivo,
    obtener_lista_plana_carpetas,
    generar_nombre_unico,
    buscar_archivos,
    move_file_sync,
    remove_file,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    carpetas = [INBOX_DIR, FILES_DIR]
    print("--> Iniciando Smart Drive. Verificando rutas...")

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


app = FastAPI(lifespan=lifespan)

if os.path.exists(BASE_MOUNT):
    app.mount("/data", StaticFiles(directory=BASE_MOUNT), name="datos")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


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


@app.get("/portfolio")
def portfolio(request: Request):
    writeups_path = os.path.join(os.path.dirname(__file__), "static", "data", "writeups.json")
    writeups_data = []

    try:
        if os.path.getsize(writeups_path) > WRITEUPS_MAX_FILE_BYTES:
            raise ValueError("writeups.json demasiado grande")

        with open(writeups_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            writeups_data = normalizar_writeups_data(data)
    except Exception:
        writeups_data = []

    return templates.TemplateResponse("portfolio.html", {
        "request": request,
        "writeups_data": writeups_data
    })


@app.get("/search")
def search_files(q: str = "", mode: str = "both"):
    query = q.strip()
    search_mode = mode.strip().lower()

    if search_mode not in {"both", "name", "content"}:
        raise HTTPException(status_code=400, detail="Modo de búsqueda inválido")
    if len(query) > 120:
        raise HTTPException(status_code=400, detail="Consulta demasiado larga")
    if len(query) < 2:
        return {"results": [], "total": 0}

    results = buscar_archivos(query, mode=search_mode)
    return {"results": results, "total": len(results)}


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


@app.get("/upload_status")
def get_upload_status(filename: str):
    filename = os.path.basename(filename)
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
        print(f"[ERROR] Fallo escribiendo {filename}: {e}")
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

    if os.path.exists(ruta_final):
        if action == "check":
            raise HTTPException(status_code=409, detail="El archivo ya existe")
        if action == "rename":
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


@app.post("/move")
async def move_file(data: MoveSchema):
    try:
        source_clean = unquote(data.source_path)
        dest_clean = unquote(data.destination_folder)

        if data.source_zone == "inbox":
            path_origen_final = sanitizar_ruta_entrada(source_clean, INBOX_DIR)
        elif data.source_zone == "catalog":
            path_origen_final = sanitizar_ruta_entrada(source_clean, FILES_DIR)
        else:
            return {"error": "Zona de origen desconocida"}

        if not os.path.isfile(path_origen_final):
            return {"error": f"El archivo origen no existe en {data.source_zone}"}

        if dest_clean == ".":
            path_destino_folder = FILES_DIR
        else:
            path_destino_folder = sanitizar_ruta_entrada(dest_clean, FILES_DIR)

        if not os.path.exists(path_destino_folder):
            os.makedirs(path_destino_folder, exist_ok=True)

        nombre_archivo = os.path.basename(path_origen_final)
        path_destino_final = os.path.join(path_destino_folder, nombre_archivo)

        if os.path.exists(path_destino_final):
            return {"error": "El archivo ya existe en la carpeta destino"}

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


@app.get("/clipboard")
def get_shared_clipboard():
    return leer_portapapeles_compartido()


@app.post("/clipboard")
def set_shared_clipboard(payload: ClipboardSchema):
    try:
        saved = guardar_portapapeles_compartido(payload.text)
        return saved
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo guardar el portapapeles: {str(e)}")


@app.delete("/delete-folder/{path:path}")
def delete_folder(path: str):
    try:
        clean_path = unquote(path)
        full_path = sanitizar_ruta_entrada(clean_path, FILES_DIR)

        if full_path == FILES_DIR:
            raise HTTPException(status_code=403, detail="No se puede borrar la raíz")

        if os.path.exists(full_path) and os.path.isdir(full_path):
            try:
                os.rmdir(full_path)
                return {"info": "Carpeta eliminada"}
            except OSError:
                raise HTTPException(status_code=409, detail="La carpeta NO está vacía.")

        raise HTTPException(status_code=404, detail="Carpeta no encontrada")
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/download-folder/{path:path}")
def download_folder_zip(path: str, background_tasks: BackgroundTasks):
    try:
        clean_path = unquote(path)
        full_path = sanitizar_ruta_entrada(clean_path, FILES_DIR)
        folder_name = os.path.basename(full_path)

        if not os.path.isdir(full_path):
            raise HTTPException(status_code=404, detail="Carpeta no encontrada")

        zip_filename = f"{folder_name}.zip"
        zip_path = os.path.join("/tmp", zip_filename)

        shutil.make_archive(zip_path.replace('.zip', ''), 'zip', full_path)
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
