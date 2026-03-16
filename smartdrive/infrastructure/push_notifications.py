import importlib
import json
import os
import threading
import time
import uuid
from collections import deque
from typing import Any

from smartdrive.infrastructure.logging import get_logger
from smartdrive.infrastructure.settings import (
    SMARTDRIVE_AUDIT_DIR,
    SMARTDRIVE_PUSH_DEFAULT_NOTIFY_RECURRENT_REQUESTS,
    SMARTDRIVE_PUSH_DEFAULT_NOTIFY_UNKNOWN_VISITORS,
    SMARTDRIVE_PUSH_DEFAULT_RECURRENT_COOLDOWN_SECONDS,
    SMARTDRIVE_PUSH_DEFAULT_RECURRENT_THRESHOLD,
    SMARTDRIVE_PUSH_DEFAULT_RECURRENT_WINDOW_SECONDS,
    SMARTDRIVE_WEBPUSH_PRIVATE_KEY,
    SMARTDRIVE_WEBPUSH_PUBLIC_KEY,
    SMARTDRIVE_WEBPUSH_SUBJECT,
)


logger = get_logger("push_notifications")

WebPushException = Exception
webpush = None

try:
    _pywebpush = importlib.import_module("pywebpush")
    WebPushException = getattr(_pywebpush, "WebPushException", Exception)
    webpush = getattr(_pywebpush, "webpush", None)

    _WEBPUSH_LIB_AVAILABLE = callable(webpush)
except Exception:  # pragma: no cover - optional dependency at runtime
    _WEBPUSH_LIB_AVAILABLE = False


SUBSCRIPTIONS_STORE_PATH = os.path.join(SMARTDRIVE_AUDIT_DIR, "push_subscriptions.json")
SETTINGS_STORE_PATH = os.path.join(SMARTDRIVE_AUDIT_DIR, "push_rules.json")
VISITOR_STORE_PATH = os.path.join(SMARTDRIVE_AUDIT_DIR, "visitor_registry.json")

_LOCK = threading.Lock()
_RATE_LOCK = threading.Lock()

_RECENT_REQUESTS: dict[str, deque[float]] = {}
_LAST_RECURRENT_ALERT_AT: dict[str, float] = {}


def _read_json(path: str, default: dict[str, Any]) -> dict[str, Any]:
    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as file_handle:
            return json.load(file_handle)
    except (json.JSONDecodeError, OSError):
        logger.warning("Invalid push JSON store detected. Resetting file=%s", path)
        return default


