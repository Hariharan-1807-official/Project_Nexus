"""Config models — agents.json and global nexus config."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class AgentConfig(BaseModel):
    name:             str
    enabled:          bool = True
    executable:       Optional[str] = None   # path or command name; None = auto-detect
    capability_note:  Optional[str] = None   # free-text note for Phase 2 verification


class NexusConfig(BaseModel):
    """Global Nexus configuration (outside any project folder)."""
    agents: list[AgentConfig] = []
