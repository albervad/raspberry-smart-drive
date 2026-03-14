from os.path import basename
from urllib.parse import unquote

from fastapi import APIRouter, Request, File, UploadFile, Form, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse

from smartdrive.application.services.access_control_service import track_user_action
from smartdrive.application.services.drive_commands import (
    create_folder as create_folder_command,
    delete_folder as delete_folder_command,
    delete_item as delete_item_command,
    move_file as move_file_command,
    prepare_folder_zip as prepare_folder_zip_command,
    rename_item as rename_item_command,
    save_clipboard as save_clipboard_command,
)
from smartdrive.application.services.drive_queries import (
    get_drive_home_context as get_drive_home_context_query,
    get_shared_clipboard as get_shared_clipboard_query,
    get_tree_context as get_tree_context_query,
    list_all_folders as list_all_folders_query,
    scan_folders as scan_folders_query,
    search_drive_files as search_drive_files_query,
)
from smartdrive.application.services.drive_uploads import (
    finish_upload as finish_upload_command,
    get_upload_status as get_upload_status_query,
    upload_chunk as upload_chunk_command,
)
from smartdrive.infrastructure.file_ops import is_file, safe_remove_file
from smartdrive.infrastructure.settings import FILES_DIR, INBOX_DIR
from smartdrive.infrastructure.storage import sanitize_input_path
from smartdrive.infrastructure.templates import templates
from smartdrive.presentation.schemas import FolderSchema, MoveSchema, ClipboardSchema, RenameSchema


router = APIRouter(prefix="/drive")


def _audit(request: Request, action: str, status: str = "ok", details: dict | None = None) -> None:
    visitor_id = getattr(request.state, "visitor_id", None)
    track_user_action(
        visitor_id=visitor_id,
        action=action,
        path=request.url.path,
        details=details,
        status=status,
    )


def _base_dir_for_zone(zone: str) -> str:
    if zone == "inbox":
        return INBOX_DIR
    if zone == "catalog":
        return FILES_DIR
    raise HTTPException(status_code=400, detail="Zona invalida")


def _resolve_file_path(zone: str, filepath: str) -> str:
    base_dir = _base_dir_for_zone(zone)
    safe_path = sanitize_input_path(unquote(filepath), base_dir)

    if not is_file(safe_path):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    return safe_path


@router.get("/")
def drive_home(request: Request):
    context = get_drive_home_context_query()
    context["request"] = request
    _audit(request, "drive_view")
    return templates.TemplateResponse("index.html", context)


@router.get("/search")
def search_files(request: Request, q: str = "", mode: str = "both"):
    result = search_drive_files_query(q=q, mode=mode)
    if q.strip():
        _audit(
            request,
            "search_files",
            details={"query": q.strip()[:120], "mode": mode, "total": result.get("total", 0)},
        )
    return result


@router.get("/open/{zone}/{filepath:path}")
def open_file(request: Request, zone: str, filepath: str):
    safe_path = _resolve_file_path(zone, filepath)
    _audit(request, "open_file", details={"zone": zone, "filepath": unquote(filepath)})
    return FileResponse(
        safe_path,
        filename=basename(safe_path),
        content_disposition_type="inline",
    )


@router.get("/download/{zone}/{filepath:path}")
def download_file(request: Request, zone: str, filepath: str):
    safe_path = _resolve_file_path(zone, filepath)
    _audit(request, "download_file", details={"zone": zone, "filepath": unquote(filepath)})
    return FileResponse(safe_path, filename=basename(safe_path))


@router.delete("/delete/{zone}/{filepath:path}")
def delete_item(request: Request, zone: str, filepath: str):
    try:
        result = delete_item_command(zone, filepath)
        _audit(request, "delete_item", details={"zone": zone, "filepath": filepath})
        return result
    except HTTPException as exc:
        _audit(
            request,
            "delete_item",
            status="error",
            details={"zone": zone, "filepath": filepath, "error": str(exc.detail)},
        )
        raise


@router.get("/upload_status")
def get_upload_status(filename: str):
    return get_upload_status_query(filename)


@router.post("/upload_chunk")
def upload_chunk(
    file: UploadFile = File(...),
    filename: str = Form(...),
    chunk_offset: int = Form(...),
):
    return upload_chunk_command(file=file, filename=filename, chunk_offset=chunk_offset)


