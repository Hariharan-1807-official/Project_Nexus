"""Phase 4 models — Diagnosis, GitHub Issue, Investigation, Docker containers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


class DiagnosisArtifact(BaseModel):
    """Output of `nexus diagnose` — structured root-cause hypothesis."""
    type:             str        = "diagnosis"
    problem:          str
    evidence:         list[str]
    likely_root_cause: str
    suggested_fix:    str
    confidence_note:  str        = "qualitative only — see ADR-006, no numeric score in v1"
    sources_checked:  list[str]  = []       # e.g. ["git", "docker", "project"]
    diagnosed_at:     datetime   = Field(default_factory=lambda: datetime.now(timezone.utc))


class GitHubIssue(BaseModel):
    """Structured representation of a GitHub issue fetched via `gh`."""
    number:                int
    title:                 str
    body:                  Optional[str]  = None
    labels:                list[str]      = []
    state:                 str            = "open"
    assignees:             list[str]      = []
    url:                   Optional[str]  = None
    recommended_agent:     Optional[str]  = None
    recommendation_reason: Optional[str]  = None


class InvestigationResult(BaseModel):
    """Output of `nexus investigate` — read-only analysis, no code changes."""
    issue_number:     int
    hypothesis:       str
    affected_files:   list[str]       = []
    proposed_approach: str
    investigated_by:  Optional[str]   = None   # agent name
    investigated_at:  datetime        = Field(default_factory=lambda: datetime.now(timezone.utc))


class ContainerStatus(BaseModel):
    """One Docker container's current state."""
    name:     str
    image:    str
    status:   str             # running / exited / paused / created / dead
    state:    Optional[str]   = None
    ports:    str             = ""
    created:  Optional[str]   = None


class PRResult(BaseModel):
    """Result of `nexus pr` — pull request creation."""
    url:      Optional[str]   = None
    number:   Optional[int]   = None
    title:    str
    branch:   str
    base:     str
    created:  bool            = False
    error:    Optional[str]   = None
