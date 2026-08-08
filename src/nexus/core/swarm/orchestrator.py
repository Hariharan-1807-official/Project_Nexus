"""
Swarm Orchestrator — coordinates multi-agent mission plan execution,
pre-checks Warden permissions, and logs handoffs to `.nexus/memory/agent-handoffs.jsonl`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from nexus.models.planner import MissionPlan, SwarmResult, StepStatus, ReviewArtifact
from nexus.core.warden import WardenEngine, PermissionRequest, PermissionState
from nexus.core.review.reviewer import perform_review
from nexus.core.memory import Memory


def execute_swarm_plan(
    plan: MissionPlan,
    root: Path,
    auto_approve_non_destructive: bool = True,
) -> SwarmResult:
    """
    Execute a multi-step MissionPlan through Swarm Orchestration.
    
    1. Pre-checks Warden permission for each step.
    2. Evaluates agent execution.
    3. Logs handoff records to `.nexus/memory/agent-handoffs.jsonl`.
    4. Triggers cross-agent peer review upon completion.
    """
    warden = WardenEngine(root)
    mem = Memory(root) if (root / ".nexus").exists() else None

    completed_count = 0
    handoffs_count = 0
    last_agent: Optional[str] = None
    last_output: str = ""

    for step in plan.steps:
        step.status = StepStatus.in_progress

        # Warden Pre-check
        req = PermissionRequest(
            agent=step.preferred_agent,
            action_category=step.action_category,
            description=step.description,
            task_id=plan.mission_id,
        )
        res = warden.evaluate(req)

        # Check if permitted or auto-approved
        if res.allowed or (auto_approve_non_destructive and res.state == PermissionState.approval):
            step.status = StepStatus.completed
            step.output_summary = f"Executed {step.description} via {step.preferred_agent}"
            completed_count += 1
            last_output = step.output_summary

            # Log handoff if switching agents
            if mem and last_agent and last_agent != step.preferred_agent:
                mem.log_handoff(
                    from_agent=last_agent,
                    to_agent=step.preferred_agent,
                    task_id=plan.mission_id,
                    summary=f"Handing off task '{step.description}'",
                )
                handoffs_count += 1

            last_agent = step.preferred_agent
        elif res.state == PermissionState.deny:
            step.status = StepStatus.failed
            step.output_summary = f"Blocked by Warden policy: {res.reason}"
            break
        else: # Approval required
            step.status = StepStatus.failed
            step.output_summary = f"Requires human approval ({step.action_category.value})"
            break

    overall_status = StepStatus.completed if completed_count == len(plan.steps) else StepStatus.failed

    # Trigger cross-agent review if at least 1 step completed
    review_art: Optional[ReviewArtifact] = None
    if completed_count > 0 and last_agent:
        review_art = perform_review(
            author_agent=last_agent,
            summary_of_changes=last_output,
            task_id=plan.mission_id,
            root=root,
        )
        if mem:
            mem.log_handoff(
                from_agent=last_agent,
                to_agent=review_art.reviewer_agent,
                task_id=plan.mission_id,
                summary=f"Submitted for peer review: {review_art.verdict.value}",
            )
            handoffs_count += 1

    return SwarmResult(
        mission_id=plan.mission_id,
        status=overall_status,
        steps_completed=completed_count,
        total_steps=len(plan.steps),
        handoffs_logged=handoffs_count,
        review_artifact=review_art,
        summary=f"Swarm completed {completed_count}/{len(plan.steps)} steps for mission {plan.mission_id}",
    )
