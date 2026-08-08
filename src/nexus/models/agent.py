"""Agent-related models — AgentCapabilities, AgentStatus, AgentResult."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel


class InvocationMode(str, Enum):
    cli      = "cli"       # adapter shells out to a subprocess
    api      = "api"       # adapter calls an HTTP/SDK API
    ide_only = "ide_only"  # adapter launches IDE interactively; no headless execution


class AgentCapabilities(BaseModel):
    repo_reasoning:     bool           # reason over existing multi-file codebase
    terminal_access:    bool           # execute shell commands itself
    multi_file_edit:    bool           # coordinated changes across files in one pass
    max_context_tokens: int            # approximate context window ceiling
    supports_streaming: bool           # can surface incremental output
    invocation_mode:    InvocationMode


class AgentStatus(str, Enum):
    ready        = "ready"
    installed    = "installed"   # present but not yet verified ready
    unreachable  = "unreachable" # not installed or auth failing


class AgentResult(BaseModel):
    task_id:      str
    agent:        str
    success:      bool
    output:       Optional[str]   = None
    error:        Optional[str]   = None
    artifacts:    dict[str, Any]  = {}
