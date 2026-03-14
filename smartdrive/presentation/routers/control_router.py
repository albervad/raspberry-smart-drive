from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from smartdrive.application.services.access_control_service import (
    clear_detected_users,
    clear_event_records,
    delete_user_records,
    get_access_control_dashboard,
    track_user_action,
    update_visitor_block_state,
    update_visitor_owner_state,
)
from smartdrive.infrastructure.templates import templates


router = APIRouter()


def _require_owner(request: Request) -> None:
    if not getattr(request.state, "visitor_is_owner", False):
        raise HTTPException(status_code=403, detail="Panel solo disponible para admin")


def _audit(request: Request, action: str, details: dict | None = None) -> None:
    visitor_id = getattr(request.state, "visitor_id", None)
    track_user_action(
        visitor_id=visitor_id,
        action=action,
        path=request.url.path,
        details=details,
        status="ok",
    )


def _redirect_control(request: Request) -> RedirectResponse:
    non_owner_only = request.query_params.get("non_owner_only") in {"1", "true", "True"}
    target = "/control?non_owner_only=1" if non_owner_only else "/control"
    return RedirectResponse(url=target, status_code=303)


@router.get("/control")
def control_panel(request: Request, non_owner_only: bool = False, q: str = ""):
    _require_owner(request)
    current_visitor_id = getattr(request.state, "visitor_id", "") or ""
    context = get_access_control_dashboard(
        non_owner_only=non_owner_only, query=q, current_visitor_id=current_visitor_id
    )
    context["request"] = request
    return templates.TemplateResponse("control_panel.html", context)


@router.post("/control/visitor/{visitor_id}/block")
def block_visitor(request: Request, visitor_id: str):
    _require_owner(request)
    updated = update_visitor_block_state(visitor_id, blocked=True)
    _audit(request, "block_visitor", details={"target": visitor_id, "updated": updated})
    return _redirect_control(request)


@router.post("/control/visitor/{visitor_id}/unblock")
def unblock_visitor(request: Request, visitor_id: str):
    _require_owner(request)
    updated = update_visitor_block_state(visitor_id, blocked=False)
    _audit(request, "unblock_visitor", details={"target": visitor_id, "updated": updated})
    return _redirect_control(request)


@router.post("/control/visitor/{visitor_id}/mark-owner")
def mark_owner(request: Request, visitor_id: str):
    _require_owner(request)
    updated = update_visitor_owner_state(visitor_id, is_owner=True)
    _audit(request, "mark_owner", details={"target": visitor_id, "updated": updated})
    return _redirect_control(request)


@router.post("/control/visitor/{visitor_id}/unmark-owner")
def unmark_owner(request: Request, visitor_id: str):
    _require_owner(request)
    updated = update_visitor_owner_state(visitor_id, is_owner=False)
    _audit(request, "unmark_owner", details={"target": visitor_id, "updated": updated})
    return _redirect_control(request)


@router.post("/control/events/clear")
def clear_all_events(request: Request):
    _require_owner(request)
    clear_event_records()
    return _redirect_control(request)


@router.post("/control/events/clear/{visitor_id}")
def clear_visitor_events(request: Request, visitor_id: str):
    _require_owner(request)
    clear_event_records(visitor_id=visitor_id)
    return _redirect_control(request)


@router.post("/control/visitors/clear")
def clear_all_visitors(request: Request):
    _require_owner(request)
    current_visitor_id = getattr(request.state, "visitor_id", None)
    removed = clear_detected_users(current_visitor_id=current_visitor_id)
    _audit(request, "clear_detected_users", details={"removed": removed})
    return _redirect_control(request)


@router.post("/control/visitor/{visitor_id}/purge")
def purge_visitor(request: Request, visitor_id: str):
    _require_owner(request)
    current_visitor_id = getattr(request.state, "visitor_id", None)
    result = delete_user_records(visitor_id=visitor_id, current_visitor_id=current_visitor_id)
    _audit(request, "purge_visitor", details={"target": visitor_id, **result})
    return _redirect_control(request)
