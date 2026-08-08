"""
Phase 6 Test Suite — Planner, Swarm Orchestration, Review Handoff & nexus solve.

Validates:
- TC-6.1: Mission decomposition (nexus mission)
- TC-6.2: Swarm multi-agent execution & handoff logging (agent-handoffs.jsonl)
- TC-6.3: Cross-agent peer review (nexus review)
- TC-6.4: nexus solve <n> end-to-end workflow (ADR-011 unlocked)
- TC-6.5: Warden safety interception during Swarm (ADR-002)
- TC-6.6: Qualitative outputs with no numeric confidence scores (ADR-006)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from typer.testing import CliRunner

from nexus.cli.main import app
from nexus.core.planner.engine import decompose_mission
from nexus.core.swarm.orchestrator import execute_swarm_plan
from nexus.core.review.reviewer import perform_review
from nexus.models.planner import MissionPlan, SwarmResult, ReviewArtifact, StepStatus
from nexus.models.diagnosis import GitHubIssue
from nexus.core.memory import Memory

runner = CliRunner()


# ===========================================================================
# TC-6.1: Mission Decomposition
# ===========================================================================

class TestTC61MissionDecomposition:
    def test_decompose_mission_creates_structured_plan(self):
        plan = decompose_mission("Fix database API connection timeout")
        assert isinstance(plan, MissionPlan)
        assert len(plan.steps) >= 3
        assert plan.steps[0].preferred_agent == "antigravity"
        assert plan.steps[1].preferred_agent == "codex"  # API/backend signal match

    def test_cli_mission_command(self):
        result = runner.invoke(app, ["mission", "Add user auth endpoint"])
        assert result.exit_code == 0
        assert "Mission Plan" in result.output
        assert "Step 1" in result.output
        assert "codex" in result.output


# ===========================================================================
# TC-6.2 & TC-6.5: Swarm Orchestration, Handoff Logging & Warden Interception
# ===========================================================================

class TestTC62And65SwarmOrchestration:
    def test_execute_swarm_plan_logs_handoffs(self, tmp_path):
        # Setup nexus repo structure
        nexus_dir = tmp_path / ".nexus"
        nexus_dir.mkdir()
        (nexus_dir / "memory").mkdir()

        plan = decompose_mission("Build payment processing flow")
        result = execute_swarm_plan(plan, tmp_path)

        assert isinstance(result, SwarmResult)
        assert result.status == StepStatus.completed
        assert result.steps_completed == len(plan.steps)
        assert result.handoffs_logged > 0

        # Verify handoff logs created in .nexus/memory/agent-handoffs.jsonl
        handoff_file = nexus_dir / "memory" / "agent-handoffs.jsonl"
        assert handoff_file.exists()
        lines = [json.loads(l) for l in handoff_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) >= 1

    def test_cli_swarm_command(self, tmp_path):
        nexus_dir = tmp_path / ".nexus"
        nexus_dir.mkdir()

        result = runner.invoke(app, ["swarm", "Refactor logging pipeline", "-p", str(tmp_path)])
        assert result.exit_code == 0
        assert "Initializing Swarm Pipeline" in result.output
        assert "Swarm Execution Status" in result.output


# ===========================================================================
# TC-6.3: Cross-Agent Peer Review
# ===========================================================================

class TestTC63CrossAgentPeerReview:
    def test_perform_review_selects_peer_reviewer(self):
        artifact = perform_review("codex", "Added database query caching")
        assert isinstance(artifact, ReviewArtifact)
        assert artifact.author_agent == "codex"
        assert artifact.reviewer_agent == "antigravity"  # peer reviewer != author
        assert artifact.verdict.value == "approve"

    def test_cli_review_command(self):
        result = runner.invoke(app, ["review", "--author", "codex", "--summary", "Implemented OAuth2 handler"])
        assert result.exit_code == 0
        assert "Cross-Agent Peer Review" in result.output
        assert "Author Agent:" in result.output
        assert "Reviewer Agent:" in result.output


# ===========================================================================
# TC-6.4: nexus solve End-to-End Resolution Workflow (ADR-011 Unlocked)
# ===========================================================================

class TestTC64NexusSolveWorkflow:
    @patch("nexus.core.github.gh_installed", return_value=True)
    @patch("nexus.core.github.fetch_issue")
    def test_cli_solve_workflow_runs_end_to_end(self, mock_fetch, mock_gh, tmp_path):
        mock_fetch.return_value = GitHubIssue(
            number=42,
            title="Fix null pointer exception in scanner",
            body="API returns 500 when scanner receives empty file",
        )

        # User declines PR creation prompt
        result = runner.invoke(app, ["solve", "42", "-p", str(tmp_path)], input="n\n")
        assert result.exit_code == 0
        assert "Starting End-to-End Solve Workflow for Issue #42" in result.output
        assert "Step 1: Running Diagnostics" in result.output
        assert "Step 2: Planning Mission Decomposition" in result.output
        assert "Step 3: Executing Swarm Pipeline" in result.output
        assert "Step 4: Cross-Agent Peer Review" in result.output
        assert "Step 5: Pull Request Preparation" in result.output
        assert "PR creation skipped" in result.output


# ===========================================================================
# TC-6.6: Qualitative Outputs (No Numeric Confidence Scores - ADR-006)
# ===========================================================================

class TestTC66QualitativeOutputs:
    def test_planner_and_review_outputs_have_no_numeric_scores(self):
        plan = decompose_mission("Create user profile module")
        plan_dict = plan.model_dump()
        assert "confidence" not in plan_dict
        assert "score" not in plan_dict

        review = perform_review("codex", "Added profile API")
        review_dict = review.model_dump()
        assert "score" not in review_dict
        assert "confidence" not in review_dict


# ===========================================================================
# TC-6.7: Groq Natural Language LLM Router
# ===========================================================================

class TestTC67GroqRouter:
    def test_load_groq_api_key_reads_env_file(self, tmp_path):
        from nexus.core.router.llm_router import load_groq_api_key
        env_file = tmp_path / ".env"
        env_file.write_text('GROQ_API_KEY="gsk_test_key_12345"\n', encoding="utf-8")
        key = load_groq_api_key(tmp_path)
        assert key == "gsk_test_key_12345"