def _write_json(path: str, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as file_handle:
        json.dump(data, file_handle, ensure_ascii=False, indent=2)


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _default_rules() -> dict[str, Any]:
    return {
        "notify_unknown_visitors": SMARTDRIVE_PUSH_DEFAULT_NOTIFY_UNKNOWN_VISITORS,
        "notify_recurrent_requests": SMARTDRIVE_PUSH_DEFAULT_NOTIFY_RECURRENT_REQUESTS,
        "recurrent_threshold": _coerce_int(
            SMARTDRIVE_PUSH_DEFAULT_RECURRENT_THRESHOLD,
            default=25,
            minimum=5,
            maximum=500,
        ),
        "recurrent_window_seconds": _coerce_int(
            SMARTDRIVE_PUSH_DEFAULT_RECURRENT_WINDOW_SECONDS,
            default=120,
            minimum=10,
            maximum=3600,
        ),
        "recurrent_cooldown_seconds": _coerce_int(
            SMARTDRIVE_PUSH_DEFAULT_RECURRENT_COOLDOWN_SECONDS,
            default=900,
            minimum=30,
            maximum=86400,
        ),
    }


def ensure_push_storage() -> None:
    os.makedirs(SMARTDRIVE_AUDIT_DIR, exist_ok=True)

    with _LOCK:
        if not os.path.exists(SUBSCRIPTIONS_STORE_PATH):
            _write_json(SUBSCRIPTIONS_STORE_PATH, {"subscriptions": []})

        if not os.path.exists(SETTINGS_STORE_PATH):
            payload = _default_rules()
            payload["updated_at"] = time.time()
            _write_json(SETTINGS_STORE_PATH, payload)


def _is_webpush_configured() -> bool:
    return bool(
        _WEBPUSH_LIB_AVAILABLE
        and SMARTDRIVE_WEBPUSH_PUBLIC_KEY
        and SMARTDRIVE_WEBPUSH_PRIVATE_KEY
        and SMARTDRIVE_WEBPUSH_SUBJECT
    )


def get_vapid_public_key() -> str:
    return SMARTDRIVE_WEBPUSH_PUBLIC_KEY


def get_notification_rules() -> dict[str, Any]:
    ensure_push_storage()
    defaults = _default_rules()

    with _LOCK:
        raw = _read_json(SETTINGS_STORE_PATH, defaults)

    return {
        "notify_unknown_visitors": _coerce_bool(
            raw.get("notify_unknown_visitors"), defaults["notify_unknown_visitors"]
        ),
        "notify_recurrent_requests": _coerce_bool(
            raw.get("notify_recurrent_requests"), defaults["notify_recurrent_requests"]
        ),
        "recurrent_threshold": _coerce_int(
            raw.get("recurrent_threshold"),
            defaults["recurrent_threshold"],
            minimum=5,
            maximum=500,
        ),
        "recurrent_window_seconds": _coerce_int(
            raw.get("recurrent_window_seconds"),
            defaults["recurrent_window_seconds"],
            minimum=10,
            maximum=3600,
        ),
        "recurrent_cooldown_seconds": _coerce_int(
            raw.get("recurrent_cooldown_seconds"),
            defaults["recurrent_cooldown_seconds"],
            minimum=30,
            maximum=86400,
        ),
    }


def update_notification_rules(
    *,
    notify_unknown_visitors: bool,
    notify_recurrent_requests: bool,
    recurrent_threshold: int,
    recurrent_window_seconds: int,
    recurrent_cooldown_seconds: int,
) -> dict[str, Any]:
    ensure_push_storage()

    updated = {
        "notify_unknown_visitors": bool(notify_unknown_visitors),
        "notify_recurrent_requests": bool(notify_recurrent_requests),
        "recurrent_threshold": _coerce_int(recurrent_threshold, 25, minimum=5, maximum=500),
        "recurrent_window_seconds": _coerce_int(
            recurrent_window_seconds,
            120,
            minimum=10,
            maximum=3600,
        ),
        "recurrent_cooldown_seconds": _coerce_int(
            recurrent_cooldown_seconds,
            900,
            minimum=30,
            maximum=86400,
        ),
        "updated_at": time.time(),
    }

    with _LOCK:
        _write_json(SETTINGS_STORE_PATH, updated)

    return {key: updated[key] for key in _default_rules().keys()}


def _sanitize_subscription(payload: dict[str, Any]) -> dict[str, Any]:
    endpoint = str(payload.get("endpoint") or "").strip()
    keys_payload = payload.get("keys")
    keys = keys_payload if isinstance(keys_payload, dict) else {}
    p256dh = str(keys.get("p256dh") or "").strip()
    auth = str(keys.get("auth") or "").strip()

    if not endpoint or not p256dh or not auth:
        raise ValueError("Subscription payload inválido")

    expiration = payload.get("expirationTime")
    if expiration is not None:
        try:
            expiration = int(expiration)
        except (TypeError, ValueError):
            expiration = None

    return {
        "endpoint": endpoint,
        "expirationTime": expiration,
        "keys": {
            "p256dh": p256dh,
            "auth": auth,
        },
    }


def list_subscriptions() -> list[dict[str, Any]]:
    ensure_push_storage()

    with _LOCK:
        data = _read_json(SUBSCRIPTIONS_STORE_PATH, {"subscriptions": []})
        subscriptions = data.get("subscriptions", [])
        if not isinstance(subscriptions, list):
            return []

    valid_subscriptions: list[dict[str, Any]] = []
    for candidate in subscriptions:
        if isinstance(candidate, dict) and candidate.get("endpoint"):
            valid_subscriptions.append(candidate)
    return valid_subscriptions


def upsert_subscription(payload: dict[str, Any]) -> dict[str, Any]:
    ensure_push_storage()
    normalized = _sanitize_subscription(payload)
    endpoint = normalized["endpoint"]

    with _LOCK:
        data = _read_json(SUBSCRIPTIONS_STORE_PATH, {"subscriptions": []})
        subscriptions = data.get("subscriptions", [])
        if not isinstance(subscriptions, list):
            subscriptions = []

        updated = False
        for item in subscriptions:
            if not isinstance(item, dict):
                continue
            if item.get("endpoint") == endpoint:
                item.update(normalized)
                item["updated_at"] = time.time()
                updated = True
                break

        if not updated:
            subscriptions.append(
                {
                    **normalized,
                    "subscription_id": f"sub-{uuid.uuid4().hex[:10]}",
                    "owner_visitor_id": None,
                    "created_at": time.time(),
                    "updated_at": time.time(),
                }
            )

        data["subscriptions"] = subscriptions
        _write_json(SUBSCRIPTIONS_STORE_PATH, data)

    return {
        "ok": True,
        "updated": updated,
        "total_subscriptions": len(subscriptions),
    }


def upsert_admin_subscription(payload: dict[str, Any], owner_visitor_id: str) -> dict[str, Any]:
    owner_id = (owner_visitor_id or "").strip()
    if not owner_id:
        raise ValueError("No se pudo asociar la suscripción a un admin")

    result = upsert_subscription(payload)
    endpoint = str(payload.get("endpoint") or "").strip()
    if not endpoint:
        raise ValueError("Subscription payload inválido")

    with _LOCK:
        data = _read_json(SUBSCRIPTIONS_STORE_PATH, {"subscriptions": []})
        subscriptions = data.get("subscriptions", [])
        if not isinstance(subscriptions, list):
            subscriptions = []

        for item in subscriptions:
            if not isinstance(item, dict):
                continue
            if item.get("endpoint") == endpoint:
                item["owner_visitor_id"] = owner_id
                item["updated_at"] = time.time()
                break

        data["subscriptions"] = subscriptions
        _write_json(SUBSCRIPTIONS_STORE_PATH, data)

    return result


def _active_admin_ids() -> set[str]:
    with _LOCK:
        visitors_data = _read_json(VISITOR_STORE_PATH, {"visitors": {}})

    visitors = visitors_data.get("visitors", {})
    if not isinstance(visitors, dict):
        return set()

    active_admins: set[str] = set()
    for visitor_id, visitor_data in visitors.items():
        if not isinstance(visitor_data, dict):
            continue
        if bool(visitor_data.get("is_owner", False)) and visitor_id:
            active_admins.add(str(visitor_id))
    return active_admins


def _eligible_admin_subscriptions() -> tuple[list[dict[str, Any]], int]:
    subscriptions = list_subscriptions()
    if not subscriptions:
        return [], 0

    active_admins = _active_admin_ids()
    if not active_admins:
        return [], 0

    eligible: list[dict[str, Any]] = []
    skipped_non_admin = 0
    for subscription in subscriptions:
        owner_id = str(subscription.get("owner_visitor_id") or "").strip()
        if owner_id and owner_id in active_admins:
            eligible.append(subscription)
        else:
            skipped_non_admin += 1

    return eligible, skipped_non_admin


def remove_subscription(endpoint: str) -> dict[str, Any]:
    ensure_push_storage()
    target = (endpoint or "").strip()
    if not target:
        return {"ok": False, "removed": False, "total_subscriptions": len(list_subscriptions())}

    with _LOCK:
        data = _read_json(SUBSCRIPTIONS_STORE_PATH, {"subscriptions": []})
        subscriptions = data.get("subscriptions", [])
        if not isinstance(subscriptions, list):
            subscriptions = []

        filtered = []
        removed = False
        for item in subscriptions:
            if isinstance(item, dict) and item.get("endpoint") == target:
                removed = True
                continue
            filtered.append(item)

        data["subscriptions"] = filtered
        _write_json(SUBSCRIPTIONS_STORE_PATH, data)

    return {
        "ok": True,
        "removed": removed,
        "total_subscriptions": len(filtered),
    }


def get_notification_status() -> dict[str, Any]:
    subscriptions = list_subscriptions()
    rules = get_notification_rules()

    enabled = _is_webpush_configured()
    if enabled:
        message = "Web Push activo"
    elif not _WEBPUSH_LIB_AVAILABLE:
        message = "Falta dependencia pywebpush"
    else:
        message = "Configura SMARTDRIVE_WEBPUSH_PUBLIC_KEY / PRIVATE_KEY / SUBJECT"

    return {
        "enabled": enabled,
        "library_available": _WEBPUSH_LIB_AVAILABLE,
        "configured": bool(SMARTDRIVE_WEBPUSH_PUBLIC_KEY and SMARTDRIVE_WEBPUSH_PRIVATE_KEY and SMARTDRIVE_WEBPUSH_SUBJECT),
        "message": message,
        "subscription_count": len(subscriptions),
        "rules": rules,
    }


def _send_notification(title: str, body: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not _is_webpush_configured() or webpush is None:
        return {"sent": 0, "failed": 0, "pruned": 0}

    subscriptions, _skipped_non_admin = _eligible_admin_subscriptions()
    if not subscriptions:
        return {"sent": 0, "failed": 0, "pruned": 0}

    message = {
        "title": title,
        "body": body,
        "tag": "smartdrive-access-alert",
        "url": "/control?non_owner_only=1",
    }
    if payload:
        message.update(payload)

    message_data = json.dumps(message, ensure_ascii=False)

    sent = 0
    failed = 0
    stale_endpoints: list[str] = []

    for subscription in subscriptions:
        try:
            webpush(
                subscription_info=subscription,
                data=message_data,
                vapid_private_key=SMARTDRIVE_WEBPUSH_PRIVATE_KEY,
                vapid_claims={"sub": SMARTDRIVE_WEBPUSH_SUBJECT},
            )
            sent += 1
        except WebPushException as exc:
            failed += 1
            status_code = None
            response = getattr(exc, "response", None)
            if response is not None:
                status_code = getattr(response, "status_code", None)
            if status_code in {404, 410} and subscription.get("endpoint"):
                stale_endpoints.append(subscription["endpoint"])
            logger.warning("Push notification failed. status=%s error=%s", status_code, exc)
        except Exception as exc:  # pragma: no cover - defensive
            failed += 1
            logger.warning("Push notification failed with unexpected error: %s", exc)

    pruned = 0
    for endpoint in stale_endpoints:
        result = remove_subscription(endpoint)
        if result.get("removed"):
            pruned += 1

    return {
        "sent": sent,
        "failed": failed,
        "pruned": pruned,
    }


def notify_new_unknown_visitor(
    *,
    visitor_id: str,
    client_ip: str,
    ip_location: str,
    path: str,
    method: str,
) -> dict[str, Any]:
    title = "Nuevo acceso no registrado"
    location_text = ip_location or "Desconocida"
    body = f"{visitor_id[:8]} · {client_ip} ({location_text}) · {method} {path}"
    return _send_notification(
        title,
        body,
        {
            "type": "unknown_visitor",
            "visitor_id": visitor_id,
            "ip": client_ip,
            "ip_location": location_text,
            "path": path,
            "method": method,
        },
    )


def _track_recent_request(visitor_id: str, window_seconds: int) -> int:
    now_ts = time.time()

    with _RATE_LOCK:
        queue = _RECENT_REQUESTS.setdefault(visitor_id, deque())
        queue.append(now_ts)

        while queue and (now_ts - queue[0]) > window_seconds:
            queue.popleft()

        return len(queue)


def _can_emit_recurrent_alert(visitor_id: str, cooldown_seconds: int) -> bool:
    now_ts = time.time()

    with _RATE_LOCK:
        last_alert = _LAST_RECURRENT_ALERT_AT.get(visitor_id)
        if last_alert is not None and (now_ts - last_alert) < cooldown_seconds:
            return False
        _LAST_RECURRENT_ALERT_AT[visitor_id] = now_ts
        return True


def maybe_notify_access_risk(
    *,
    visitor_id: str,
    fingerprint: str,
    activity_fingerprint: str,
    set_cookie: bool,
    is_owner: bool,
    is_new: bool,
    client_ip: str,
    ip_location: str,
    path: str,
    method: str,
) -> None:
    if is_owner:
        return

    status = get_notification_status()
    if not status.get("enabled"):
        return
    if int(status.get("subscription_count", 0)) <= 0:
        return

    rules = status.get("rules", {})

    if is_new and bool(rules.get("notify_unknown_visitors", False)):
        notify_new_unknown_visitor(
            visitor_id=visitor_id,
            client_ip=client_ip,
            ip_location=ip_location,
            path=path,
            method=method,
        )

    if not bool(rules.get("notify_recurrent_requests", False)):
        return

    threshold = _coerce_int(rules.get("recurrent_threshold"), 25, minimum=5, maximum=500)
    window_seconds = _coerce_int(
        rules.get("recurrent_window_seconds"),
        120,
        minimum=10,
        maximum=3600,
    )
    cooldown_seconds = _coerce_int(
        rules.get("recurrent_cooldown_seconds"),
        900,
        minimum=30,
        maximum=86400,
    )

    if set_cookie:
        recurrent_key = f"stateless:{(activity_fingerprint or '').strip() or (fingerprint or '').strip() or visitor_id}"
    else:
        recurrent_key = visitor_id

    requests_in_window = _track_recent_request(recurrent_key, window_seconds=window_seconds)
    if requests_in_window < threshold:
        return

    if not _can_emit_recurrent_alert(recurrent_key, cooldown_seconds=cooldown_seconds):
        return

    title = "Actividad recurrente detectada"
    location_text = ip_location or "Desconocida"
    body = (
        f"{visitor_id[:8]} · {client_ip} ({location_text}) · "
        f"{requests_in_window} peticiones en {window_seconds}s "
        f"({method} {path})"
    )
    _send_notification(
        title,
        body,
        {
            "type": "recurrent_requests",
            "visitor_id": visitor_id,
            "ip": client_ip,
            "ip_location": location_text,
            "path": path,
            "method": method,
            "requests_in_window": requests_in_window,
            "window_seconds": window_seconds,
        },
    )
