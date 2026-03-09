import os
import re
import html
import json
import shutil
import zipfile
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import HTTPException
from natsort import natsorted

from smartdrive.config import (
    BASE_MOUNT,
    INBOX_DIR,
    FILES_DIR,
    WRITEUPS_MAX_ITEMS,
    WRITEUPS_MAX_TAGS,
    WRITEUPS_MAX_STEPS,
    CLIPBOARD_MAX_TEXT_CHARS,
    CLIPBOARD_MAX_FILE_BYTES,
    MAX_CONTENT_SEARCH_BYTES,
    MAX_SEARCH_RESULTS,
    MAX_EXTRACT_CHARS,
    CONTENT_SEARCH_EXTENSIONS,
)


def limitar_texto_seguro(value, max_len: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = value.replace("\x00", "").strip()
    if len(value) > max_len:
        return value[:max_len]
    return value


def normalizar_lista_texto(value, max_items: int, max_len: int):
    if not isinstance(value, list):
        return []

    normalizados = []
    for item in value[:max_items]:
        texto = limitar_texto_seguro(item, max_len)
        if texto:
            normalizados.append(texto)
    return normalizados


def normalizar_writeups_data(raw_data):
    if not isinstance(raw_data, list):
        return []

    writeups = []
    seen_ids = set()

    for row in raw_data[:WRITEUPS_MAX_ITEMS]:
        if not isinstance(row, dict):
            continue

        item_id = limitar_texto_seguro(row.get("id", ""), 80)
        machine = limitar_texto_seguro(row.get("machine", ""), 120)
        if not item_id or not machine:
            continue
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)

        writeups.append({
            "id": item_id,
            "machine": machine,
            "platform": limitar_texto_seguro(row.get("platform", "N/A"), 80),
            "difficulty": limitar_texto_seguro(row.get("difficulty", "N/A"), 40),
            "date": limitar_texto_seguro(row.get("date", "Sin fecha"), 40),
            "tags": normalizar_lista_texto(row.get("tags", []), WRITEUPS_MAX_TAGS, 40),
            "summary": limitar_texto_seguro(row.get("summary", "Sin resumen."), 1200),
            "steps": normalizar_lista_texto(row.get("steps", []), WRITEUPS_MAX_STEPS, 300),
            "mitigation": limitar_texto_seguro(row.get("mitigation", "Sin medidas definidas."), 1200)
        })

    return writeups


def obtener_ruta_portapapeles() -> str:
    if os.path.exists(BASE_MOUNT):
        return os.path.join(BASE_MOUNT, ".clipboard_shared.json")
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "data", "clipboard.json")


def normalizar_texto_portapapeles(value) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = value.replace("\x00", "")
    if len(value) > CLIPBOARD_MAX_TEXT_CHARS:
        return value[:CLIPBOARD_MAX_TEXT_CHARS]
    return value


def leer_portapapeles_compartido():
    path = obtener_ruta_portapapeles()
    default_payload = {"text": "", "updated_at": None}

    if not os.path.exists(path):
        return default_payload

    try:
        if os.path.getsize(path) > CLIPBOARD_MAX_FILE_BYTES:
            return default_payload

        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        if not isinstance(raw, dict):
            return default_payload

        return {
            "text": normalizar_texto_portapapeles(raw.get("text", "")),
            "updated_at": limitar_texto_seguro(raw.get("updated_at"), 80) or None
        }
    except Exception:
        return default_payload


