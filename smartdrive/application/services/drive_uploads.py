import os

from fastapi import HTTPException, UploadFile

from smartdrive.infrastructure.file_ops import delete_file, path_exists, rename_path
from smartdrive.infrastructure.logging import get_logger
from smartdrive.infrastructure.settings import INBOX_DIR
from smartdrive.infrastructure.storage import generate_unique_name, sanitize_input_path
from smartdrive.infrastructure.uploads import write_upload_chunk

logger = get_logger(__name__)


def get_upload_status(filename: str) -> dict:
    safe_filename = os.path.basename(filename)
    partial_path = sanitize_input_path(f"{safe_filename}.part", INBOX_DIR)

    if path_exists(partial_path):
        return {"offset": os.path.getsize(partial_path)}
    return {"offset": 0}


def upload_chunk(file: UploadFile, filename: str, chunk_offset: int) -> dict:
    if chunk_offset < 0:
        raise HTTPException(status_code=400, detail="chunk_offset inválido")

    safe_filename = os.path.basename(filename)
    partial_path = sanitize_input_path(f"{safe_filename}.part", INBOX_DIR)

    expected_offset = os.path.getsize(partial_path) if path_exists(partial_path) else 0
    if chunk_offset != expected_offset:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "chunk_offset desincronizado",
                "expected_offset": expected_offset,
            },
        )

    try:
        write_upload_chunk(file, partial_path)
        next_offset = os.path.getsize(partial_path)
        return {"received": "ok", "next_offset": next_offset}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Fallo escribiendo chunk. filename=%s", safe_filename)
        raise HTTPException(status_code=500, detail=f"Error I/O: {str(exc)}")
    finally:
        file.file.close()


def finish_upload(filename: str, action: str = "check") -> dict:
    safe_filename = os.path.basename(filename)
    partial_path = os.path.join(INBOX_DIR, f"{safe_filename}.part")
    final_path = sanitize_input_path(safe_filename, INBOX_DIR)

    if not path_exists(partial_path):
        raise HTTPException(status_code=404, detail="Archivo parcial no encontrado")

    if path_exists(final_path):
        if action == "check":
            raise HTTPException(status_code=409, detail="El archivo ya existe")
        if action == "rename":
            new_name, new_path = generate_unique_name(INBOX_DIR, safe_filename)
            safe_filename = new_name
            final_path = new_path
        elif action == "overwrite":
            delete_file(final_path)

    try:
        rename_path(partial_path, final_path)
        return {"info": f"Completado: {safe_filename}"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error al finalizar: {str(exc)}")
