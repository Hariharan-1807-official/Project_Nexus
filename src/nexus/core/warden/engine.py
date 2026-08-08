"""
Warden Engine — permission rule evaluation, policy enforcement, and
task-scoped session approval tracking (ADR-002, ADR-012).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from nexus.models.warden import (
    ActionCategory, PermissionRequest, PermissionResult, PermissionState
)
from nexus.core.warden.prompt import DESTRUCTIVE_ACTIONS


class WardenEngine:
    """
    Evaluates agent actions against .nexus/config/permissions.json
    and tracks task-scoped session approvals.
    """

    def __init__(self, project_root: Path) -> None:
        self.root = project_root.resolve()
        self.config_path = self.root / ".nexus" / "config" / "permissions.json"
        # Session approvals: { (task_id, action_category): True }
        self._session_approvals: dict[tuple[str, ActionCategory], bool] = {}

    def load_permissions(self) -> dict:
        """Load permissions dict from permissions.json, or empty dict if missing."""
        if not self.config_path.exists():
            return {}
        try:
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def set_permission(
        self,
        agent: str,
        action: ActionCategory,
        state: PermissionState,
    ) -> bool:
        """Update a permission setting in .nexus/config/permissions.json."""
        perms = self.load_permissions()
        if agent not in perms:
            perms[agent] = {}
        perms[agent][action.value] = state.value

        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(json.dumps(perms, indent=2), encoding="utf-8")
            return True
        except Exception:
            return False

    def evaluate(self, request: PermissionRequest) -> PermissionResult:
        """
        Evaluate a permission request.
        
        Rules:
        1. If permissions.json config specifies 'deny' -> Deny immediately.
        2. If permissions.json specifies 'allow' -> Allow immediately.
        3. If permissions.json specifies 'approval':
           - Destructive actions (git_push, delete_files) -> ALWAYS require prompt (ADR-002).
           - Non-destructive actions: Check task-scoped session approval table. If granted -> Allow. Else -> Prompt.
        """
        perms = self.load_permissions()
        agent_perms = perms.get(request.agent, {})
        raw_setting = agent_perms.get(request.action_category.value, "approval")

        try:
            policy_state = PermissionState(raw_setting)
        except ValueError:
            policy_state = PermissionState.approval

        # Rule 1: Deny
        if policy_state == PermissionState.deny:
            return PermissionResult(
                allowed=False,
                state=PermissionState.deny,
                reason=f"Denied by policy in permissions.json for {request.agent}:{request.action_category.value}",
                prompt_user=False,
                task_id=request.task_id,
            )

        # Rule 2: Allow
        if policy_state == PermissionState.allow:
            return PermissionResult(
                allowed=True,
                state=PermissionState.allow,
                reason=f"Allowed by policy in permissions.json for {request.agent}:{request.action_category.value}",
                prompt_user=False,
                task_id=request.task_id,
            )

        # Rule 3: Approval required
        # Check task-scoped session approval table (non-destructive actions only — ADR-012)
        is_destructive = request.action_category in DESTRUCTIVE_ACTIONS
        if not is_destructive and request.task_id:
            key = (request.task_id, request.action_category)
            if self._session_approvals.get(key):
                return PermissionResult(
                    allowed=True,
                    state=PermissionState.allow,
                    reason=f"Allowed via active session approval for task '{request.task_id}'",
                    prompt_user=False,
                    task_id=request.task_id,
                )

        return PermissionResult(
            allowed=False,
            state=PermissionState.approval,
            reason=f"Requires human approval ({request.action_category.value})",
            prompt_user=True,
            task_id=request.task_id,
        )

    def grant_session_approval(self, task_id: str, action: ActionCategory) -> bool:
        """Grant session approval for a non-destructive action for the given task_id."""
        if action in DESTRUCTIVE_ACTIONS:
            return False  # Safety override (ADR-002)
        self._session_approvals[(task_id, action)] = True
        return True

    def revoke_task_approvals(self, task_id: str) -> None:
        """Clear all session approvals for a task_id when task finishes (ADR-012)."""
        keys_to_del = [k for k in self._session_approvals.keys() if k[0] == task_id]
        for k in keys_to_del:
            del self._session_approvals[k]
