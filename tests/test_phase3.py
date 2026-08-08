"""
Phase 3 test suite — Project Intelligence + Shared Memory
TC-3.1 through TC-3.5
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from nexus.cli.main import app
from nexus.core.scaffold import init_project
from nexus.core.intelligence.scanner import scan_project, scan_and_write
from nexus.core.intelligence.health import (
    run_health_checks, CheckStatus, HealthReport,
    _check_git, _check_tests, _check_dependencies,
)
from nexus.core.intelligence.status import get_status, explain_project
from nexus.core.memory import Memory, EventType

runner = CliRunner(mix_stderr=False)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def nexus_project(tmp_path: Path) -> Path:
    """A tmp dir with .nexus/ initialised."""
    init_project(tmp_path)
    return tmp_path


@pytest.fixture()
def python_project(tmp_path: Path) -> Path:
    """A minimal Python project with .nexus/ and a pyproject.toml."""
    init_project(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\n\n[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def hello(): return 'hello'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_hello.py").write_text(
        "from src.main import hello\ndef test_hello(): assert hello() == 'hello'\n",
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text("pydantic>=2\n", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def react_project(tmp_path: Path) -> Path:
    """A minimal React/Node project."""
    init_project(tmp_path)
    pkg = {
        "name": "test-app",
        "version": "1.0.0",
        "dependencies": {"react": "^18.0.0", "react-dom": "^18.0.0"},
        "devDependencies": {"typescript": "^5.0.0"},
        "scripts": {"build": "echo built", "test": "echo tested"},
    }
    (tmp_path / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.tsx").write_text("export default function App() { return null; }\n", encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# TC-3.1  nexus scan identifies stack, frameworks, structure
# ---------------------------------------------------------------------------

class TestTC31Scan:
    """TC-3.1: nexus scan on a real project correctly identifies stack,
    frameworks, and structure."""

    def test_scan_python_project_detects_language(self, python_project):
        ctx = scan_project(python_project)
        assert "Python" in ctx["languages"], f"Python not detected. languages={ctx['languages']}"

    def test_scan_python_project_detects_frameworks(self, python_project):
        ctx = scan_project(python_project)
        # pydantic is in requirements.txt
        assert "Pydantic" in ctx["frameworks"], f"Pydantic not detected. frameworks={ctx['frameworks']}"

    def test_scan_python_project_detects_structure(self, python_project):
        ctx = scan_project(python_project)
        assert ctx["structure"]["has_tests"] is True
        assert ctx["structure"]["file_count"] > 0
        assert "src" in ctx["structure"]["top_level_dirs"] or "tests" in ctx["structure"]["top_level_dirs"]

    def test_scan_react_project_detects_language(self, react_project):
        ctx = scan_project(react_project)
        assert "TypeScript" in ctx["languages"] or "JavaScript" in ctx["languages"]

    def test_scan_react_project_detects_framework(self, react_project):
        ctx = scan_project(react_project)
        assert "React" in ctx["frameworks"], f"React not detected. frameworks={ctx['frameworks']}"

    def test_scan_returns_scanned_at_timestamp(self, python_project):
        ctx = scan_project(python_project)
        assert "scanned_at" in ctx
        assert "T" in ctx["scanned_at"]   # ISO format

    def test_scan_and_write_creates_context_json(self, nexus_project):
        scan_and_write(nexus_project)
        ctx_path = nexus_project / ".nexus" / "project" / "context.json"
        assert ctx_path.exists()
        data = json.loads(ctx_path.read_text(encoding="utf-8"))
        assert "languages" in data
        assert "frameworks" in data
        assert "structure" in data

    def test_scan_and_write_requires_nexus_init(self, tmp_path):
        """scan_and_write must raise if .nexus/ doesn't exist."""
        with pytest.raises(FileNotFoundError):
            scan_and_write(tmp_path)

    def test_cli_scan_command_succeeds(self, nexus_project):
        result = runner.invoke(app, ["scan", str(nexus_project)])
        assert result.exit_code == 0, result.output
        assert "Scan complete" in result.output

    def test_cli_scan_writes_context_json(self, nexus_project):
        runner.invoke(app, ["scan", str(nexus_project)])
        ctx_path = nexus_project / ".nexus" / "project" / "context.json"
        assert ctx_path.exists()

    def test_cli_scan_logs_event_to_memory(self, nexus_project):
        runner.invoke(app, ["scan", str(nexus_project)])
        mem = Memory(nexus_project)
        events = mem.read_events(event_type=EventType.scan)
        assert len(events) >= 1
        assert events[-1]["action"] == "nexus scan"

    def test_cli_scan_without_init_exits_nonzero(self, tmp_path):
        result = runner.invoke(app, ["scan", str(tmp_path)])
        assert result.exit_code != 0

    def test_nexus_project_scan_detects_python_and_typer(self):
        """Smoke: scan the actual Nexus project (has pyproject.toml, Typer, Pydantic)."""
        from pathlib import Path
        project_root = Path(__file__).parent.parent
        ctx = scan_project(project_root)
        assert "Python" in ctx["languages"]
        assert "Typer" in ctx["frameworks"] or "Pydantic" in ctx["frameworks"]


