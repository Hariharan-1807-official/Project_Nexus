"""
Mission Planner Engine — decomposes high-level goals into structured steps.

Uses router signal rules to assign the best agent to each step.
Follows ADR-006 (no numeric confidence scores).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from nexus.models.planner import MissionPlan, TaskStep, StepStatus
from nexus.models.warden import ActionCategory
from nexus.core.github import recommend_agent_for_issue
from nexus.models.diagnosis import GitHubIssue


def decompose_mission(goal: str, root: Optional[Path] = None) -> MissionPlan:
    """
    Decompose a high-level goal string into structured task steps.
    Assigns preferred agents based on keyword signal matching.
    """
    mission_id = f"mission-{uuid.uuid4().hex[:8]}"
    goal_lower = goal.lower()

    steps: list[TaskStep] = []

    # Step 1: Investigation & Context
    steps.append(
        TaskStep(
            step_id=f"{mission_id}-step-1",
            description=f"Inspect workspace and gather context for: {goal}",
            preferred_agent="antigravity",
            action_category=ActionCategory.read_source,
            status=StepStatus.pending,
        )
    )

    # Step 2: Implementation (Backend vs Frontend vs Generic)
    if any(w in goal_lower for w in ("frontend", "ui", "component", "css", "layout", "react")):
        impl_agent = "antigravity"
        action_cat = ActionCategory.write_source
    elif any(w in goal_lower for w in ("docker", "deploy", "ci", "compose", "container")):
        impl_agent = "codex"
        action_cat = ActionCategory.execute_commands
    elif any(w in goal_lower for w in ("api", "backend", "db", "database", "server", "python", "fix", "bug")):
        impl_agent = "codex"
        action_cat = ActionCategory.write_source
    else:
        impl_agent = "codex"
        action_cat = ActionCategory.write_source

    steps.append(
        TaskStep(
            step_id=f"{mission_id}-step-2",
            description=f"Implement changes for: {goal}",
            preferred_agent=impl_agent,
            action_category=action_cat,
            status=StepStatus.pending,
        )
    )

    # Step 3: Verification / Testing
    steps.append(
        TaskStep(
            step_id=f"{mission_id}-step-3",
            description=f"Run tests and verify functionality for: {goal}",
            preferred_agent="kiro" if impl_agent != "kiro" else "codex",
            action_category=ActionCategory.execute_commands,
            status=StepStatus.pending,
        )
    )

    return MissionPlan(
        mission_id=mission_id,
        goal=goal,
        steps=steps,
        notes="Qualitative mission decomposition (ADR-006 compliance).",
    )
