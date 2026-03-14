import os
from urllib.parse import quote

from fastapi import HTTPException
from natsort import natsorted

from smartdrive.infrastructure.logging import get_logger
from smartdrive.infrastructure.settings import BASE_MOUNT, INBOX_DIR


logger = get_logger("storage")


def sanitize_input_path(user_input: str, base_dir: str) -> str:
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
        logger.warning("Path traversal blocked. user_input=%s base_dir=%s", user_input, base_dir)
        raise HTTPException(status_code=403, detail=f"Forbidden: Acceso denegado a {user_input}")
    return safe_path


def format_size(size: int | float) -> str:
    current_size = float(size)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if current_size < 1024:
            return f"{current_size:.2f} {unit}"
        current_size /= 1024
    return f"{current_size:.2f} PB"


def get_disk_usage() -> tuple[str, str, str]:
    try:
        if not os.path.exists(BASE_MOUNT):
            return "0 B", "0 B", "0"

        import shutil

        total, used, free = shutil.disk_usage(BASE_MOUNT)
        return format_size(used), format_size(free), f"{(used / total) * 100:.1f}"
    except Exception:
        return "Error", "Error", "0"


def list_inbox_files() -> list[dict]:
    if not os.path.exists(INBOX_DIR):
        logger.debug("Inbox directory not found: %s", INBOX_DIR)
        return []

    file_names = natsorted(os.listdir(INBOX_DIR))
    files = []
    skipped_partial_files = 0

    for file_name in file_names:
        file_path = os.path.join(INBOX_DIR, file_name)
        if os.path.isfile(file_path):
            if file_name.endswith(".part"):
                skipped_partial_files += 1
                continue

            files.append({
                "name": file_name,
                "size": format_size(os.path.getsize(file_path)),
                "encoded_url": quote(file_name),
                "download_url": quote(file_name),
            })

    logger.debug(
        "Loaded inbox file list. files=%s skipped_partial=%s",
        len(files),
        skipped_partial_files,
    )
    return files


def build_recursive_tree(base_path: str, relative_path: str = "") -> dict:
    tree = {
        "name": os.path.basename(base_path),
        "relative_path": relative_path,
        "files": [],
        "subfolders": [],
    }

    if os.path.exists(base_path):
        try:
            items = natsorted(os.listdir(base_path))
            for item in items:
                full_path = os.path.join(base_path, item)
                next_relative_path = os.path.join(relative_path, item) if relative_path else item

                if os.path.isdir(full_path):
                    tree["subfolders"].append(
                        build_recursive_tree(full_path, next_relative_path)
                    )
                elif os.path.isfile(full_path):
                    tree["files"].append({
                        "name": item,
                        "size": format_size(os.path.getsize(full_path)),
                        "download_url": quote(next_relative_path.replace("\\", "/")),
                    })
        except PermissionError:
            pass

    return tree


def list_flat_folders(base_path: str) -> list[str]:
    folders = ["."]
    if os.path.exists(base_path):
        for root, dirs, _ in os.walk(base_path):
            dirs.sort()
            relative_root = os.path.relpath(root, base_path)

            for folder_name in dirs:
                relative_folder_path = os.path.join(relative_root, folder_name)
                if relative_folder_path != ".":
                    normalized_path = relative_folder_path.replace("\\", "/")
                    if normalized_path.startswith("./"):
                        normalized_path = normalized_path[2:]
                    folders.append(normalized_path)
    return natsorted(folders)


def generate_unique_name(base_path: str, filename: str) -> tuple[str, str]:
    stem, extension = os.path.splitext(filename)
    counter = 1
    unique_filename = filename
    final_path = os.path.join(base_path, unique_filename)

    while os.path.exists(final_path):
        unique_filename = f"{stem}({counter}){extension}"
        final_path = os.path.join(base_path, unique_filename)
        counter += 1

    return unique_filename, final_path
