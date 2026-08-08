"""
Agent base class — the one contract everything above the Agent Layer depends on (ADR-005).

Every adapter must implement:
    run(task)       → AgentResult
    status()        → AgentStatus
    capabilities()  → AgentCapabilities

No component above this layer may contain tool-specific logic.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from nexus.models.warden import ActionCategory, PermissionResult, PermissionRequest

from nexus.models.agent import AgentCapabilities, AgentResult, AgentStatus
from nexus.models.task import Task


# ---------------------------------------------------------------------------
# PATH resolution helper
# The Anaconda conda environment overrides PATH and hides tools installed
# under the user account (agy, cursor, etc.).  We resolve using both the
# process PATH and the persistent user-level PATH from the registry.
# ---------------------------------------------------------------------------

def _user_path_dirs() -> list[str]:
    """Return directories from the Windows user-level PATH (registry), deduplicated."""
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Environment",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "PATH")
            return [d for d in value.split(";") if d.strip()]
    except Exception:
        return []


def resolve_executable(name: str, hints: Optional[list[str]] = None) -> Optional[str]:
    """
    Find the full path of an executable, checking:
      1. hints list (explicit full paths / directories to try first)
      2. current process PATH (shutil.which)
      3. Windows user-level PATH from registry (conda overrides process PATH)

    Returns the resolved path string, or None if not found.
    Never raises.
    """
    # 1. Explicit hints (full paths or directories)
    for hint in (hints or []):
        p = Path(hint)
        if p.is_file():
            return str(p)
        # hint is a directory — try appending the name with common extensions
        for ext in ("", ".exe", ".cmd", ".ps1"):
            candidate = p / (name + ext)
            if candidate.is_file():
                return str(candidate)

    # 2. Process PATH
    found = shutil.which(name)
    if found:
        return found

    # 3. User-level PATH (catches conda environment shadowing)
    for directory in _user_path_dirs():
        for ext in ("", ".exe", ".cmd", ".ps1"):
            candidate = Path(directory) / (name + ext)
            try:
                if candidate.is_file():
                    return str(candidate)
            except OSError:
                continue

    return None


# ---------------------------------------------------------------------------
# Agent base class
# ---------------------------------------------------------------------------

class Agent(ABC):
    """
    Abstract base for all agent adapters.

    Subclasses must set:
        NAME        — short identifier used in config/routing (e.g. "codex")
        LABEL       — human-readable name (e.g. "Codex CLI")
        _EXECUTABLE — primary command name for resolve_executable()
        _HINTS      — optional list of known full paths to try first
    """

    NAME:        str = ""
    LABEL:       str = ""
    _EXECUTABLE: str = ""
    _HINTS:      list[str] = []

    def __init__(self) -> None:
        self._resolved_path: Optional[str] = None  # cached after first resolution

    # ------------------------------------------------------------------
    # Executable resolution (shared by all adapters)
    # ------------------------------------------------------------------

    def _exe(self) -> Optional[str]:
        """Return the resolved executable path, caching the result."""
        if self._resolved_path is None:
            self._resolved_path = resolve_executable(self._EXECUTABLE, self._HINTS)
        return self._resolved_path

    def _run_subprocess(
        self,
        args: list[str],
        cwd: Optional[Path] = None,
        timeout: int = 120,
        input_text: Optional[str] = None,
    ) -> tuple[int, str, str]:
        """
        Run a subprocess with the given args list.
        Returns (returncode, stdout, stderr).
        Always uses argument list — never a shell string (ADR-010 injection rule).
        """
        exe = self._exe()
        if exe is None:
            return -1, "", f"{self._EXECUTABLE!r} not found on PATH"

        cmd = [exe] + args
        try:
            result = subprocess.run(
                cmd,
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                text=True,
                timeout=timeout,
                input=input_text,
                env={**os.environ, "PATH": self._extended_path()},
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -2, "", f"Timeout after {timeout}s"
        except FileNotFoundError:
            return -1, "", f"Executable not found: {exe}"
        except Exception as exc:
            return -1, "", str(exc)

    def _extended_path(self) -> str:
        """
        Return a PATH string that merges the current process PATH with the
        user-level PATH entries, so subprocesses can find all user-installed tools.
        """
        current = os.environ.get("PATH", "")
        user_dirs = _user_path_dirs()
        extra = ";".join(d for d in user_dirs if d not in current)
        return f"{current};{extra}" if extra else current

    # ------------------------------------------------------------------
    # Abstract interface (ADR-005)
    # ------------------------------------------------------------------

    @abstractmethod
    def run(self, task: Task) -> AgentResult:
        """
        Execute a task non-interactively.
        Must check Warden before any write/execute/push/delete (enforced in Phase 5).
        """
        ...

    @abstractmethod
    def status(self) -> AgentStatus:
        """Return Ready / Installed / Unreachable with version info where available."""
        ...

    @abstractmethod
    def capabilities(self) -> AgentCapabilities:
        """Return the verified capability profile for this agent."""
        ...

    def check_warden_permission(
        self,
        action_category: ActionCategory,
        description: str,
        task_id: Optional[str] = None,
        cwd: Optional[Path] = None,
    ) -> PermissionResult:
        """
        Check Warden security policy for an action before execution (ADR-002, ADR-012).
        Logs evaluation to memory audit trail.
        """
        from nexus.core.warden.engine import WardenEngine
        from nexus.core.warden.audit import log_warden_evaluation
        from nexus.models.warden import PermissionRequest
        from nexus.core.memory import Memory

        root = cwd or Path(".")
        engine = WardenEngine(root)
        request = PermissionRequest(
            agent=self.NAME,
            action_category=action_category,
            description=description,
            task_id=task_id,
        )
        result = engine.evaluate(request)

        # Log audit trail if .nexus directory exists
        try:
            mem = Memory(root)
            log_warden_evaluation(mem, request, result)
        except Exception:
            pass

        return result

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.NAME!r}>"
