"""Task artifact model — written to .nexus/tasks/<id>/task.json."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class TaskStatus(str, Enum):
    pending    = "pending"
    in_progress = "in_progress"
    completed  = "completed"
    failed     = "failed"
    abandoned  = "abandoned"


class Task(BaseModel):
    task_id:        str          = Field(default_factory=lambda: f"task-{uuid.uuid4().hex[:8]}")
    description:    str
    domain:         Optional[str] = None   # classification from Router
    complexity:     Optional[str] = None   # low / medium / high
    assigned_agent: Optional[str] = None
    status:         TaskStatus   = TaskStatus.pending
    created_at:     datetime     = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at:     datetime     = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"ser_json_timedelta": "iso8601"}
