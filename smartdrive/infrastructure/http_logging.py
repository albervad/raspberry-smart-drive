import time
import uuid

from fastapi import FastAPI, Request

from smartdrive.infrastructure.logging import get_logger


def setup_request_logging(app: FastAPI, enabled: bool) -> None:
	if not enabled:
		return

	logger = get_logger("http")

	@app.middleware("http")
	async def request_logger(request: Request, call_next):
		request_id = uuid.uuid4().hex[:8]
		start_time = time.perf_counter()

		client_host = request.client.host if request.client else "-"
		logger.debug(
			"[%s] -> %s %s from %s",
			request_id,
			request.method,
			request.url.path,
			client_host,
		)

		try:
			response = await call_next(request)
		except Exception:
			duration_ms = (time.perf_counter() - start_time) * 1000
			logger.exception(
				"[%s] !! %s %s failed in %.2fms",
				request_id,
				request.method,
				request.url.path,
				duration_ms,
			)
			raise

		duration_ms = (time.perf_counter() - start_time) * 1000
		logger.info(
			"[%s] <- %s %s %s in %.2fms",
			request_id,
			request.method,
			request.url.path,
			response.status_code,
			duration_ms,
		)
		response.headers["X-Request-ID"] = request_id
		return response
