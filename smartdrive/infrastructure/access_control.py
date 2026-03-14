import asyncio
import hashlib
import json
import os
import secrets
import threading
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from smartdrive.infrastructure.logging import get_logger
from smartdrive.infrastructure.settings import (
    SMARTDRIVE_AUDIT_DIR,
    SMARTDRIVE_AUDIT_MAX_EVENTS,
    SMARTDRIVE_AUDIT_RECENT_LIMIT,
    SMARTDRIVE_NEW_VISITOR_WINDOW_HOURS,
    SMARTDRIVE_OWNER_IPS,
    SMARTDRIVE_TRUST_PROXY_HEADERS,
    SMARTDRIVE_TRUSTED_PROXY_IPS,
)


logger = get_logger("access_control")

VISITOR_COOKIE_NAME = "sd_vid"
CSRF_COOKIE_NAME = "sd_csrf"
CSRF_HEADER_NAME = "x-csrf-token"
CSRF_QUERY_NAME = "csrf_token"
VISITOR_STORE_PATH = os.path.join(SMARTDRIVE_AUDIT_DIR, "visitor_registry.json")
EVENT_STORE_PATH = os.path.join(SMARTDRIVE_AUDIT_DIR, "audit_events.json")

_LOCK = threading.Lock()
_STORAGE_READY = False

_GEO_CACHE: dict[str, str] = {}
_GEO_CACHE_LOCK = threading.Lock()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _is_new_visitor(first_seen_iso: str | None) -> bool:
    first_seen = _parse_iso(first_seen_iso)
    if not first_seen:
        return False

    window = timedelta(hours=max(SMARTDRIVE_NEW_VISITOR_WINDOW_HOURS, 1))
    return datetime.now(timezone.utc) - first_seen <= window


def _read_json(path: str, default: dict[str, Any]) -> dict[str, Any]:
    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as file_handle:
            return json.load(file_handle)
    except (json.JSONDecodeError, OSError):
        logger.warning("Invalid JSON store detected. Resetting file=%s", path)
        return default


