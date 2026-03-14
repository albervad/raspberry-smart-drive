import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from smartdrive.infrastructure.logging import get_logger
from smartdrive.infrastructure.settings import INBOX_DIR, FILES_DIR


logger = get_logger("runtime")


def ensure_storage_folders() -> None:
    storage_paths = [INBOX_DIR, FILES_DIR]
    logger.info("Starting Smart Drive. Checking storage paths...")

    for storage_path in storage_paths:
        if not os.path.exists(storage_path):
            try:
                os.makedirs(storage_path, exist_ok=True)
                logger.info("Created storage path: %s", storage_path)
            except PermissionError:
                logger.error("Permission denied creating storage path: %s", storage_path)
        else:
            logger.debug("Detected existing storage path: %s", storage_path)


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    ensure_storage_folders()
    yield
    logger.info("Shutting down Smart Drive")
