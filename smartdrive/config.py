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
