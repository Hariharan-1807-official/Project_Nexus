"""
Antigravity CLI adapter.

Headless execution:  agy --print "<prompt>"
Status detection:    agy --version
Invocation mode:     cli
Verified:            agy 1.1.11  (installed to %LOCALAPPDATA%\agy\bin\agy.exe)

Note: agy.exe is in the user-level PATH but not the conda process PATH.
      resolve_executable() handles this via the registry PATH fallback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from nexus.agents.base import Agent
from nexus.models.agent import AgentCapabilities, AgentResult, AgentStatus, InvocationMode
from nexus.models.task import Task

# Known install location — the installer puts agy.exe here on Windows
_AGY_HINTS = [
    r"C:\Users\Hariharan N\AppData\Local\agy\bin\agy.exe",
]


class AntigravityAgent(Agent):
    NAME        = "antigravity"
    LABEL       = "Antigravity CLI"
    _EXECUTABLE = "agy"
    _HINTS      = _AGY_HINTS

    # ------------------------------------------------------------------
    # status()
    # ------------------------------------------------------------------

    def status(self) -> AgentStatus:
        exe = self._exe()
        if exe is None:
            return AgentStatus.unreachable

        rc, stdout, stderr = self._run_subprocess(["--version"], timeout=15)
        combined = (stdout + stderr).lower()
        if rc == 0 or "agy" in combined or any(c.isdigit() for c in combined):
            return AgentStatus.ready
        return AgentStatus.installed

    def version(self) -> Optional[str]:
        rc, stdout, stderr = self._run_subprocess(["--version"], timeout=15)
        text = (stdout + stderr).strip()
        return text.splitlines()[0] if text else None

    # ------------------------------------------------------------------
    # capabilities()   — verified against agy 1.1.11
    # ------------------------------------------------------------------

    def capabilities(self) -> AgentCapabilities:
        return AgentCapabilities(
            repo_reasoning     = True,   # Gemini 2.5 Pro, 1M token context
            terminal_access    = True,   # agy can execute shell commands via tool calls
            multi_file_edit    = True,   # multi-file edits confirmed in --print mode
            max_context_tokens = 1_000_000,
            supports_streaming = False,  # --print returns full output; stream-json exists
                                         # but not used in v1 for simplicity
            invocation_mode    = InvocationMode.cli,
        )

    # ------------------------------------------------------------------
    # run()
    # ------------------------------------------------------------------

    def run(self, task: Task, cwd: Optional[Path] = None) -> AgentResult:
        """
        Execute a task non-interactively using `agy --print "<prompt>"`.
        """
        exe = self._exe()
        if exe is None:
            return AgentResult(
                task_id = task.task_id,
                agent   = self.NAME,
                success = False,
                error   = (
                    "Antigravity CLI (agy) not found. "
                    "Install with: irm https://antigravity.google/cli/install.ps1 | iex"
                ),
            )

        rc, stdout, stderr = self._run_subprocess(
            ["--print", task.description],
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
