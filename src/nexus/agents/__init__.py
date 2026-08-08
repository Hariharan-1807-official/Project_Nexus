"""Agent adapters — one file per tool, all implementing the Agent base class."""

from nexus.agents.base import Agent
from nexus.agents.codex import CodexAgent
from nexus.agents.antigravity import AntigravityAgent
from nexus.agents.kiro import KiroAgent
from nexus.agents.cursor import CursorAgent

# Registry: name → class.  Adding a new agent = add one entry here + one file.
REGISTRY: dict[str, type[Agent]] = {
    "codex":       CodexAgent,
    "antigravity": AntigravityAgent,
    "kiro":        KiroAgent,
    "cursor":      CursorAgent,
}

__all__ = ["Agent", "CodexAgent", "AntigravityAgent", "KiroAgent", "CursorAgent", "REGISTRY"]
