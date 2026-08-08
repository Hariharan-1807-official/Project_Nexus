"""
Phase 1 test suite — CLI Core + Universal Launcher
TC-1.1 through TC-1.5
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nexus.cli.main import app, KNOWN_AGENTS, OPEN_COMMANDS
from nexus.core.scaffold import init_project, _REQUIRED_DIRS, _DEFAULT_FILES

runner = CliRunner(mix_stderr=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _nexus_dir_contents(project_root: Path) -> set[str]:
    """Return all paths under .nexus/ relative to project_root."""
    nexus = project_root / ".nexus"
    return {
        str(p.relative_to(project_root)).replace("\\", "/")
        for p in nexus.rglob("*")
    }


# ---------------------------------------------------------------------------
# TC-1.1  nexus init creates the full .nexus/ structure
# ---------------------------------------------------------------------------

class TestTC11InitCreatesStructure:
    """TC-1.1: nexus init in an empty directory creates the full .nexus/ folder
    structure exactly as specified in the architecture doc."""

    def test_all_required_dirs_created(self, tmp_path):
        init_project(tmp_path)
        for rel_dir in _REQUIRED_DIRS:
            assert (tmp_path / rel_dir).is_dir(), f"Missing directory: {rel_dir}"

    def test_all_default_files_created(self, tmp_path):
        init_project(tmp_path)
        for rel_path in _DEFAULT_FILES:
            assert (tmp_path / rel_path).exists(), f"Missing file: {rel_path}"

    def test_config_files_are_valid_json_or_empty(self, tmp_path):
        init_project(tmp_path)
        json_files = [p for p in _DEFAULT_FILES if p.endswith(".json")]
        for rel_path in json_files:
            content = (tmp_path / rel_path).read_text(encoding="utf-8").strip()
            if content:  # non-empty files must be valid JSON
                parsed = json.loads(content)   # raises if invalid
                assert isinstance(parsed, (dict, list))

    def test_agents_json_contains_four_agents(self, tmp_path):
        init_project(tmp_path)
        agents_json = tmp_path / ".nexus" / "config" / "agents.json"
        data = json.loads(agents_json.read_text(encoding="utf-8"))
        assert len(data["agents"]) == 4
        names = {a["name"] for a in data["agents"]}
        assert names == {"codex", "antigravity", "kiro", "cursor"}

    def test_permissions_json_has_no_excluded_agents(self, tmp_path):
        """ADR-015 regression: claude and gemini must not appear in permissions."""
        init_project(tmp_path)
        perms = json.loads(
            (tmp_path / ".nexus" / "config" / "permissions.json")
            .read_text(encoding="utf-8")
        )
        assert "claude"  not in perms, "claude found in permissions.json — ADR-015 violation"
        assert "gemini"  not in perms, "gemini found in permissions.json — ADR-015 violation"

    def test_router_json_default_agent_is_codex(self, tmp_path):
        """System Architecture §6a: default_agent must be codex."""
        init_project(tmp_path)
        router = json.loads(
            (tmp_path / ".nexus" / "config" / "router.json")
            .read_text(encoding="utf-8")
        )
        assert router["default_agent"] == "codex"

    def test_daemon_json_defaults_to_disabled(self, tmp_path):
        """System Architecture §9 / TC-7.0 pre-check: daemon off by default."""
        init_project(tmp_path)
        daemon = json.loads(
            (tmp_path / ".nexus" / "config" / "daemon.json")
            .read_text(encoding="utf-8")
        )
        assert daemon["global"]["enabled"] is False
        assert daemon["global"]["auto_fix_attempt"] is False

    def test_cli_init_command_succeeds(self, tmp_path):
        result = runner.invoke(app, ["init", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert (tmp_path / ".nexus").is_dir()


# ---------------------------------------------------------------------------
# TC-1.2  nexus init is idempotent — never overwrites existing data
# ---------------------------------------------------------------------------

class TestTC12InitIdempotent:
    """TC-1.2: nexus init run a second time does not overwrite existing
    context.json or task history."""

    def test_existing_context_json_not_overwritten(self, tmp_path):
        init_project(tmp_path)
        context_file = tmp_path / ".nexus" / "project" / "context.json"
        sentinel = '{"stack": "test-sentinel"}'
        context_file.write_text(sentinel, encoding="utf-8")

        init_project(tmp_path)  # second call

        assert context_file.read_text(encoding="utf-8") == sentinel

    def test_existing_agents_json_not_overwritten(self, tmp_path):
        init_project(tmp_path)
        agents_file = tmp_path / ".nexus" / "config" / "agents.json"
        custom = '{"agents": [{"name": "custom", "enabled": true}]}'
        agents_file.write_text(custom, encoding="utf-8")

        init_project(tmp_path)

        assert agents_file.read_text(encoding="utf-8") == custom

    def test_second_init_reports_nothing_overwritten(self, tmp_path):
        init_project(tmp_path)
        already_existed, created = init_project(tmp_path)
        assert already_existed is True
        assert created == [], f"Unexpected files created on second init: {created}"

    def test_cli_second_init_exit_code_zero(self, tmp_path):
        runner.invoke(app, ["init", str(tmp_path)])
        result = runner.invoke(app, ["init", str(tmp_path)])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# TC-1.3  nexus open
# ---------------------------------------------------------------------------

class TestTC13NexusOpen:
    """TC-1.3: nexus open <known> does not crash; nexus open <unknown> exits
    with a clear error message, not a stack trace."""

    def test_open_unknown_tool_exits_nonzero(self):
        result = runner.invoke(app, ["open", "doesnotexist"])
        assert result.exit_code != 0

    def test_open_unknown_tool_error_message_is_human_readable(self):
        result = runner.invoke(app, ["open", "doesnotexist"])
        output = result.output
        assert "doesnotexist" in output.lower() or "unknown" in output.lower()
        # Must not be a raw Python traceback
        assert "Traceback" not in output
        assert "traceback" not in output

    def test_open_unknown_tool_lists_known_agents(self):
        result = runner.invoke(app, ["open", "doesnotexist"])
        # Should hint at valid options
        output = result.output
        assert any(name in output for name in OPEN_COMMANDS.keys())

    def test_open_all_known_agents_are_in_open_commands(self):
        """Every agent in KNOWN_AGENTS must have an entry in OPEN_COMMANDS."""
        for agent in KNOWN_AGENTS:
            assert agent["name"] in OPEN_COMMANDS, (
                f"Agent '{agent['name']}' missing from OPEN_COMMANDS"
            )

    def test_open_commands_contain_no_excluded_agents(self):
        """ADR-015 regression: claude and gemini-cli must not appear."""
        assert "claude"     not in OPEN_COMMANDS
        assert "gemini"     not in OPEN_COMMANDS
        assert "gemini-cli" not in OPEN_COMMANDS


# ---------------------------------------------------------------------------
# TC-1.4  Interactive shell command equivalence
# ---------------------------------------------------------------------------

class TestTC14ShellEquivalence:
    """TC-1.4: Inside the shell, 'agents' and 'nexus agents' are equivalent."""

    def test_shell_dispatches_agents(self):
        from nexus.cli.main import _dispatch_shell_line
        # Capture: just verify no exception and returns True (continue)
        result = _dispatch_shell_line("agents")
        assert result is True

    def test_shell_dispatches_nexus_agents(self):
        from nexus.cli.main import _dispatch_shell_line
        result = _dispatch_shell_line("nexus agents")
        assert result is True

    def test_shell_exit_returns_false(self):
        from nexus.cli.main import _dispatch_shell_line
        assert _dispatch_shell_line("exit") is False

    def test_shell_quit_returns_false(self):
        from nexus.cli.main import _dispatch_shell_line
        assert _dispatch_shell_line("quit") is False

    def test_shell_nexus_exit_returns_false(self):
        from nexus.cli.main import _dispatch_shell_line
        assert _dispatch_shell_line("nexus exit") is False

    def test_shell_empty_line_returns_true(self):
        from nexus.cli.main import _dispatch_shell_line
        assert _dispatch_shell_line("") is True
        assert _dispatch_shell_line("   ") is True

    def test_shell_help_returns_true(self):
        from nexus.cli.main import _dispatch_shell_line
        assert _dispatch_shell_line("help") is True

    def test_shell_unknown_command_returns_true_no_crash(self):
        """Unknown commands return True (keep running) and don't crash."""
        from nexus.cli.main import _dispatch_shell_line
        result = _dispatch_shell_line("some random natural language thing")
        assert result is True


# ---------------------------------------------------------------------------
# TC-1.5  Help output
# ---------------------------------------------------------------------------

class TestTC15HelpOutput:
    """TC-1.5: nexus --help and per-command --help output correct usage."""

    def test_root_help_exits_zero(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0

    def test_root_help_lists_all_commands(self):
        result = runner.invoke(app, ["--help"])
        output = result.output
        assert "init"   in output
        assert "agents" in output
        assert "open"   in output

    def test_init_help_exits_zero(self):
        result = runner.invoke(app, ["init", "--help"])
        assert result.exit_code == 0

    def test_agents_help_exits_zero(self):
        result = runner.invoke(app, ["agents", "--help"])
        assert result.exit_code == 0

    def test_open_help_exits_zero(self):
        result = runner.invoke(app, ["open", "--help"])
        assert result.exit_code == 0

    def test_open_help_mentions_agent_names(self):
        result = runner.invoke(app, ["open", "--help"])
        output = result.output
        assert "codex" in output.lower() or "agent" in output.lower()