# ---------------------------------------------------------------------------
# TC-3.2  nexus health flags a broken build
# ---------------------------------------------------------------------------

class TestTC32Health:
    """TC-3.2: nexus health correctly flags a deliberately broken build."""

    def test_health_returns_health_report(self, python_project):
        report = run_health_checks(python_project)
        assert isinstance(report, HealthReport)

    def test_health_has_expected_check_names(self, python_project):
        report = run_health_checks(python_project)
        names = {c.name for c in report.checks}
        assert "git"          in names
        assert "build"        in names
        assert "tests"        in names
        assert "dependencies" in names
        assert "docker"       in names

    def test_health_flags_syntax_error(self, python_project):
        """Introduce a syntax error and confirm build check fails."""
        bad_file = python_project / "src" / "broken.py"
        bad_file.write_text("def broken(\n    # unclosed parenthesis\n", encoding="utf-8")
        report = run_health_checks(python_project)
        build_check = next(c for c in report.checks if c.name == "build")
        assert build_check.status == CheckStatus.fail, (
            f"Syntax error not detected. build check: {build_check.summary}"
        )

    def test_health_overall_fail_when_build_fails(self, python_project):
        bad_file = python_project / "src" / "broken2.py"
        bad_file.write_text("def bad(\n", encoding="utf-8")
        report = run_health_checks(python_project)
        assert report.overall == CheckStatus.fail

    def test_health_ok_when_no_issues(self, python_project):
        report = run_health_checks(python_project)
        build = next(c for c in report.checks if c.name == "build")
        # With clean files, build should be ok
        assert build.status == CheckStatus.ok

    def test_health_git_skip_when_not_git_repo(self, python_project):
        """tmp_path is not a git repo — git check should skip, not fail."""
        report = run_health_checks(python_project)
        git_check = next(c for c in report.checks if c.name == "git")
        assert git_check.status == CheckStatus.skip

    def test_health_docker_skip_when_not_running(self, python_project):
        report = run_health_checks(python_project)
        docker_check = next(c for c in report.checks if c.name == "docker")
        # Docker not running in test env → skip is the expected result
        assert docker_check.status in (CheckStatus.skip, CheckStatus.ok)

    def test_health_as_dict_structure(self, python_project):
        report = run_health_checks(python_project)
        d = report.as_dict()
        assert "overall" in d
        assert "checks"  in d
        assert all("name" in c and "status" in c and "summary" in c for c in d["checks"])

    def test_cli_health_command_exits_zero(self, nexus_project):
        result = runner.invoke(app, ["health", str(nexus_project)])
        assert result.exit_code == 0, result.output

    def test_cli_health_shows_overall(self, nexus_project):
        result = runner.invoke(app, ["health", str(nexus_project)])
        assert "Overall:" in result.output

    def test_cli_health_logs_event(self, nexus_project):
        runner.invoke(app, ["health", str(nexus_project)])
        mem = Memory(nexus_project)
        events = mem.read_events(event_type=EventType.health_check)
        assert len(events) >= 1


# ---------------------------------------------------------------------------
# TC-3.3  Agents receive context automatically (FR-13)
# ---------------------------------------------------------------------------

