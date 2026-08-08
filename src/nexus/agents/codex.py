"""
Codex CLI adapter.

Headless execution:  codex exec "<prompt>"
Status detection:    codex --version
Invocation mode:     cli
Verified:            codex-cli 0.147.0  (npm global install)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from nexus.agents.base import Agent
from nexus.models.agent import AgentCapabilities, AgentResult, AgentStatus, InvocationMode
from nexus.models.task import Task

# Known install locations for Codex CLI (npm global)
_CODEX_HINTS = [
    r"C:\Users\Hariharan N\AppData\Roaming\npm\codex.cmd",
    r"C:\Users\Hariharan N\AppData\Roaming\npm\codex.ps1",
]


class CodexAgent(Agent):
    NAME        = "codex"
    LABEL       = "Codex CLI"
    _EXECUTABLE = "codex"
    _HINTS      = _CODEX_HINTS

    # ------------------------------------------------------------------
    # status()
    # ------------------------------------------------------------------

    def status(self) -> AgentStatus:
        exe = self._exe()
        if exe is None:
            return AgentStatus.unreachable

        rc, stdout, stderr = self._run_subprocess(["--version"], timeout=15)
        if rc == 0 or "codex" in (stdout + stderr).lower():
            return AgentStatus.ready
        return AgentStatus.installed   # found but didn't respond as expected

    def version(self) -> Optional[str]:
        """Return version string e.g. 'codex-cli 0.147.0', or None."""
        rc, stdout, stderr = self._run_subprocess(["--version"], timeout=15)
        text = (stdout + stderr).strip()
        if text:
            return text.splitlines()[0]
        return None

    # ------------------------------------------------------------------
    # capabilities()   — verified against codex-cli 0.147.0
    # ------------------------------------------------------------------

    def capabilities(self) -> AgentCapabilities:
        return AgentCapabilities(
            repo_reasoning     = True,   # strong multi-file codebase reasoning
            terminal_access    = True,   # executes shell commands natively
            multi_file_edit    = True,   # coordinated multi-file edits in one pass
            max_context_tokens = 200_000,
            supports_streaming = False,  # exec mode returns complete output only
            invocation_mode    = InvocationMode.cli,
        )

    # ------------------------------------------------------------------
    # run()
    # ------------------------------------------------------------------

    def run(self, task: Task, cwd: Optional[Path] = None) -> AgentResult:
        """
        Execute a task non-interactively using `codex exec "<prompt>"`.
        The `exec` subcommand (alias: e) runs Codex without opening the TUI.
        """
        # Phase 5 Warden check goes here — stub until Warden is built
        exe = self._exe()
        if exe is None:
            return AgentResult(
                task_id = task.task_id,
                agent   = self.NAME,
                success = False,
                error   = "Codex CLI not found. Install with: npm install -g @openai/codex",
            )

        rc, stdout, stderr = self._run_subprocess(
            ["exec", task.description],
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
