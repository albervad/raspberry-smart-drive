import logging

from smartdrive.infrastructure.settings import SMARTDRIVE_LOG_LEVEL


_IS_CONFIGURED = False


def configure_logging() -> None:
    global _IS_CONFIGURED

    if _IS_CONFIGURED:
        return

    level = getattr(logging, SMARTDRIVE_LOG_LEVEL, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    _IS_CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"smartdrive.{name}")
