"""
Phase 4 Test Suite — GitHub, Docker, Diagnostics.

Validates:
- TC-4.1:  nexus issue <n> displays title, labels, recommended agent
- TC-4.2:  nexus investigate <n> produces hypothesis without code changes
- TC-4.2a: nexus solve <n> is NOT present in CLI (ADR-011 negative test)
- TC-4.3:  nexus docker reflects container state
- TC-4.4:  broken docker-compose -> nexus diagnose finds root cause
- TC-4.5:  nexus diagnose output has no numeric confidence score (ADR-006)
- TC-4.6:  nexus pr always stops at confirmation prompt
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from typer.testing import CliRunner

from nexus.cli.main import app
from nexus.core.github import fetch_issue, recommend_agent_for_issue
from nexus.core.docker import list_containers, inspect_compose
from nexus.core.diagnostics import diagnose, _analyze_evidence
from nexus.models.diagnosis import GitHubIssue, DiagnosisArtifact

runner = CliRunner()


# ===========================================================================
# TC-4.1: GitHub Issue Fetch & Agent Recommendation
# ===========================================================================

class TestTC41GitHubIssue:
    def test_recommend_agent_backend_issue(self):
        issue = GitHubIssue(
            number=42,
            title="Database API connection error",
            labels=["backend", "bug"],
        )
        agent, reason = recommend_agent_for_issue(issue)
        assert agent == "codex"
        assert "backend" in reason.lower() or "issue" in reason.lower()

    def test_recommend_agent_frontend_issue(self):
        issue = GitHubIssue(
            number=101,
            title="UI layout shift on mobile component",
            labels=["frontend", "styling"],
        )
        agent, reason = recommend_agent_for_issue(issue)
        assert agent == "antigravity"

    @patch("nexus.core.github.subprocess.run")
    def test_fetch_issue_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "number": 42,
                "title": "Fix auth endpoint crash",
                "body": "API crashes on null token",
                "labels": [{"name": "backend"}],
                "state": "OPEN",
                "assignees": [{"login": "octocat"}],
                "url": "https://github.com/example/repo/issues/42",
            }),
        )
        issue = fetch_issue(42)
        assert issue is not None
        assert issue.number == 42
        assert issue.title == "Fix auth endpoint crash"
        assert "backend" in issue.labels
        assert issue.recommended_agent == "codex"

    @patch("nexus.core.github.gh_installed", return_value=True)
    @patch("nexus.core.github.fetch_issue")
    def test_cli_issue_command_displays_info(self, mock_fetch, mock_gh):
        mock_fetch.return_value = GitHubIssue(
            number=42,
            title="Fix memory leak in scanner",
            body="Memory usage grows linearly",
            labels=["bug"],
            state="OPEN",
            url="https://github.com/example/repo/issues/42",
            recommended_agent="codex",
            recommendation_reason="Matched issue signal",
        )
        result = runner.invoke(app, ["issue", "42"])
        assert result.exit_code == 0
        assert "Issue #42" in result.output
        assert "Fix memory leak in scanner" in result.output
        assert "codex" in result.output


# ===========================================================================
# TC-4.2 & TC-4.2a: Read-only Investigation & Absence of 'solve'
# ===========================================================================

class TestTC42InvestigationAndSolveAbsence:
    @patch("nexus.core.github.gh_installed", return_value=True)
    @patch("nexus.core.github.fetch_issue")
    def test_cli_investigate_does_not_modify_files(self, mock_fetch, mock_gh, tmp_path):
        mock_fetch.return_value = GitHubIssue(
            number=42,
            title="Slow query on user lookup",
            body="Database takes 5s",
        )
        files_before = set(tmp_path.rglob("*"))

        result = runner.invoke(app, ["investigate", "42", "-p", str(tmp_path)])
        assert result.exit_code == 0
        assert "Investigating Issue #42" in result.output
        assert "Root-Cause Hypothesis" in result.output

        # Verify no project source files were created or modified (ignoring .nexus audit logs)
        files_after = set(p for p in tmp_path.rglob("*") if ".nexus" not in p.parts)
        assert files_before == files_after

    def test_tc42a_nexus_solve_command_exists_in_phase6(self):
        """ADR-011 — 'nexus solve' is unlocked in Phase 6 now that Warden (Phase 5) is active."""
        result = runner.invoke(app, ["solve", "--help"])
        assert result.exit_code == 0
        assert "End-to-end issue resolution workflow" in result.output


# ===========================================================================
# TC-4.3: Docker Status
# ===========================================================================

class TestTC43DockerStatus:
    @patch("nexus.core.docker.subprocess.run")
    def test_list_containers_parsing(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=(
                '{"Names":"web_app","Image":"nginx:latest","Status":"Up 2 hours","State":"running","Ports":"80/tcp"}\n'
                '{"Names":"db","Image":"postgres:15","Status":"Exited (1) 10 mins ago","State":"exited","Ports":""}\n'
            ),
        )
        containers = list_containers(all_containers=True)
        assert len(containers) == 2
        assert containers[0].name == "web_app"
        assert containers[0].state == "running"
        assert containers[1].name == "db"
        assert containers[1].state == "exited"

    @patch("nexus.core.docker.docker_installed", return_value=True)
    @patch("nexus.core.docker.docker_available", return_value=True)
    @patch("nexus.core.docker.list_containers")
    def test_cli_docker_command(self, mock_list, mock_avail, mock_inst):
        from nexus.models.diagnosis import ContainerStatus
        mock_list.return_value = [
            ContainerStatus(name="web", image="nginx", status="Up 5m", state="running", ports="8080:80")
        ]
        result = runner.invoke(app, ["docker"])
        assert result.exit_code == 0
        assert "web" in result.output


# ===========================================================================
# TC-4.4 & TC-4.5: Diagnostics Engine & No Numeric Confidence Score
# ===========================================================================

class TestTC44And45Diagnostics:
    def test_analyze_evidence_dependency_healthcheck_issue(self):
        problem, cause, fix = _analyze_evidence(
            git_ev=["Git working tree is clean"],
            project_ev=[],
            docker_ev=["Docker: 1 running, 1 exited container(s)", "Service 'web' depends on 'db' which has no healthcheck"],
            env_ev=[],
        )
        assert "dependency" in problem.lower() or "dependency" in cause.lower()
        assert "healthcheck" in fix.lower() or "depends_on" in fix.lower()

    def test_tc45_no_numeric_confidence_score(self, tmp_path):
        """ADR-006 compliance check — diagnosis must NOT contain numeric confidence scores."""
        diag = diagnose(tmp_path)
        assert isinstance(diag, DiagnosisArtifact)
        assert hasattr(diag, "confidence_note")
        # Ensure no percentage or float score field exists
        diag_dict = diag.model_dump()
        assert "confidence" not in diag_dict
        assert "score" not in diag_dict
        assert "confidence_score" not in diag_dict
        assert "qualitative only" in diag.confidence_note.lower()

    def test_cli_diagnose_command_executes(self, tmp_path):
        result = runner.invoke(app, ["diagnose", "-p", str(tmp_path)])
        assert result.exit_code == 0
        assert "Problem Identified" in result.output
        assert "Likely Root Cause" in result.output
        assert "Suggested Fix" in result.output


# ===========================================================================
# TC-4.6: PR Confirmation Prompt
# ===========================================================================

class TestTC46PRConfirmation:
    @patch("nexus.core.github.gh_installed", return_value=True)
    def test_pr_aborts_when_user_declines_confirmation(self, mock_gh):
        # Provide 'n' to confirmation prompt
        result = runner.invoke(app, ["pr", "--title", "Feature X"], input="n\n")
        assert result.exit_code == 0
        assert "PR creation cancelled" in result.output

    @patch("nexus.core.github.gh_installed", return_value=True)
    @patch("nexus.cli.main.create_pr")
    def test_pr_proceeds_when_user_confirms(self, mock_create, mock_gh):
        mock_create.return_value = MagicMock(
            created=True,
            url="https://github.com/example/repo/pull/1",
        )
        # Provide 'y' to confirmation prompt
        result = runner.invoke(app, ["pr", "--title", "Feature X"], input="y\n")
        assert result.exit_code == 0
        assert "Pull Request Created!" in result.output

    def test_shell_dispatch_phase4_commands(self):
        """Verify interactive shell _dispatch_shell_line works cleanly for Phase 4 commands without OptionInfo errors."""
        from nexus.cli.main import _dispatch_shell_line
        with patch("nexus.core.github.gh_installed", return_value=True), \
             patch("nexus.core.github.fetch_issue") as mock_fetch, \
             patch("nexus.core.docker.docker_installed", return_value=True), \
             patch("nexus.core.docker.docker_available", return_value=True), \
             patch("nexus.core.docker.list_containers", return_value=[]):
            
            mock_fetch.return_value = GitHubIssue(
                number=1, title="Shell test issue", state="OPEN",
            )
            # Dispatch shell commands directly — should return True and not raise OptionInfo exceptions
            assert _dispatch_shell_line("issue 1") is True
            assert _dispatch_shell_line("investigate 1") is True
            assert _dispatch_shell_line("docker") is True
            assert _dispatch_shell_line("diagnose") is True
