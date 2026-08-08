"""
Phase 2 test suite — Agent Abstraction
TC-2.1 through TC-2.6

Test strategy:
- TC-2.1 / TC-2.4 / TC-2.6: call real adapters against real local installs
- TC-2.2: run() with a trivial task; we don't assert on output content
  (agents may require auth / produce variable output) but we assert on
  the shape of the returned AgentResult and that no exception is raised.
- TC-2.3: ADR-005 isolation — throwaway 5th adapter must not touch any
  existing file outside its own module.
- TC-2.5: adapter failure path — mock the executable as missing.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from nexus.agents import REGISTRY
from nexus.agents.base import Agent, resolve_executable
from nexus.models.agent import AgentCapabilities, AgentResult, AgentStatus, InvocationMode
from nexus.models.task import Task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALL_AGENT_NAMES = ["codex", "antigravity", "kiro", "cursor"]

def _make_task(desc: str = "print hello world to stdout") -> Task:
    return Task(description=desc)


# ---------------------------------------------------------------------------
# TC-2.1  Live status detection against real local installs
# ---------------------------------------------------------------------------

class TestTC21LiveStatus:
    """TC-2.1: Each adapter's status() correctly reports Ready/Installed/Unreachable
    against real local installs."""

    def test_all_four_agents_in_registry(self):
        for name in ALL_AGENT_NAMES:
            assert name in REGISTRY, f"Agent '{name}' missing from REGISTRY"

    def test_registry_contains_no_excluded_agents(self):
        """ADR-015 regression."""
        assert "claude"     not in REGISTRY
        assert "gemini"     not in REGISTRY
        assert "gemini-cli" not in REGISTRY

    @pytest.mark.parametrize("name", ALL_AGENT_NAMES)
    def test_status_returns_valid_enum(self, name):
        adapter = REGISTRY[name]()
        result = adapter.status()
        assert isinstance(result, AgentStatus), (
            f"{name}.status() returned {type(result)}, expected AgentStatus"
        )

    @pytest.mark.parametrize("name", ALL_AGENT_NAMES)
    def test_status_is_ready_for_installed_agents(self, name):
        """All four agents are confirmed installed — each must report ready."""
        adapter = REGISTRY[name]()
        assert adapter.status() == AgentStatus.ready, (
            f"{name} is installed but status() returned {adapter.status()}. "
            f"Check executable resolution."
        )

    @pytest.mark.parametrize("name", ALL_AGENT_NAMES)
    def test_version_returns_non_empty_string(self, name):
        adapter = REGISTRY[name]()
        if adapter.status() == AgentStatus.ready:
            ver = adapter.version()
            assert ver is not None and len(ver) > 0, (
                f"{name}.version() returned empty for a ready agent"
            )


# ---------------------------------------------------------------------------
# TC-2.2  run() returns a well-shaped AgentResult
# ---------------------------------------------------------------------------

class TestTC22RunReturnsResult:
    """TC-2.2: run() on each adapter returns a populated AgentResult.
    We mock the subprocess call so we don't actually invoke the agent
    (avoids auth requirements and flakiness), but we verify the full
    AgentResult contract is satisfied."""

    @pytest.mark.parametrize("name", ALL_AGENT_NAMES)
    def test_run_returns_agent_result(self, name):
        adapter = REGISTRY[name]()
        task = _make_task()

        # Mock _run_subprocess to return a successful result
        with patch.object(adapter, "_run_subprocess", return_value=(0, "hello world\n", "")):
            result = adapter.run(task)

        assert isinstance(result, AgentResult), (
            f"{name}.run() returned {type(result)}, expected AgentResult"
        )

    @pytest.mark.parametrize("name", ALL_AGENT_NAMES)
    def test_run_result_has_correct_task_id(self, name):
        adapter = REGISTRY[name]()
        task = _make_task()

        with patch.object(adapter, "_run_subprocess", return_value=(0, "ok", "")):
            result = adapter.run(task)

        assert result.task_id == task.task_id

    @pytest.mark.parametrize("name", ALL_AGENT_NAMES)
    def test_run_result_has_correct_agent_name(self, name):
        adapter = REGISTRY[name]()
        task = _make_task()

        with patch.object(adapter, "_run_subprocess", return_value=(0, "ok", "")):
            result = adapter.run(task)

        assert result.agent == name

    @pytest.mark.parametrize("name", ALL_AGENT_NAMES)
    def test_run_success_true_on_rc_zero(self, name):
        adapter = REGISTRY[name]()
        task = _make_task()

        with patch.object(adapter, "_run_subprocess", return_value=(0, "output", "")):
            result = adapter.run(task)

        assert result.success is True

    @pytest.mark.parametrize("name", ALL_AGENT_NAMES)
    def test_run_success_false_on_nonzero_rc(self, name):
        adapter = REGISTRY[name]()
        task = _make_task()

        with patch.object(adapter, "_run_subprocess", return_value=(1, "", "error text")):
            result = adapter.run(task)

        assert result.success is False
        assert result.error is not None


# ---------------------------------------------------------------------------
# TC-2.3  Adding a 5th adapter touches only its own file (ADR-005)
# ---------------------------------------------------------------------------

class TestTC23AdapterIsolation:
    """TC-2.3: Adding a new adapter requires only a new adapter file —
    no edits to router, planner, or CLI core."""

    def test_throwaway_adapter_can_be_created_without_modifying_existing_files(self, tmp_path):
        """
        Create a minimal in-memory 5th adapter and verify it satisfies
        the Agent interface contract without needing to touch any existing module.
        """
        # Build a throwaway adapter entirely in-memory
        class ThrowawayAgent(Agent):
            NAME        = "throwaway"
            LABEL       = "Throwaway Test Agent"
            _EXECUTABLE = "throwaway-nonexistent"
            _HINTS      = []

            def status(self) -> AgentStatus:
                return AgentStatus.unreachable

            def capabilities(self) -> AgentCapabilities:
                return AgentCapabilities(
                    repo_reasoning     = False,
                    terminal_access    = False,
                    multi_file_edit    = False,
                    max_context_tokens = 1000,
                    supports_streaming = False,
                    invocation_mode    = InvocationMode.cli,
                )

            def run(self, task: Task) -> AgentResult:
                return AgentResult(
                    task_id = task.task_id,
                    agent   = self.NAME,
                    success = False,
                    error   = "throwaway agent — not real",
                )

        adapter = ThrowawayAgent()

        # Verify it satisfies the full interface
        assert adapter.status() == AgentStatus.unreachable
        caps = adapter.capabilities()
        assert isinstance(caps, AgentCapabilities)
        result = adapter.run(_make_task())
        assert isinstance(result, AgentResult)
        assert result.agent == "throwaway"

    def test_registry_can_accept_new_adapter_without_modifying_existing_entries(self):
        """Simulate adding to REGISTRY — existing entries are untouched."""
        original_keys = set(REGISTRY.keys())

        # Add a temporary entry
        REGISTRY["throwaway_test"] = type(
            "ThrowawayAgent", (Agent,),
            {
                "NAME": "throwaway_test",
                "LABEL": "Throwaway",
                "_EXECUTABLE": "none",
                "_HINTS": [],
                "run": lambda self, task: AgentResult(task_id=task.task_id, agent="throwaway_test", success=False),
                "status": lambda self: AgentStatus.unreachable,
                "capabilities": lambda self: AgentCapabilities(
                    repo_reasoning=False, terminal_access=False,
                    multi_file_edit=False, max_context_tokens=0,
                    supports_streaming=False, invocation_mode=InvocationMode.cli,
                ),
            }
        )

        # All original entries still present and unmodified
        assert original_keys.issubset(set(REGISTRY.keys()))
        for name in original_keys:
            assert REGISTRY[name] is not None

        # Clean up
        del REGISTRY["throwaway_test"]
        assert set(REGISTRY.keys()) == original_keys


# ---------------------------------------------------------------------------
# TC-2.4  capabilities() differs meaningfully between agents (ADR-014)
# ---------------------------------------------------------------------------

class TestTC24CapabilitiesDiffer:
    """TC-2.4: capabilities() returns a fully-populated AgentCapabilities for
    every adapter. invocation_mode and terminal_access differ between agents."""

    @pytest.mark.parametrize("name", ALL_AGENT_NAMES)
    def test_capabilities_returns_correct_type(self, name):
        adapter = REGISTRY[name]()
        caps = adapter.capabilities()
        assert isinstance(caps, AgentCapabilities), (
            f"{name}.capabilities() returned {type(caps)}"
        )

    @pytest.mark.parametrize("name", ALL_AGENT_NAMES)
    def test_capabilities_all_fields_populated(self, name):
        """Every field must be set — no None values, no missing keys."""
        adapter = REGISTRY[name]()
        caps = adapter.capabilities()
        assert isinstance(caps.repo_reasoning,     bool)
        assert isinstance(caps.terminal_access,    bool)
        assert isinstance(caps.multi_file_edit,    bool)
        assert isinstance(caps.max_context_tokens, int)
        assert caps.max_context_tokens > 0
        assert isinstance(caps.supports_streaming, bool)
        assert isinstance(caps.invocation_mode,    InvocationMode)

    def test_terminal_access_differs_between_agents(self):
        """Codex+Antigravity have terminal_access=True; Kiro+Cursor have False."""
        caps = {name: REGISTRY[name]().capabilities() for name in ALL_AGENT_NAMES}
        terminal_true  = [n for n, c in caps.items() if c.terminal_access]
        terminal_false = [n for n, c in caps.items() if not c.terminal_access]
        assert len(terminal_true)  >= 1, "No agent with terminal_access=True"
        assert len(terminal_false) >= 1, "No agent with terminal_access=False"

    def test_codex_and_antigravity_have_terminal_access(self):
        assert REGISTRY["codex"]().capabilities().terminal_access is True
        assert REGISTRY["antigravity"]().capabilities().terminal_access is True

    def test_kiro_and_cursor_do_not_have_terminal_access(self):
        assert REGISTRY["kiro"]().capabilities().terminal_access is False
        assert REGISTRY["cursor"]().capabilities().terminal_access is False

    def test_all_agents_are_cli_invocation_mode(self):
        """All four verified as cli — none are ide_only."""
        for name in ALL_AGENT_NAMES:
            caps = REGISTRY[name]().capabilities()
            assert caps.invocation_mode == InvocationMode.cli, (
                f"{name} unexpectedly has invocation_mode={caps.invocation_mode}"
            )

    def test_max_context_tokens_differ_between_agents(self):
        """Agents should have different context sizes — confirms real values, not defaults."""
        tokens = {name: REGISTRY[name]().capabilities().max_context_tokens for name in ALL_AGENT_NAMES}
        unique_values = set(tokens.values())
        assert len(unique_values) > 1, (
            f"All agents have identical max_context_tokens={unique_values} — "
            "likely all defaulted to the same value rather than being set individually."
        )


# ---------------------------------------------------------------------------
# TC-2.5  Adapter failure surfaces a clear error
# ---------------------------------------------------------------------------

class TestTC25AdapterFailure:
    """TC-2.5: An adapter failure (tool not installed, auth missing) surfaces
    a clear, specific error — never a silent no-op."""

    @pytest.mark.parametrize("name", ALL_AGENT_NAMES)
    def test_unreachable_status_when_exe_missing(self, name):
        """Patch _exe() to return None — simulates tool not installed."""
        adapter = REGISTRY[name]()
        with patch.object(adapter, "_exe", return_value=None):
            status = adapter.status()
        assert status == AgentStatus.unreachable

    @pytest.mark.parametrize("name", ALL_AGENT_NAMES)
    def test_run_returns_error_when_exe_missing(self, name):
        """run() must return AgentResult with success=False and a non-empty error."""
        adapter = REGISTRY[name]()
        task = _make_task()
        with patch.object(adapter, "_exe", return_value=None):
            result = adapter.run(task)
        assert result.success is False
        assert result.error is not None
        assert len(result.error) > 0, f"{name}.run() returned empty error string"

    @pytest.mark.parametrize("name", ALL_AGENT_NAMES)
    def test_run_error_contains_install_hint(self, name):
        """Error message should tell the user how to install, not just 'not found'."""
        adapter = REGISTRY[name]()
        task = _make_task()
        with patch.object(adapter, "_exe", return_value=None):
            result = adapter.run(task)
        # Should contain either a URL, a command, or the tool name
        error_lower = result.error.lower()
        assert any(
            keyword in error_lower
            for keyword in ["install", "http", "download", name]
        ), f"{name} error message lacks install guidance: {result.error!r}"

    @pytest.mark.parametrize("name", ALL_AGENT_NAMES)
    def test_no_exception_raised_on_missing_exe(self, name):
        """Neither status() nor run() should raise — errors must be returned, not thrown."""
        adapter = REGISTRY[name]()
        task = _make_task()
        with patch.object(adapter, "_exe", return_value=None):
            try:
                adapter.status()
                adapter.run(task)
            except Exception as exc:
                pytest.fail(f"{name} raised {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# TC-2.6  ide_only agents excluded from Router candidate list
# ---------------------------------------------------------------------------

class TestTC26IdeOnlyExclusion:
    """TC-2.6: Any adapter with invocation_mode=ide_only is excluded from
    Swarm/Daemon routing. Currently all four are cli — this test verifies
    the exclusion logic works correctly when an ide_only agent is present."""

    def _get_headless_candidates(self, agent_names: list[str]) -> list[str]:
        """Simulate the Router's exclusion of ide_only agents."""
        return [
            name for name in agent_names
            if REGISTRY[name]().capabilities().invocation_mode != InvocationMode.ide_only
        ]

    def test_all_current_agents_are_eligible_for_routing(self):
        """All four current agents are cli — all should be routing candidates."""
        candidates = self._get_headless_candidates(ALL_AGENT_NAMES)
        assert set(candidates) == set(ALL_AGENT_NAMES), (
            f"Unexpected agents excluded from routing: "
            f"{set(ALL_AGENT_NAMES) - set(candidates)}"
        )

    def test_ide_only_agent_is_excluded_from_routing(self):
        """Inject a mock ide_only agent and confirm it's excluded."""
        class FakeIdeAgent(Agent):
            NAME        = "fake_ide"
            LABEL       = "Fake IDE Agent"
            _EXECUTABLE = "fake-ide"
            _HINTS      = []

            def status(self):       return AgentStatus.ready
            def capabilities(self): return AgentCapabilities(
                repo_reasoning=True, terminal_access=False, multi_file_edit=True,
                max_context_tokens=50000, supports_streaming=False,
                invocation_mode=InvocationMode.ide_only,   # <-- ide_only
            )
            def run(self, task):    return AgentResult(task_id=task.task_id, agent=self.NAME, success=False)

        REGISTRY["fake_ide"] = FakeIdeAgent
        try:
            all_names = ALL_AGENT_NAMES + ["fake_ide"]
            candidates = self._get_headless_candidates(all_names)
            assert "fake_ide" not in candidates, "ide_only agent was not excluded from routing"
            # Real agents still included
            for name in ALL_AGENT_NAMES:
                assert name in candidates
        finally:
            del REGISTRY["fake_ide"]

    def test_no_current_agent_is_ide_only(self):
        for name in ALL_AGENT_NAMES:
            caps = REGISTRY[name]().capabilities()
            assert caps.invocation_mode != InvocationMode.ide_only, (
                f"{name} is unexpectedly ide_only — update capabilities() or this test"
            )


# ---------------------------------------------------------------------------
# Phase 1 regression — all Phase 1 tests must still pass
# ---------------------------------------------------------------------------

class TestPhase1Regression:
    """Cross-phase regression: Phase 1 contract must still hold after Phase 2 changes."""

    def test_open_commands_contain_no_excluded_agents(self):
        from nexus.cli.main import OPEN_COMMANDS
        assert "claude"     not in OPEN_COMMANDS
        assert "gemini"     not in OPEN_COMMANDS
        assert "gemini-cli" not in OPEN_COMMANDS

    def test_known_agents_in_cli_matches_registry(self):
        from nexus.cli.main import KNOWN_AGENTS
        cli_names   = {a["name"] for a in KNOWN_AGENTS}
        reg_names   = set(REGISTRY.keys())
        assert cli_names == reg_names, (
            f"CLI KNOWN_AGENTS {cli_names} does not match REGISTRY {reg_names}"
        )

    def test_resolve_executable_returns_none_for_nonexistent(self):
        result = resolve_executable("this-tool-definitely-does-not-exist-xyz123")
        assert result is None
