"""
Cursor adapter.

Headless execution:  cursor agent "<prompt>"
Status detection:    cursor --version
Invocation mode:     cli  (cursor agent subcommand runs non-interactively)
Verified:            Cursor 3.15.6  (installed to %LOCALAPPDATA%/Programs/cursor)

Note: cursor.cmd is in user-level PATH but not conda process PATH.
      resolve_executable() handles this via the registry PATH fallback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from nexus.agents.base import Agent
from nexus.models.agent import AgentCapabilities, AgentResult, AgentStatus, InvocationMode
from nexus.models.task import Task

_CURSOR_HINTS = [
    r"C:\Users\Hariharan N\AppData\Local\Programs\cursor\resources\app\bin\cursor.cmd",
]


class CursorAgent(Agent):
    NAME        = "cursor"
    LABEL       = "Cursor"
    _EXECUTABLE = "cursor"
    _HINTS      = _CURSOR_HINTS

    # ------------------------------------------------------------------
    # status()
    # ------------------------------------------------------------------

    def status(self) -> AgentStatus:
        exe = self._exe()
        if exe is None:
            return AgentStatus.unreachable

        rc, stdout, stderr = self._run_subprocess(["--version"], timeout=15)
        combined = (stdout + stderr).lower()
        if "cursor" in combined or any(c.isdigit() for c in combined):
            return AgentStatus.ready
        if exe:
            return AgentStatus.ready
        return AgentStatus.installed

    def version(self) -> Optional[str]:
        rc, stdout, stderr = self._run_subprocess(["--version"], timeout=15)
        text = (stdout + stderr).strip()
        return text.splitlines()[0] if text else None

    # ------------------------------------------------------------------
    # capabilities()   — verified against Cursor 3.15.6
    # ------------------------------------------------------------------

    def capabilities(self) -> AgentCapabilities:
        return AgentCapabilities(
            repo_reasoning     = True,   # full codebase context via agent mode
            terminal_access    = False,  # Cursor does not execute shell commands itself
            multi_file_edit    = True,   # multi-file edits in one agent pass
            max_context_tokens = 200_000,
            supports_streaming = False,  # agent subcommand returns complete output
            invocation_mode    = InvocationMode.cli,
        )

    # ------------------------------------------------------------------
    # run()
    # ------------------------------------------------------------------

    def run(self, task: Task, cwd: Optional[Path] = None) -> AgentResult:
        """
        Execute a task using `cursor agent "<prompt>"`.
        """
        exe = self._exe()
        if exe is None:
            return AgentResult(
                task_id = task.task_id,
                agent   = self.NAME,
                success = False,
                error   = "Cursor not found. Download from https://cursor.com",
            )

        rc, stdout, stderr = self._run_subprocess(
            ["agent", task.description],
            cwd     = cwd,
            timeout = 300,
        )

        success = rc == 0
        return AgentResult(
            task_id  = task.task_id,
            agent    = self.NAME,
            success  = success,
            output   = stdout.strip() or None,
            error    = stderr.strip() if not success else None,
            artifacts= {},
        )
