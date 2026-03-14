import os

BASE_MOUNT = "/mnt/midrive"
INBOX_DIR = os.path.join(BASE_MOUNT, "inbox")
FILES_DIR = os.path.join(BASE_MOUNT, "files")

WRITEUPS_MAX_FILE_BYTES = 512 * 1024
WRITEUPS_MAX_ITEMS = 150
WRITEUPS_MAX_TAGS = 15
WRITEUPS_MAX_STEPS = 20

CLIPBOARD_MAX_TEXT_CHARS = 20000
CLIPBOARD_MAX_FILE_BYTES = 64 * 1024

MAX_CONTENT_SEARCH_BYTES = 8 * 1024 * 1024
MAX_SEARCH_RESULTS = 120
MAX_EXTRACT_CHARS = 150000
CONTENT_SEARCH_EXTENSIONS = {
    ".txt", ".md", ".csv", ".json", ".log", ".ini", ".yaml", ".yml",
    ".xml", ".html", ".css", ".js", ".py", ".java", ".ts", ".tsx",
    ".jsx", ".sql", ".sh", ".conf", ".rtf", ".pdf", ".docx", ".odt"
}


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


SMARTDRIVE_DEBUG = _as_bool(os.getenv("SMARTDRIVE_DEBUG"), default=False)
SMARTDRIVE_REQUEST_LOGGING = _as_bool(
    os.getenv("SMARTDRIVE_REQUEST_LOGGING"),
    default=SMARTDRIVE_DEBUG,
)
SMARTDRIVE_LOG_LEVEL = os.getenv(
    "SMARTDRIVE_LOG_LEVEL",
    "DEBUG" if SMARTDRIVE_DEBUG else "INFO",
).upper()