def guardar_portapapeles_compartido(text: str):
    path = obtener_ruta_portapapeles()
    payload = {
        "text": normalizar_texto_portapapeles(text),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    return payload


def sanitizar_ruta_entrada(user_input: str, base_dir: str) -> str:
    if not user_input:
        return base_dir

    requested_path = os.path.join(base_dir, user_input)
    safe_path = os.path.realpath(requested_path)
    base_real = os.path.realpath(base_dir)

    try:
        in_jail = os.path.commonpath([safe_path, base_real]) == base_real
    except ValueError:
        in_jail = False

    if not in_jail:
        raise HTTPException(status_code=403, detail=f"Forbidden: Acceso denegado a {user_input}")
    return safe_path


def formatear_tamano(size: int | float) -> str:
    current_size = float(size)
    for unidad in ['B', 'KB', 'MB', 'GB', 'TB']:
        if current_size < 1024:
            return f"{current_size:.2f} {unidad}"
        current_size /= 1024
    return f"{current_size:.2f} PB"


def obtener_uso_disco():
    try:
        if not os.path.exists(BASE_MOUNT):
            return "0 B", "0 B", "0"

        total, used, free = shutil.disk_usage(BASE_MOUNT)
        return formatear_tamano(used), formatear_tamano(free), f"{(used / total) * 100:.1f}"
    except Exception:
        return "Error", "Error", "0"


def listar_archivos_inbox():
    if not os.path.exists(INBOX_DIR):
        return []

    archivos = natsorted(os.listdir(INBOX_DIR))
    lista = []

    for nombre in archivos:
        ruta = os.path.join(INBOX_DIR, nombre)
        if os.path.isfile(ruta):
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
            pass

    return estructura


def obtener_lista_plana_carpetas(path_base):
    lista = ["."]
    if os.path.exists(path_base):
        for root, dirs, _ in os.walk(path_base):
            dirs.sort()
            relative_root = os.path.relpath(root, path_base)

            for d in dirs:
                full_rel = os.path.join(relative_root, d)
                if full_rel != ".":
                    clean = full_rel.replace("\\", "/")
                    if clean.startswith("./"):
                        clean = clean[2:]
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


def ruta_real_en_base(path: str, base_dir: str) -> bool:
    try:
        base_real = os.path.realpath(base_dir)
        file_real = os.path.realpath(path)
        return os.path.commonpath([file_real, base_real]) == base_real
    except Exception:
        return False


def archivo_apto_para_busqueda_contenido(file_path: str) -> bool:
    extension = os.path.splitext(file_path)[1].lower()
    if extension not in CONTENT_SEARCH_EXTENSIONS:
        return False
    try:
        return os.path.getsize(file_path) <= MAX_CONTENT_SEARCH_BYTES
    except OSError:
        return False


def extraer_texto_plano(file_path: str) -> str:
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(MAX_EXTRACT_CHARS)
    except Exception:
        return ""


def extraer_texto_pdf(file_path: str) -> str:
    try:
        from pypdf import PdfReader
    except Exception:
        return ""

    try:
        reader = PdfReader(file_path)
        partes = []
        for page in reader.pages[:25]:
            texto = page.extract_text() or ""
            if texto:
                partes.append(texto)
            if sum(len(p) for p in partes) >= MAX_EXTRACT_CHARS:
                break
        return "\n".join(partes)[:MAX_EXTRACT_CHARS]
    except Exception:
        return ""


def extraer_texto_docx(file_path: str) -> str:
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            xml_data = []
            for name in zf.namelist():
                if name.startswith("word/") and name.endswith(".xml"):
                    try:
                        xml_data.append(zf.read(name).decode("utf-8", errors="ignore"))
                    except Exception:
                        continue
        if not xml_data:
            return ""
        text = " ".join(xml_data)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:MAX_EXTRACT_CHARS]
    except Exception:
        return ""


def extraer_texto_para_busqueda(file_path: str) -> str:
    extension = os.path.splitext(file_path)[1].lower()

    if extension in {
        ".txt", ".md", ".csv", ".json", ".log", ".ini", ".yaml", ".yml",
        ".xml", ".html", ".css", ".js", ".py", ".java", ".ts", ".tsx",
        ".jsx", ".sql", ".sh", ".conf", ".rtf"
    }:
        return extraer_texto_plano(file_path)

    if extension == ".pdf":
        return extraer_texto_pdf(file_path)

    if extension in {".docx", ".odt"}:
        return extraer_texto_docx(file_path)

    return ""


def extraer_fragmento_coincidente(file_path: str, query_lower: str) -> str:
    text = extraer_texto_para_busqueda(file_path)
    if not text:
        return ""

    text_lower = text.lower()
    idx = text_lower.find(query_lower)
    if idx == -1:
        return ""

    inicio = max(0, idx - 20)
    fin = min(len(text), idx + len(query_lower) + 20)
    return text[inicio:fin].strip()


def buscar_archivos(query: str, mode: str = "both"):
    query_lower = query.lower().strip()
    resultados = []

    buscar_nombre = mode in {"both", "name"}
    buscar_contenido = mode in {"both", "content"}

    if not query_lower:
        return resultados

    zonas = [("inbox", INBOX_DIR), ("catalog", FILES_DIR)]

    for zona, base_dir in zonas:
        if not os.path.exists(base_dir):
            continue

        for root, _, files in os.walk(base_dir):
            for nombre in files:
                if nombre.endswith(".part"):
                    continue

                ruta_absoluta = os.path.join(root, nombre)
                if os.path.islink(ruta_absoluta):
                    continue
                if not ruta_real_en_base(ruta_absoluta, base_dir):
                    continue
                ruta_relativa = os.path.relpath(ruta_absoluta, base_dir).replace("\\", "/")

                coincide_nombre = buscar_nombre and query_lower in nombre.lower()
                coincide_contenido = False
                fragmento = ""

                if buscar_contenido and archivo_apto_para_busqueda_contenido(ruta_absoluta):
                    fragmento = extraer_fragmento_coincidente(ruta_absoluta, query_lower)
                    coincide_contenido = bool(fragmento)

                if not coincide_nombre and not coincide_contenido:
                    continue

                url_encoded = quote(ruta_relativa)
                url_abrir = f"/drive/inbox/{url_encoded}" if zona == "inbox" else f"/drive/files/{url_encoded}"

                tipo_coincidencia = []
                if coincide_nombre:
                    tipo_coincidencia.append("nombre")
                if coincide_contenido:
                    tipo_coincidencia.append("contenido")

                resultados.append({
                    "zona": zona,
                    "nombre": nombre,
                    "ruta_relativa": ruta_relativa,
                    "tamano": formatear_tamano(os.path.getsize(ruta_absoluta)),
                    "url": url_abrir,
                    "coincidencia": " + ".join(tipo_coincidencia),
                    "fragmento": fragmento
                })

                if len(resultados) >= MAX_SEARCH_RESULTS:
                    return resultados

    return resultados


def move_file_sync(src, dst):
    shutil.move(src, dst)


def remove_file(path: str):
    try:
        os.remove(path)
    except Exception:
        pass