@router.post("/upload_finish")
def finish_upload(
    request: Request,
    filename: str = Form(...),
    action: str = Form("check"),
):
    try:
        result = finish_upload_command(filename=filename, action=action)
        _audit(
            request,
            "finish_upload",
            details={"filename": filename, "action": action, "result": result.get("info", "")},
        )
        return result
    except HTTPException as exc:
        _audit(
            request,
            "finish_upload",
            status="error",
            details={"filename": filename, "action": action, "error": str(exc.detail)},
        )
        raise


@router.post("/create-folder")
def create_folder(request: Request, folder: FolderSchema):
    result = create_folder_command(folder.folder_name)
    status = "error" if "error" in result else "ok"
    _audit(
        request,
        "create_folder",
        status=status,
        details={"folder_name": folder.folder_name, "result": result.get("info") or result.get("error")},
    )
    return result


@router.get("/all-folders")
def get_all_folders():
    return list_all_folders_query()


@router.get("/scan-folders/{filename}")
def scan_folders(filename: str):
    return scan_folders_query(filename)


@router.post("/move")
async def move_file(request: Request, data: MoveSchema):
    result = await move_file_command(data)
    status = "error" if "error" in result else "ok"
    _audit(
        request,
        "move_file",
        status=status,
        details={
            "source_zone": data.source_zone,
            "source_path": data.source_path,
            "destination_folder": data.destination_folder,
            "result": result.get("info") or result.get("error"),
        },
    )
    return result


@router.post("/rename")
def rename_item(request: Request, data: RenameSchema):
    try:
        result = rename_item_command(data)
        _audit(
            request,
            "rename_item",
            details={
                "zone": data.zone,
                "item_path": data.item_path,
                "new_name": data.new_name,
                "result": result.get("info", ""),
            },
        )
        return result
    except HTTPException as exc:
        _audit(
            request,
            "rename_item",
            status="error",
            details={
                "zone": data.zone,
                "item_path": data.item_path,
                "new_name": data.new_name,
                "error": str(exc.detail),
            },
        )
        raise


@router.get("/clipboard")
def get_shared_clipboard(request: Request):
    result = get_shared_clipboard_query()
    _audit(request, "read_clipboard", details={"text_length": len(result.get("text", ""))})
    return result


@router.post("/clipboard")
def set_shared_clipboard(request: Request, payload: ClipboardSchema):
    try:
        result = save_clipboard_command(payload.text)
        _audit(
            request,
            "save_clipboard",
            details={"text_length": len(payload.text)},
        )
        return result
    except HTTPException as exc:
        _audit(
            request,
            "save_clipboard",
            status="error",
            details={"text_length": len(payload.text), "error": str(exc.detail)},
        )
        raise


@router.delete("/delete-folder/{path:path}")
def delete_folder(request: Request, path: str):
    try:
        result = delete_folder_command(path)
        _audit(request, "delete_folder", details={"path": path})
        return result
    except HTTPException as exc:
        _audit(
            request,
            "delete_folder",
            status="error",
            details={"path": path, "error": str(exc.detail)},
        )
        raise


@router.get("/download-folder/{path:path}")
def download_folder_zip(request: Request, path: str, background_tasks: BackgroundTasks):
    try:
        zip_path, zip_filename = prepare_folder_zip_command(path)
        background_tasks.add_task(safe_remove_file, zip_path)
        _audit(request, "download_folder_zip", details={"path": path, "zip_filename": zip_filename})
        return FileResponse(zip_path, media_type="application/zip", filename=zip_filename)
    except HTTPException as exc:
        _audit(
            request,
            "download_folder_zip",
            status="error",
            details={"path": path, "error": str(exc.detail)},
        )
        raise
    except Exception as exc:
        _audit(
            request,
            "download_folder_zip",
            status="error",
            details={"path": path, "error": str(exc)},
        )
        raise HTTPException(status_code=500, detail="Error creando ZIP")


@router.get("/tree-html")
def get_tree_html(request: Request):
    context = get_tree_context_query()
    context["request"] = request
    return templates.TemplateResponse("tree_fragment.html", context)
