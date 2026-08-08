"""Phase 5 Warden Pydantic Models — Action Categories, Permission States, Requests & Results."""

from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class ActionCategory(str, Enum):
    read_source      = "read_source"
    write_source     = "write_source"
    execute_commands = "execute_commands"
    git_push         = "git_push"
    delete_files     = "delete_files"
    network          = "network"


class PermissionState(str, Enum):
    allow    = "allow"
    deny     = "deny"
    approval = "approval"


class PermissionRequest(BaseModel):
    """A request to perform an action evaluated by Warden."""
    agent:           str
    action_category: ActionCategory
    description:     str
    task_id:         Optional[str] = None
    target_path:     Optional[str] = None


class PermissionResult(BaseModel):
    """The result of Warden's permission evaluation."""
    allowed:         bool
    state:           PermissionState
    reason:          str
    prompt_user:     bool = False
    task_id:         Optional[str] = None
