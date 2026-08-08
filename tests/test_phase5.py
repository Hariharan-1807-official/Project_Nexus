"""
Phase 5 Test Suite — Warden Security & Permissions System.

Validates:
- TC-5.1: Permission rule evaluation (allow, deny, approval)
- TC-5.2: Destructive action safety override (git_push & delete_files always prompt per ADR-002)
- TC-5.3: Task-scoped session approval tracking & revocation (ADR-012)
- TC-5.4: Audit trail logging to memory/events.jsonl (ADR-003)
- TC-5.5: CLI commands `nexus warden` matrix and `nexus warden set` rule updates
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from nexus.cli.main import app
from nexus.core.warden import (
    WardenEngine, ActionCategory, PermissionState, PermissionRequest, PermissionResult,
    log_warden_evaluation, prompt_approval
)
from nexus.core.memory import Memory, EventType
from nexus.agents.codex import CodexAgent

runner = CliRunner()


# ===========================================================================
# TC-5.1: Permission Evaluation Engine
# ===========================================================================

class TestTC51PermissionEvaluation:
    def test_default_permissions_require_approval(self, tmp_path):
        engine = WardenEngine(tmp_path)
        req = PermissionRequest(
            agent="codex",
            action_category=ActionCategory.execute_commands,
            description="Run shell command",
        )
        res = engine.evaluate(req)
        assert res.allowed is False
        assert res.state == PermissionState.approval
        assert res.prompt_user is True

    def test_allow_permission(self, tmp_path):
        engine = WardenEngine(tmp_path)
        engine.set_permission("codex", ActionCategory.read_source, PermissionState.allow)

        req = PermissionRequest(
            agent="codex",
            action_category=ActionCategory.read_source,
            description="Read src/main.py",
        )
        res = engine.evaluate(req)
        assert res.allowed is True
        assert res.state == PermissionState.allow

    def test_deny_permission(self, tmp_path):
        engine = WardenEngine(tmp_path)
        engine.set_permission("codex", ActionCategory.network, PermissionState.deny)

        req = PermissionRequest(
            agent="codex",
            action_category=ActionCategory.network,
            description="Outbound network request",
        )
        res = engine.evaluate(req)
        assert res.allowed is False
        assert res.state == PermissionState.deny
        assert res.prompt_user is False


# ===========================================================================
# TC-5.2: Destructive Action Safety Override (ADR-002)
# ===========================================================================

class TestTC52DestructiveActionSafety:
    def test_git_push_always_requires_prompt(self, tmp_path):
        engine = WardenEngine(tmp_path)
        # Even if session approval is granted for other actions on this task:
        engine.grant_session_approval("task-123", ActionCategory.git_push)

        req = PermissionRequest(
            agent="codex",
            action_category=ActionCategory.git_push,
            description="git push origin main",
            task_id="task-123",
        )
        res = engine.evaluate(req)
        # git_push MUST STILL prompt (ADR-002)
        assert res.allowed is False
        assert res.state == PermissionState.approval
        assert res.prompt_user is True

    def test_delete_files_always_requires_prompt(self, tmp_path):
        engine = WardenEngine(tmp_path)
        engine.grant_session_approval("task-123", ActionCategory.delete_files)

        req = PermissionRequest(
            agent="codex",
            action_category=ActionCategory.delete_files,
            description="rm -rf build/",
            task_id="task-123",
        )
        res = engine.evaluate(req)
        assert res.allowed is False
        assert res.state == PermissionState.approval
        assert res.prompt_user is True


# ===========================================================================
# TC-5.3: Task-Scoped Session Approvals (ADR-012)
# ===========================================================================

class TestTC53TaskScopedSessionApprovals:
    def test_non_destructive_session_approval_grant_and_evaluation(self, tmp_path):
        engine = WardenEngine(tmp_path)
        task_id = "task-456"

        req = PermissionRequest(
            agent="codex",
            action_category=ActionCategory.write_source,
            description="Modify main.py",
            task_id=task_id,
        )
        # Initial evaluation requires approval
        res1 = engine.evaluate(req)
        assert res1.prompt_user is True

        # Grant session approval for write_source on task-456
        assert engine.grant_session_approval(task_id, ActionCategory.write_source) is True

        # Subsequent evaluation on task-456 is allowed automatically
        res2 = engine.evaluate(req)
        assert res2.allowed is True
        assert res2.state == PermissionState.allow

        # Different task_id still requires prompt
        req_other = PermissionRequest(
            agent="codex",
            action_category=ActionCategory.write_source,
            description="Modify main.py",
            task_id="task-999",
        )
        res3 = engine.evaluate(req_other)
        assert res3.allowed is False

    def test_revoke_task_approvals(self, tmp_path):
        engine = WardenEngine(tmp_path)
        task_id = "task-789"
        engine.grant_session_approval(task_id, ActionCategory.write_source)

        req = PermissionRequest(
            agent="codex",
            action_category=ActionCategory.write_source,
            description="Modify main.py",
            task_id=task_id,
        )
        assert engine.evaluate(req).allowed is True

        # When task finishes, revoke task approvals
        engine.revoke_task_approvals(task_id)
        assert engine.evaluate(req).allowed is False


# ===========================================================================
# TC-5.4: Audit Trail Logging (ADR-003)
# ===========================================================================

class TestTC54AuditTrailLogging:
    def test_log_warden_evaluation_records_events(self, tmp_path):
        mem = Memory(tmp_path)
        req = PermissionRequest(
            agent="codex",
            action_category=ActionCategory.git_push,
            description="git push origin main",
            task_id="task-001",
        )

        res_prompt = PermissionResult(
            allowed=False,
            state=PermissionState.approval,
            reason="Prompt required",
            prompt_user=True,
            task_id="task-001",
        )
        log_warden_evaluation(mem, req, res_prompt)

        res_allow = PermissionResult(
            allowed=True,
            state=PermissionState.allow,
            reason="Allowed",
            prompt_user=False,
            task_id="task-001",
        )
        log_warden_evaluation(mem, req, res_allow)

        events = mem.read_events()
        assert len(events) == 2
        assert events[0]["event_type"] == EventType.warden_prompt.value
        assert events[1]["event_type"] == EventType.warden_allow.value
        assert events[0]["agent"] == "codex"
        assert events[0]["task_id"] == "task-001"

    def test_agent_check_warden_permission_logs_audit_trail(self, tmp_path):
        # Create nexus structure first
        nexus_dir = tmp_path / ".nexus"
        nexus_dir.mkdir()

        agent = CodexAgent()
        res = agent.check_warden_permission(
            ActionCategory.execute_commands,
            "npm test",
            task_id="task-002",
            cwd=tmp_path,
        )
        assert res.state == PermissionState.approval

        mem = Memory(tmp_path)
        events = mem.read_events()
        assert len(events) >= 1
        assert events[-1]["agent"] == "codex"


# ===========================================================================
# TC-5.5: CLI Commands (`nexus warden` & `nexus warden set`)
# ===========================================================================

class TestTC55WardenCLICommands:
    def test_cli_warden_matrix_command(self):
        result = runner.invoke(app, ["warden"])
        assert result.exit_code == 0
        assert "Warden Security Policy & Permission Matrix" in result.output
        assert "codex" in result.output

    def test_cli_warden_set_command(self, tmp_path):
        # Init nexus first
        nexus_dir = tmp_path / ".nexus"
        nexus_dir.mkdir()

        result = runner.invoke(app, ["warden", "set", "codex", "read_source", "allow", "-p", str(tmp_path)])
        assert result.exit_code == 0
        assert "Updated Permission" in result.output
        assert "codex" in result.output
        assert "read_source" in result.output
        assert "allow" in result.output

        # Verify permissions.json was updated
        engine = WardenEngine(tmp_path)
        perms = engine.load_permissions()
        assert perms["codex"]["read_source"] == "allow"

    def test_cli_warden_set_invalid_agent_fails(self):
        result = runner.invoke(app, ["warden", "set", "invalid_agent", "git_push", "allow"])
        assert result.exit_code != 0
        assert "Unknown agent" in result.output

    def test_cli_warden_set_invalid_action_fails(self):
        result = runner.invoke(app, ["warden", "set", "codex", "invalid_action", "allow"])
        assert result.exit_code != 0
        assert "Unknown action" in result.output

    def test_cli_warden_set_invalid_state_fails(self):
        result = runner.invoke(app, ["warden", "set", "codex", "git_push", "invalid_state"])
        assert result.exit_code != 0
        assert "Unknown state" in result.output

    def test_shell_dispatch_warden_commands(self, tmp_path):
        from nexus.cli.main import _dispatch_shell_line
        # Dispatch warden from shell loop
        assert _dispatch_shell_line("warden") is True
        assert _dispatch_shell_line(f"warden set codex execute_commands allow") is True