class TestTC33ContextAutoInjection:
    """TC-3.3: Two consecutive agent runs both receive the same context.json
    automatically without the user re-explaining."""

    def test_context_json_is_readable_after_scan(self, nexus_project):
        scan_and_write(nexus_project)
        ctx_path = nexus_project / ".nexus" / "project" / "context.json"
        data = json.loads(ctx_path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert "scanned_at" in data

    def test_consecutive_scans_update_context_json(self, nexus_project):
        """Second scan overwrites context.json with a newer timestamp."""
        scan_and_write(nexus_project)
        first_ts = json.loads(
            (nexus_project / ".nexus" / "project" / "context.json").read_text()
        )["scanned_at"]

        import time; time.sleep(0.05)
        scan_and_write(nexus_project)
        second_ts = json.loads(
            (nexus_project / ".nexus" / "project" / "context.json").read_text()
        )["scanned_at"]

        assert second_ts > first_ts, "Second scan did not update context.json timestamp"

    def test_get_status_returns_context(self, nexus_project):
        scan_and_write(nexus_project)
        snap = get_status(nexus_project)
        assert snap["context"] is not None
        assert "languages" in snap["context"]

    def test_get_status_no_error_after_scan(self, nexus_project):
        scan_and_write(nexus_project)
        snap = get_status(nexus_project)
        assert "error" not in snap


# ---------------------------------------------------------------------------
# TC-3.4  events.jsonl is append-only
# ---------------------------------------------------------------------------

class TestTC34AppendOnly:
    """TC-3.4: memory/events.jsonl is append-only — the normal API never
    exposes a way to edit or truncate past entries."""

    def test_log_event_creates_events_file(self, nexus_project):
        mem = Memory(nexus_project)
        mem.log_event(EventType.system, agent=None, action="test", result="ok")
        assert (nexus_project / ".nexus" / "memory" / "events.jsonl").exists()

    def test_each_log_event_appends_a_line(self, nexus_project):
        mem = Memory(nexus_project)
        mem.log_event(EventType.system, agent=None, action="first",  result="ok")
        mem.log_event(EventType.system, agent=None, action="second", result="ok")
        mem.log_event(EventType.system, agent=None, action="third",  result="ok")

        events = mem.read_events()
        assert len(events) == 3
        assert events[0]["action"] == "first"
        assert events[1]["action"] == "second"
        assert events[2]["action"] == "third"

    def test_line_count_only_grows(self, nexus_project):
        mem = Memory(nexus_project)
        path = nexus_project / ".nexus" / "memory" / "events.jsonl"

        mem.log_event(EventType.system, agent=None, action="a", result="ok")
        count_1 = path.read_text().count("\n")

        mem.log_event(EventType.system, agent=None, action="b", result="ok")
        count_2 = path.read_text().count("\n")

        mem.log_event(EventType.system, agent=None, action="c", result="ok")
        count_3 = path.read_text().count("\n")

        assert count_2 > count_1
        assert count_3 > count_2

    def test_memory_api_has_no_delete_or_truncate_method(self):
        """The Memory class must not expose any method that mutates past entries."""
        mem = Memory(Path("."))
        forbidden = ["delete", "truncate", "clear", "reset", "remove", "edit", "update"]
        for method_name in forbidden:
            assert not hasattr(mem, method_name), (
                f"Memory exposes forbidden method: {method_name!r}"
            )

    def test_read_events_returns_all_written_records(self, nexus_project):
        mem = Memory(nexus_project)
        for i in range(5):
            mem.log_event(EventType.agent_action, agent="codex", action=f"action-{i}", result="ok", task_id="t-1")
        events = mem.read_events()
        assert len(events) == 5

    def test_read_events_filter_by_event_type(self, nexus_project):
        mem = Memory(nexus_project)
        mem.log_event(EventType.scan,         agent=None,    action="scan",   result="ok")
        mem.log_event(EventType.agent_action, agent="codex", action="coding", result="ok")
        mem.log_event(EventType.scan,         agent=None,    action="scan2",  result="ok")

        scans = mem.read_events(event_type=EventType.scan)
        assert len(scans) == 2
        assert all(e["event_type"] == "scan" for e in scans)

    def test_read_events_filter_by_agent(self, nexus_project):
        mem = Memory(nexus_project)
        mem.log_event(EventType.agent_action, agent="codex",       action="a", result="ok")
        mem.log_event(EventType.agent_action, agent="antigravity", action="b", result="ok")
        mem.log_event(EventType.agent_action, agent="codex",       action="c", result="ok")

        codex_events = mem.read_events(agent="codex")
        assert len(codex_events) == 2
        assert all(e["agent"] == "codex" for e in codex_events)

    def test_read_events_filter_by_task_id(self, nexus_project):
        mem = Memory(nexus_project)
        mem.log_event(EventType.agent_action, agent="codex", action="x", result="ok", task_id="task-001")
        mem.log_event(EventType.agent_action, agent="codex", action="y", result="ok", task_id="task-002")
        mem.log_event(EventType.agent_action, agent="codex", action="z", result="ok", task_id="task-001")

        t1 = mem.read_events(task_id="task-001")
        assert len(t1) == 2

    def test_events_each_have_required_fields(self, nexus_project):
        mem = Memory(nexus_project)
        mem.log_event(EventType.agent_action, agent="kiro", action="edit", result="ok", task_id="t-42")
        ev = mem.read_events()[-1]
        assert "timestamp"  in ev
        assert "event_type" in ev
        assert "agent"      in ev
        assert "action"     in ev
        assert "task_id"    in ev
        assert "result"     in ev

    def test_log_decision_appears_in_both_logs(self, nexus_project):
        mem = Memory(nexus_project)
        mem.log_decision("Use PostgreSQL for persistence", rationale="team familiarity", task_id="t-5")

        decisions = mem.read_decisions()
        events    = mem.read_events(event_type=EventType.decision)

        assert len(decisions) >= 1
        assert decisions[-1]["description"] == "Use PostgreSQL for persistence"
        assert len(events) >= 1

    def test_log_handoff_appears_in_both_logs(self, nexus_project):
        mem = Memory(nexus_project)
        mem.log_handoff("codex", "antigravity", task_id="t-7", artifact="review.json")

        handoffs = mem.read_handoffs(task_id="t-7")
        events   = mem.read_events(event_type=EventType.handoff)

        assert len(handoffs) == 1
        assert handoffs[0]["from_agent"] == "codex"
        assert handoffs[0]["to_agent"]   == "antigravity"
        assert len(events) >= 1


# ---------------------------------------------------------------------------
# TC-3.5  nexus explain produces accurate human-readable summary
# ---------------------------------------------------------------------------

class TestTC35Explain:
    """TC-3.5: nexus explain after several scans/health checks produces an
    accurate human-readable summary of current project state."""

    def test_explain_mentions_project_name(self, nexus_project):
        scan_and_write(nexus_project)
        narrative = explain_project(nexus_project)
        # Project dir name should appear
        assert nexus_project.name in narrative

    def test_explain_mentions_recent_scan(self, nexus_project):
        scan_and_write(nexus_project)
        mem = Memory(nexus_project)
        mem.log_event(EventType.scan, agent=None, action="nexus scan", result="ok")
        narrative = explain_project(nexus_project)
        assert "scan" in narrative.lower()

    def test_explain_before_scan_suggests_running_scan(self, nexus_project):
        """If context.json is empty/missing, explain should prompt the user to scan."""
        narrative = explain_project(nexus_project)
        assert "scan" in narrative.lower()

    def test_explain_shows_recent_activity(self, nexus_project):
        mem = Memory(nexus_project)
        mem.log_event(EventType.agent_action, agent="codex", action="implement auth", result="ok")
        narrative = explain_project(nexus_project)
        assert "codex" in narrative.lower() or "activity" in narrative.lower()

    def test_explain_returns_string(self, nexus_project):
        result = explain_project(nexus_project)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_cli_explain_exits_zero(self, nexus_project):
        runner.invoke(app, ["scan", str(nexus_project)])
        result = runner.invoke(app, ["explain", str(nexus_project)])
        assert result.exit_code == 0, result.output

    def test_cli_status_exits_zero(self, nexus_project):
        result = runner.invoke(app, ["status", str(nexus_project)])
        assert result.exit_code == 0, result.output

    def test_cli_status_shows_project_name(self, nexus_project):
        result = runner.invoke(app, ["status", str(nexus_project)])
        assert nexus_project.name in result.output

    def test_cli_status_shows_last_scan_after_scan(self, nexus_project):
        runner.invoke(app, ["scan", str(nexus_project)])
        result = runner.invoke(app, ["status", str(nexus_project)])
        assert "ago" in result.output   # time-ago formatting

    def test_cli_status_warns_when_not_scanned(self, nexus_project):
        result = runner.invoke(app, ["status", str(nexus_project)])
        assert "scan" in result.output.lower()


# ---------------------------------------------------------------------------
# Phase 1 + Phase 2 regression
# ---------------------------------------------------------------------------

class TestPhase12Regression:
    def test_phase1_init_still_works(self, tmp_path):
        result = runner.invoke(app, ["init", str(tmp_path)])
        assert result.exit_code == 0

    def test_phase2_agents_command_still_works(self):
        result = runner.invoke(app, ["agents"])
        assert result.exit_code == 0
        assert "ready" in result.output.lower()

    def test_memory_events_have_task_id_field(self, nexus_project):
        """TC-5.6 pre-condition: task_id in every event record."""
        mem = Memory(nexus_project)
        rec = mem.log_event(EventType.agent_action, agent="codex", action="test", result="ok", task_id="task-abc")
        assert "task_id" in rec
        assert rec["task_id"] == "task-abc"
