"""
Kiro adapter.

Headless execution:  kiro chat "<prompt>" --mode agent
Status detection:    kiro --version
Invocation mode:     cli  (kiro chat accepts prompt as positional arg — no TUI needed)
Verified:            Kiro 1.0.212  (installed to %LOCALAPPDATA%/Programs/Kiro/bin/kiro.cmd)

Note: kiro.cmd is on both process PATH and user PATH — no special resolution needed,
      but hints are provided for robustness.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from nexus.agents.base import Agent
from nexus.models.agent import AgentCapabilities, AgentResult, AgentStatus, InvocationMode
from nexus.models.task import Task

_KIRO_HINTS = [
    r"C:\Users\Hariharan N\AppData\Local\Programs\Kiro\bin\kiro.cmd",
]


class KiroAgent(Agent):
    NAME        = "kiro"
    LABEL       = "Kiro"
    _EXECUTABLE = "kiro"
    _HINTS      = _KIRO_HINTS

    # ------------------------------------------------------------------
    # status()
    # ------------------------------------------------------------------

    def status(self) -> AgentStatus:
        exe = self._exe()
        if exe is None:
            return AgentStatus.unreachable

        # kiro --version writes to stderr, exits 0
        rc, stdout, stderr = self._run_subprocess(["--version"], timeout=15)
        combined = (stdout + stderr).lower()
        if "kiro" in combined or any(c.isdigit() for c in combined):
            return AgentStatus.ready
        # kiro is found but version check inconclusive — still report ready
        # (the exe resolved, which is the meaningful check)
        if exe:
            return AgentStatus.ready
        return AgentStatus.installed

    def version(self) -> Optional[str]:
        rc, stdout, stderr = self._run_subprocess(["--version"], timeout=15)
        text = (stdout + stderr).strip()
        return text.splitlines()[0] if text else None

    # ------------------------------------------------------------------
    # capabilities()   — verified against Kiro 1.0.212
    # ------------------------------------------------------------------

    def capabilities(self) -> AgentCapabilities:
        return AgentCapabilities(
            repo_reasoning     = True,   # Kiro spec-driven dev with full repo context
            terminal_access    = False,  # Kiro does not execute shell commands itself
            multi_file_edit    = True,   # coordinated multi-file edits via agent mode
            max_context_tokens = 128_000,
            supports_streaming = False,  # chat mode returns complete output
            invocation_mode    = InvocationMode.cli,
        )

    # ------------------------------------------------------------------
    # run()
    # ------------------------------------------------------------------

    def run(self, task: Task, cwd: Optional[Path] = None) -> AgentResult:
        """
        Execute a task using `kiro chat "<prompt>" --mode agent`.
        Kiro processes the prompt in agent mode and returns when done.
        """
        exe = self._exe()
        if exe is None:
            return AgentResult(
                task_id = task.task_id,
                agent   = self.NAME,
                success = False,
                error   = "Kiro not found. Download from https://kiro.dev",
            )

        rc, stdout, stderr = self._run_subprocess(
            ["chat", task.description, "--mode", "agent"],
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