def _write_json(path: str, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as file_handle:
        json.dump(data, file_handle, ensure_ascii=False, indent=2)


def _sanitize_event_details(details: dict[str, Any] | None) -> dict[str, Any]:
    if not details:
        return {}

    clean: dict[str, Any] = {}
    for key, value in details.items():
        key_name = str(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            normalized = value
        else:
            normalized = str(value)

        text_value = str(normalized) if normalized is not None else ""
        if len(text_value) > 400:
            normalized = text_value[:400] + "..."

        clean[key_name] = normalized
    return clean


def _is_trackable_request(path: str) -> bool:
    static_prefixes = (
        "/static/",
        "/drive/inbox/",
        "/drive/files/",
        "/favicon.ico",
    )
    return not path.startswith(static_prefixes)


def _is_unsafe_method(method: str) -> bool:
    return method.upper() in {"POST", "PUT", "PATCH", "DELETE"}


def _has_same_origin(request: Request) -> bool:
    host = (request.headers.get("host") or "").strip().lower()
    if not host:
        return False

    origin = (request.headers.get("origin") or "").strip()
    if origin:
        parsed_origin = urlsplit(origin)
        return (
            parsed_origin.scheme in {"http", "https"}
            and parsed_origin.netloc.lower() == host
        )

    referer = (request.headers.get("referer") or "").strip()
    if referer:
        parsed_referer = urlsplit(referer)
        return (
            parsed_referer.scheme in {"http", "https"}
            and parsed_referer.netloc.lower() == host
        )

    return False


def _has_valid_csrf_token(request: Request, csrf_token: str) -> bool:
    header_token = (request.headers.get(CSRF_HEADER_NAME) or "").strip()
    query_token = (request.query_params.get(CSRF_QUERY_NAME) or "").strip()

    for candidate in (header_token, query_token):
        if candidate and secrets.compare_digest(candidate, csrf_token):
            return True

    return False


def _normalize_ip(value: str | None) -> str | None:
    if not value:
        return None

    candidate = value.strip()
    if not candidate:
        return None

    if candidate.startswith("[") and "]" in candidate:
        candidate = candidate[1 : candidate.index("]")]
    elif candidate.count(":") == 1 and "." in candidate:
        candidate = candidate.split(":", 1)[0]

    try:
        return str(ip_address(candidate))
    except ValueError:
        return None


def _pick_forwarded_ip(forwarded_for: str) -> str | None:
    parts = [part.strip() for part in forwarded_for.split(",") if part.strip()]
    for part in parts:
        normalized = _normalize_ip(part)
        if normalized:
            return normalized
    return None


def extract_client_ip(request: Request) -> str:
    peer_host = request.client.host if request.client else "-"
    peer_ip = _normalize_ip(peer_host)

    if not SMARTDRIVE_TRUST_PROXY_HEADERS:
        return peer_ip or peer_host

    if not peer_ip or peer_ip not in SMARTDRIVE_TRUSTED_PROXY_IPS:
        return peer_ip or peer_host

    forwarded_for = request.headers.get("x-forwarded-for", "").strip()
    if forwarded_for:
        forwarded_ip = _pick_forwarded_ip(forwarded_for)
        if forwarded_ip:
            return forwarded_ip

    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        normalized_real_ip = _normalize_ip(real_ip)
        if normalized_real_ip:
            return normalized_real_ip

    return peer_ip or peer_host


def _is_private_ip(ip: str) -> bool:
    if not ip or ip in ("-", ""):
        return True
    try:
        addr = ip_address(ip)
        return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
    except ValueError:
        return False


def geolocate_ip(ip: str) -> str:
    """Return 'City, Country' for a public IP, 'Local/Red privada' for private ones.
    Results are cached in memory for the lifetime of the process."""
    if _is_private_ip(ip):
        return "Local/Red privada"

    with _GEO_CACHE_LOCK:
        cached = _GEO_CACHE.get(ip)
    if cached is not None:
        return cached

    result = "Desconocida"
    try:
        url = f"http://ip-api.com/json/{ip}?fields=status,country,city"
        with urllib.request.urlopen(url, timeout=3) as resp:  # noqa: S310
            data = json.loads(resp.read())
        if data.get("status") == "success":
            parts = [data.get("city", ""), data.get("country", "")]
            result = ", ".join(p for p in parts if p) or "Desconocida"
    except Exception:
        pass

    with _GEO_CACHE_LOCK:
        _GEO_CACHE[ip] = result
    return result


def ensure_access_control_storage() -> None:
    global _STORAGE_READY

    if _STORAGE_READY:
        return

    try:
        os.makedirs(SMARTDRIVE_AUDIT_DIR, exist_ok=True)
    except PermissionError:
        logger.error("Permission denied while creating audit directory: %s", SMARTDRIVE_AUDIT_DIR)
        return

    with _LOCK:
        if _STORAGE_READY:
            return

        visitors_data = _read_json(VISITOR_STORE_PATH, {"visitors": {}})
        if "visitors" not in visitors_data or not isinstance(visitors_data.get("visitors"), dict):
            visitors_data = {"visitors": {}}
            _write_json(VISITOR_STORE_PATH, visitors_data)
        elif not os.path.exists(VISITOR_STORE_PATH):
            _write_json(VISITOR_STORE_PATH, visitors_data)

        events_data = _read_json(EVENT_STORE_PATH, {"events": []})
        if "events" not in events_data or not isinstance(events_data.get("events"), list):
            events_data = {"events": []}
            _write_json(EVENT_STORE_PATH, events_data)
        elif not os.path.exists(EVENT_STORE_PATH):
            _write_json(EVENT_STORE_PATH, events_data)

        _STORAGE_READY = True


def touch_visitor(request: Request) -> dict[str, Any]:
    ensure_access_control_storage()

    visitor_id = request.cookies.get(VISITOR_COOKIE_NAME)
    set_cookie = False
    if not visitor_id:
        visitor_id = f"v-{uuid.uuid4().hex[:12]}"
        set_cookie = True

    now_iso = _utcnow_iso()
    path = request.url.path
    client_ip = extract_client_ip(request)
    user_agent = (request.headers.get("user-agent") or "").strip()[:300]
    accept_language = (request.headers.get("accept-language") or "").strip()[:120]

    fingerprint_seed = f"{client_ip}|{user_agent}|{accept_language}"
    fingerprint = hashlib.sha1(fingerprint_seed.encode("utf-8")).hexdigest()[:16]

    with _LOCK:
        visitors_data = _read_json(VISITOR_STORE_PATH, {"visitors": {}})
        visitors = visitors_data.setdefault("visitors", {})

        visitor = visitors.get(visitor_id)
        is_new = visitor is None

        if visitor is None:
            visitor = {
                "visitor_id": visitor_id,
                "first_seen": now_iso,
                "last_seen": now_iso,
                "first_ip": client_ip,
                "last_ip": client_ip,
                "user_agent": user_agent,
                "accept_language": accept_language,
                "fingerprint": fingerprint,
                "requests_count": 0,
                "actions_count": 0,
                "is_blocked": False,
                "is_owner": client_ip in SMARTDRIVE_OWNER_IPS,
                "last_path": path,
                "last_method": request.method,
                "last_action": None,
                "last_action_at": None,
            }

        if _is_trackable_request(path):
            visitor["requests_count"] = int(visitor.get("requests_count", 0)) + 1

        visitor["last_seen"] = now_iso
        visitor["last_ip"] = client_ip
        visitor["user_agent"] = user_agent or visitor.get("user_agent", "")
        visitor["accept_language"] = accept_language or visitor.get("accept_language", "")
        visitor["fingerprint"] = fingerprint
        visitor["last_path"] = path
        visitor["last_method"] = request.method

        visitors[visitor_id] = visitor
        visitors_data["visitors"] = visitors
        _write_json(VISITOR_STORE_PATH, visitors_data)

    return {
        "visitor_id": visitor_id,
        "set_cookie": set_cookie,
        "client_ip": client_ip,
        "is_owner": bool(visitor.get("is_owner", False)),
        "is_blocked": bool(visitor.get("is_blocked", False)),
        "is_new": is_new,
    }


def record_action_event(
    visitor_id: str | None,
    action: str,
    path: str,
    details: dict[str, Any] | None = None,
    status: str = "ok",
) -> None:
    if not visitor_id:
        return

    ensure_access_control_storage()

    now_iso = _utcnow_iso()
    clean_details = _sanitize_event_details(details)

    event = {
        "event_id": uuid.uuid4().hex,
        "timestamp": now_iso,
        "visitor_id": visitor_id,
        "action": action,
        "path": path,
        "status": status,
        "details": clean_details,
    }

    with _LOCK:
        visitors_data = _read_json(VISITOR_STORE_PATH, {"visitors": {}})
        visitors = visitors_data.setdefault("visitors", {})

        visitor = visitors.get(visitor_id)
        if visitor is None:
            visitor = {
                "visitor_id": visitor_id,
                "first_seen": now_iso,
                "last_seen": now_iso,
                "first_ip": "-",
                "last_ip": "-",
                "user_agent": "",
                "accept_language": "",
                "fingerprint": "",
                "requests_count": 0,
                "actions_count": 0,
                "is_blocked": False,
                "is_owner": False,
                "last_path": path,
                "last_method": "",
                "last_action": action,
                "last_action_at": now_iso,
            }

        visitor["actions_count"] = int(visitor.get("actions_count", 0)) + 1
        visitor["last_action"] = action
        visitor["last_action_at"] = now_iso
        visitor["last_seen"] = now_iso
        visitors[visitor_id] = visitor
        visitors_data["visitors"] = visitors
        _write_json(VISITOR_STORE_PATH, visitors_data)

        events_data = _read_json(EVENT_STORE_PATH, {"events": []})
        events = events_data.setdefault("events", [])
        events.append(event)

        if len(events) > SMARTDRIVE_AUDIT_MAX_EVENTS:
            events = events[-SMARTDRIVE_AUDIT_MAX_EVENTS :]

        events_data["events"] = events
        _write_json(EVENT_STORE_PATH, events_data)


def set_visitor_block_state(visitor_id: str, blocked: bool) -> bool:
    ensure_access_control_storage()

    with _LOCK:
        visitors_data = _read_json(VISITOR_STORE_PATH, {"visitors": {}})
        visitors = visitors_data.setdefault("visitors", {})
        visitor = visitors.get(visitor_id)

        if visitor is None:
            return False

        visitor["is_blocked"] = bool(blocked)
        visitors[visitor_id] = visitor
        visitors_data["visitors"] = visitors
        _write_json(VISITOR_STORE_PATH, visitors_data)

    return True


def set_visitor_owner_state(visitor_id: str, is_owner: bool) -> bool:
    ensure_access_control_storage()

    with _LOCK:
        visitors_data = _read_json(VISITOR_STORE_PATH, {"visitors": {}})
        visitors = visitors_data.setdefault("visitors", {})
        visitor = visitors.get(visitor_id)

        if visitor is None:
            return False

        # Prevent removing owner status from visitors whose IP is permanently trusted
        if not is_owner:
            visitor_ip = visitor.get("last_ip") or visitor.get("first_ip") or ""
            if visitor_ip in SMARTDRIVE_OWNER_IPS:
                return False

        visitor["is_owner"] = bool(is_owner)
        visitors[visitor_id] = visitor
        visitors_data["visitors"] = visitors
        _write_json(VISITOR_STORE_PATH, visitors_data)

    return True


def clear_action_events(visitor_id: str | None = None) -> int:
    ensure_access_control_storage()

    with _LOCK:
        events_data = _read_json(EVENT_STORE_PATH, {"events": []})
        events = events_data.setdefault("events", [])
        original_count = len(events)

        if visitor_id:
            events = [event for event in events if event.get("visitor_id") != visitor_id]
            # Also reset the request/action counters stored on the visitor record
            visitors_data = _read_json(VISITOR_STORE_PATH, {"visitors": {}})
            visitors = visitors_data.setdefault("visitors", {})
            if visitor_id in visitors:
                visitors[visitor_id]["requests_count"] = 0
                visitors[visitor_id]["actions_count"] = 0
                visitors_data["visitors"] = visitors
                _write_json(VISITOR_STORE_PATH, visitors_data)
        else:
            events = []

        events_data["events"] = events
        _write_json(EVENT_STORE_PATH, events_data)

    return original_count - len(events)


def clear_detected_visitors(preserve_visitor_ids: set[str] | None = None) -> int:
    ensure_access_control_storage()
    preserve_ids = set(preserve_visitor_ids or set())

    with _LOCK:
        visitors_data = _read_json(VISITOR_STORE_PATH, {"visitors": {}})
        visitors = visitors_data.setdefault("visitors", {})
        kept_visitors: dict[str, dict[str, Any]] = {}
        removed_count = 0

        for visitor_id, visitor in visitors.items():
            if visitor_id in preserve_ids or bool(visitor.get("is_owner", False)):
                kept_visitors[visitor_id] = visitor
                continue
            removed_count += 1

        visitors_data["visitors"] = kept_visitors
        _write_json(VISITOR_STORE_PATH, visitors_data)

    return removed_count


def purge_visitor_records(visitor_id: str, preserve_visitor_ids: set[str] | None = None) -> dict[str, Any]:
    ensure_access_control_storage()
    preserve_ids = set(preserve_visitor_ids or set())

    if visitor_id in preserve_ids:
        return {"removed_visitor": False, "removed_events": 0, "skipped_preserved": True}

    with _LOCK:
        visitors_data = _read_json(VISITOR_STORE_PATH, {"visitors": {}})
        events_data = _read_json(EVENT_STORE_PATH, {"events": []})

        visitors = visitors_data.setdefault("visitors", {})
        removed_visitor = visitor_id in visitors
        if removed_visitor:
            visitors.pop(visitor_id, None)

        events = events_data.setdefault("events", [])
        original_event_count = len(events)
        events = [event for event in events if event.get("visitor_id") != visitor_id]
        removed_events = original_event_count - len(events)

        visitors_data["visitors"] = visitors
        events_data["events"] = events
        _write_json(VISITOR_STORE_PATH, visitors_data)
        _write_json(EVENT_STORE_PATH, events_data)

    return {
        "removed_visitor": removed_visitor,
        "removed_events": removed_events,
        "skipped_preserved": False,
    }


def _matches_visitor_query(visitor: dict[str, Any], query: str) -> bool:
    text = " ".join(
        [
            str(visitor.get("visitor_id", "")),
            str(visitor.get("last_ip", "")),
            str(visitor.get("fingerprint", "")),
            str(visitor.get("user_agent", "")),
            str(visitor.get("accept_language", "")),
        ]
    ).lower()
    return query in text


def get_control_panel_data(
    non_owner_only: bool = False, query: str = "", current_visitor_id: str = ""
) -> dict[str, Any]:
    ensure_access_control_storage()

    with _LOCK:
        visitors_data = _read_json(VISITOR_STORE_PATH, {"visitors": {}})
        events_data = _read_json(EVENT_STORE_PATH, {"events": []})

    visitors_map: dict[str, dict[str, Any]] = visitors_data.get("visitors", {})
    events: list[dict[str, Any]] = events_data.get("events", [])

    visitors: list[dict[str, Any]] = []
    for raw_visitor in visitors_map.values():
        visitor = dict(raw_visitor)
        visitor["is_new"] = _is_new_visitor(visitor.get("first_seen"))
        visitor["visitor_short"] = visitor.get("visitor_id", "")[:8]
        visitor["is_self"] = bool(current_visitor_id and visitor.get("visitor_id") == current_visitor_id)
        visitor_ip = visitor.get("last_ip") or visitor.get("first_ip") or ""
        visitor["is_protected_owner"] = visitor_ip in SMARTDRIVE_OWNER_IPS
        visitor["geo_location"] = geolocate_ip(visitor_ip) if visitor_ip else "Desconocida"
        visitors.append(visitor)

    query_normalized = query.strip().lower()
    if query_normalized:
        visitors = [visitor for visitor in visitors if _matches_visitor_query(visitor, query_normalized)]

    visitors.sort(key=lambda item: item.get("last_seen", ""), reverse=True)

    events_sorted = sorted(events, key=lambda item: item.get("timestamp", ""), reverse=True)
    recent_events = events_sorted[: max(SMARTDRIVE_AUDIT_RECENT_LIMIT, 1)]

    for event in recent_events:
        visitor_data = visitors_map.get(event.get("visitor_id", ""), {})
        event["visitor_short"] = event.get("visitor_id", "")[:8]
        event["ip"] = visitor_data.get("last_ip", "-")
        event["is_owner"] = bool(visitor_data.get("is_owner", False))

    if query_normalized:
        visitor_ids = {visitor.get("visitor_id") for visitor in visitors}
        recent_events = [
            event
            for event in recent_events
            if (
                event.get("visitor_id") in visitor_ids
                or query_normalized in str(event.get("path", "")).lower()
                or query_normalized in str(event.get("action", "")).lower()
                or query_normalized in str(event.get("ip", "")).lower()
            )
        ]

    if non_owner_only:
        recent_events = [event for event in recent_events if not event.get("is_owner", False)]

    owner_ids = {
        visitor.get("visitor_id")
        for visitor in visitors
        if visitor.get("is_owner", False)
    }

    portfolio_events = [
        event
        for event in events
        if event.get("action") == "portfolio_view" and event.get("visitor_id") not in owner_ids
    ]

    last_24h_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    portfolio_last_24h = 0
    for event in portfolio_events:
        event_ts = _parse_iso(event.get("timestamp"))
        if event_ts and event_ts >= last_24h_cutoff:
            portfolio_last_24h += 1

    stats = {
        "total_visitors": len(visitors),
        "new_visitors": len([visitor for visitor in visitors if visitor.get("is_new") and not visitor.get("is_owner")]),
        "blocked_visitors": len([visitor for visitor in visitors if visitor.get("is_blocked")]),
        "total_events": len(events),
        "portfolio_visits_excluding_owner": len(portfolio_events),
        "portfolio_unique_visitors_excluding_owner": len({event.get("visitor_id") for event in portfolio_events}),
        "portfolio_visits_last_24h_excluding_owner": portfolio_last_24h,
    }

    return {
        "stats": stats,
        "visitors": visitors,
        "events": recent_events,
        "non_owner_only": non_owner_only,
        "search_query": query,
        "new_visitor_window_hours": SMARTDRIVE_NEW_VISITOR_WINDOW_HOURS,
    }


def setup_access_control(app: FastAPI) -> None:
    ensure_access_control_storage()

    @app.middleware("http")
    async def access_control_middleware(request: Request, call_next):
        path = request.url.path

        if not _is_trackable_request(path):
            return await call_next(request)

        visitor_info = touch_visitor(request)
        request.state.visitor_id = visitor_info["visitor_id"]
        request.state.client_ip = visitor_info["client_ip"]
        request.state.visitor_is_owner = visitor_info["is_owner"]

        csrf_token = request.cookies.get(CSRF_COOKIE_NAME) or uuid.uuid4().hex
        set_csrf_cookie = CSRF_COOKIE_NAME not in request.cookies
        request.state.csrf_token = csrf_token

        if _is_unsafe_method(request.method):
            has_valid_token = _has_valid_csrf_token(request, csrf_token)
            has_same_origin = _has_same_origin(request)

            if not (has_valid_token or has_same_origin):
                record_action_event(
                    visitor_id=visitor_info["visitor_id"],
                    action="csrf_rejected",
                    path=path,
                    details={
                        "method": request.method,
                        "origin": request.headers.get("origin", ""),
                        "referer": request.headers.get("referer", ""),
                    },
                    status="blocked",
                )
                response = PlainTextResponse("Solicitud rechazada por protección CSRF.", status_code=403)
                if visitor_info["set_cookie"]:
                    response.set_cookie(
                        VISITOR_COOKIE_NAME,
                        visitor_info["visitor_id"],
                        max_age=31536000,
                        httponly=True,
                        samesite="lax",
                    )
                if set_csrf_cookie:
                    response.set_cookie(
                        CSRF_COOKIE_NAME,
                        csrf_token,
                        max_age=31536000,
                        httponly=False,
                        samesite="lax",
                    )
                return response

        is_blocked_user = visitor_info["is_blocked"] and not visitor_info["is_owner"]
        allow_blocked_path = path.startswith("/control")

        if is_blocked_user and not allow_blocked_path:
            record_action_event(
                visitor_id=visitor_info["visitor_id"],
                action="blocked_request",
                path=path,
                details={"method": request.method},
                status="blocked",
            )
            response = PlainTextResponse("Acceso bloqueado por el administrador.", status_code=403)
            if visitor_info["set_cookie"]:
                response.set_cookie(
                    VISITOR_COOKIE_NAME,
                    visitor_info["visitor_id"],
                    max_age=31536000,
                    httponly=True,
                    samesite="lax",
                )
            if set_csrf_cookie:
                response.set_cookie(
                    CSRF_COOKIE_NAME,
                    csrf_token,
                    max_age=31536000,
                    httponly=False,
                    samesite="lax",
                )
            return response

        response = await call_next(request)

        if request.method == "GET" and path in {"/", "/portfolio"} and response.status_code < 400:
            event_kwargs = {
                "visitor_id": visitor_info["visitor_id"],
                "action": "portfolio_view",
                "path": path,
                "details": {"status_code": response.status_code},
                "status": "ok",
            }

            try:
                asyncio.create_task(asyncio.to_thread(record_action_event, **event_kwargs))
            except RuntimeError:
                record_action_event(**event_kwargs)

        if visitor_info["set_cookie"]:
            response.set_cookie(
                VISITOR_COOKIE_NAME,
                visitor_info["visitor_id"],
                max_age=31536000,
                httponly=True,
                samesite="lax",
            )
        if set_csrf_cookie:
            response.set_cookie(
                CSRF_COOKIE_NAME,
                csrf_token,
                max_age=31536000,
                httponly=False,
                samesite="lax",
            )

        return response
