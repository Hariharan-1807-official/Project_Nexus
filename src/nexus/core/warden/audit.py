"""
Warden Audit Trail — logs all permission decisions (allow, deny, prompt)
to `.nexus/memory/events.jsonl` (ADR-003).
"""

from __future__ import annotations

from typing import Any, Optional
from nexus.core.memory import Memory, EventType
from nexus.models.warden import PermissionRequest, PermissionResult, PermissionState


def log_warden_evaluation(
    memory: Memory,
    request: PermissionRequest,
    result: PermissionResult,
) -> dict:
    """Log a Warden evaluation event to memory audit trail."""
    if result.state == PermissionState.allow:
        event_type = EventType.warden_allow
    elif result.state == PermissionState.deny:
        event_type = EventType.warden_deny
    else:
        event_type = EventType.warden_prompt

    action_summary = f"warden:{request.action_category.value}:{request.agent}"

    detail: dict[str, Any] = {
        "action_category": request.action_category.value,
        "description":     request.description,
        "permission":      result.state.value,
        "allowed":          result.allowed,
        "reason":           result.reason,
    }
    if request.target_path:
        detail["target_path"] = request.target_path

    return memory.log_event(
        event_type,
        agent=request.agent,
        action=action_summary,
        task_id=request.task_id,
        result="allow" if result.allowed else "deny",
        detail=detail,
    )
