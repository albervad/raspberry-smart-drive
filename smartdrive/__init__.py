from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from smartdrive.infrastructure.http_logging import setup_request_logging
from smartdrive.infrastructure.logging import configure_logging, get_logger
from smartdrive.infrastructure.runtime import app_lifespan
from smartdrive.infrastructure.settings import (
    FILES_DIR,
    INBOX_DIR,
    SMARTDRIVE_DEBUG,
    SMARTDRIVE_REQUEST_LOGGING,
)
from smartdrive.presentation.routers.drive_router import router as drive_router
from smartdrive.presentation.routers.portfolio_router import router as portfolio_router


def create_app() -> FastAPI:
    configure_logging()
    logger = get_logger("app")

    app = FastAPI(
        lifespan=app_lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    setup_request_logging(app, enabled=SMARTDRIVE_REQUEST_LOGGING)

    app.mount("/drive/inbox", StaticFiles(directory=INBOX_DIR, check_dir=False), name="drive-inbox")
    app.mount("/drive/files", StaticFiles(directory=FILES_DIR, check_dir=False), name="drive-files")
    app.mount("/static", StaticFiles(directory="static"), name="static")

    app.include_router(portfolio_router)
    app.include_router(drive_router)

    logger.info(
        "Smart Drive app initialized (debug=%s, request_logging=%s)",
        SMARTDRIVE_DEBUG,
        SMARTDRIVE_REQUEST_LOGGING,
    )
    return app
