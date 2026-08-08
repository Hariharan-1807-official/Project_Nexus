"""Phase 6 Planner, Swarm & Review Pydantic Models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field

from nexus.models.warden import ActionCategory


class StepStatus(str, Enum):
    pending     = "pending"
    in_progress = "in_progress"
    completed   = "completed"
    failed      = "failed"
    skipped     = "skipped"


class ReviewVerdict(str, Enum):
    approve         = "approve"
    request_changes = "request_changes"
    comment         = "comment"


class TaskStep(BaseModel):
    """Single step in a decomposed mission plan."""
    step_id:         str
    description:     str
    preferred_agent: str
    action_category: ActionCategory = ActionCategory.execute_commands
    status:          StepStatus = StepStatus.pending
    output_summary:  Optional[str] = None


class MissionPlan(BaseModel):
    """A decomposed multi-step plan for a high-level goal."""
    mission_id:  str
    goal:        str
    steps:       list[TaskStep]
    created_at:  datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    notes:       Optional[str] = None


class ReviewArtifact(BaseModel):
    """Result of cross-agent peer review."""
    review_id:      str
    task_id:        Optional[str] = None
    author_agent:   str
    reviewer_agent: str
    verdict:        ReviewVerdict
    feedback:       str
    reviewed_at:    datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SwarmResult(BaseModel):
    """Result of multi-agent swarm plan execution."""
    mission_id:          str
    status:              StepStatus
    steps_completed:     int
    total_steps:         int
    handoffs_logged:     int
    review_artifact:     Optional[ReviewArtifact] = None
    summary:             str
    completed_at:        datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
