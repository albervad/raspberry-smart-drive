from typing import Any

from smartdrive.infrastructure.access_control import (
    clear_action_events,
    clear_detected_visitors,
    get_control_panel_data,
    purge_visitor_records,
    record_action_event,
    set_visitor_block_state,
    set_visitor_owner_state,
)


def get_access_control_dashboard(
    non_owner_only: bool = False, query: str = "", current_visitor_id: str = ""
) -> dict[str, Any]:
    return get_control_panel_data(
        non_owner_only=non_owner_only, query=query, current_visitor_id=current_visitor_id
    )


def track_user_action(
    visitor_id: str | None,
    action: str,
    path: str,
    details: dict[str, Any] | None = None,
    status: str = "ok",
) -> None:
    record_action_event(
        visitor_id=visitor_id,
        action=action,
        path=path,
        details=details,
        status=status,
    )


def update_visitor_block_state(visitor_id: str, blocked: bool) -> bool:
    return set_visitor_block_state(visitor_id, blocked)


def update_visitor_owner_state(visitor_id: str, is_owner: bool) -> bool:
    return set_visitor_owner_state(visitor_id, is_owner)


def clear_event_records(visitor_id: str | None = None) -> int:
    return clear_action_events(visitor_id=visitor_id)


def clear_detected_users(current_visitor_id: str | None = None) -> int:
    preserve_ids = {current_visitor_id} if current_visitor_id else None
    return clear_detected_visitors(preserve_visitor_ids=preserve_ids)


def delete_user_records(visitor_id: str, current_visitor_id: str | None = None) -> dict[str, Any]:
    preserve_ids = {current_visitor_id} if current_visitor_id else None
    return purge_visitor_records(visitor_id=visitor_id, preserve_visitor_ids=preserve_ids)
