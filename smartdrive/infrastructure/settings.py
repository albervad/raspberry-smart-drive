import os

BASE_MOUNT = os.path.abspath(os.getenv("SMARTDRIVE_BASE_MOUNT", "/mnt/midrive"))
INBOX_DIR = os.path.join(BASE_MOUNT, "inbox")
FILES_DIR = os.path.join(BASE_MOUNT, "files")
SMARTDRIVE_AUDIT_DIR = os.path.abspath(
    os.getenv("SMARTDRIVE_AUDIT_DIR", os.path.join(os.getcwd(), ".smartdrive_audit"))
)

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


def _as_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return default


def _as_csv_set(value: str | None, default: set[str] | None = None) -> set[str]:
    if value is None:
        return set(default or set())

    parsed = {item.strip() for item in value.split(",") if item.strip()}
    return parsed or set(default or set())


SMARTDRIVE_DEBUG = _as_bool(os.getenv("SMARTDRIVE_DEBUG"), default=False)
SMARTDRIVE_REQUEST_LOGGING = _as_bool(
    os.getenv("SMARTDRIVE_REQUEST_LOGGING"),
    default=SMARTDRIVE_DEBUG,
)
SMARTDRIVE_LOG_LEVEL = os.getenv(
    "SMARTDRIVE_LOG_LEVEL",
    "DEBUG" if SMARTDRIVE_DEBUG else "INFO",
).upper()

SMARTDRIVE_OWNER_IPS = _as_csv_set(
    os.getenv("SMARTDRIVE_OWNER_IPS"),
    default={"127.0.0.1", "::1"},
)
SMARTDRIVE_TRUST_PROXY_HEADERS = _as_bool(
    os.getenv("SMARTDRIVE_TRUST_PROXY_HEADERS"),
    default=False,
)
SMARTDRIVE_TRUSTED_PROXY_IPS = _as_csv_set(
    os.getenv("SMARTDRIVE_TRUSTED_PROXY_IPS"),
    default={"127.0.0.1", "::1"},
)
SMARTDRIVE_AUDIT_MAX_EVENTS = _as_int(os.getenv("SMARTDRIVE_AUDIT_MAX_EVENTS"), default=5000)
SMARTDRIVE_AUDIT_RECENT_LIMIT = _as_int(os.getenv("SMARTDRIVE_AUDIT_RECENT_LIMIT"), default=200)
SMARTDRIVE_NEW_VISITOR_WINDOW_HOURS = _as_int(
    os.getenv("SMARTDRIVE_NEW_VISITOR_WINDOW_HOURS"),
    default=24,
)
