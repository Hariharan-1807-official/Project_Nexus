# Nexus — System Architecture

**Status:** Draft v1
**Depends on:** PRD (01-prd.md), ADRs (02-adr.md) — this document must not contradict either.

---

## 0. Technology Stack (ADR-010)

- **Language/runtime:** Python 3.11+
- **CLI framework:** Typer
- **Schema/validation:** Pydantic models for every `.nexus/` artifact (Task, AgentResult, ReviewArtifact, DiagnosisArtifact, PermissionProfile)
- **Testing:** pytest, one test module per component matching the Implementation Plan's phase test cases
- **Packaging:** pip-installable local package (`pip install -e .` during development); no PyPI publish planned for v1 (non-goal, see PRD §3)
- **Process management:** `subprocess` for all CLI-tool adapters (Codex CLI, Antigravity CLI, Kiro, Cursor); no shelling out via a shell string — always argument lists, to avoid injection risk given agents may generate command arguments. Note: Gemini CLI was retired June 18, 2026 and is not supported; its successor is Antigravity CLI (ADR-015).

## 1. High-Level Component Diagram

```
                         NEXUS CLI
                            │
              ┌─────────────┴─────────────┐
              │                           │
        Command Core                Project Intelligence
              │                           │
       ┌──────┼──────┐              ┌─────┼─────┐
       ▼      ▼      ▼              ▼     ▼     ▼
     Router  Planner  Swarm         Git   Files  Config
       │      │      │
       └──────┼──────┘
              │
        ┌─────┴─────────────────────────┐
        │                               │
   Agent Layer                    Shared Memory
        │                               │
 ┌──────┼────────────┐                  │
 ▼      ▼      ▼     ▼                  │
Codex  Agy   Kiro  Cursor               │
  (Antigravity CLI)                      │
        │                                │
        └──────────────┬─────────────────┘
                       │
             ┌─────────┴─────────┐
             ▼                   ▼
      Review Handoff       Diagnostics Engine
                                  │
                       ┌──────────┼──────────┐
                       ▼          ▼          ▼
                      Git       Docker      Project

        Warden (permission gate) wraps every write/execute/push/delete
        call from Agent Layer, Swarm, Review Handoff, and Daemon.
```

## 2. Component Responsibilities

| Component | Responsibility | Depends on |
|---|---|---|
| Command Core | CLI parsing, interactive shell, top-level command routing | — |
| Agent Layer | Uniform interface + adapters over each AI tool | — |
| AI Router | Task classification, agent recommendation | Agent Layer, Project Intelligence |
| Project Intelligence | Repo scanning, health checks, context maintenance | Git, filesystem |
| Shared Memory | `.nexus/` artifact store (tasks, decisions, handoffs, events) | Filesystem |
| Planner | Goal → task graph decomposition | Shared Memory, Router |
| Swarm Orchestrator | Multi-agent pipeline execution, role assignment | Agent Layer, Shared Memory, Warden |
| Review Handoff | Structured cross-agent review protocol | Agent Layer, Shared Memory |
| Diagnostics Engine | Cross-source evidence correlation + root-cause hypothesis | Git, Docker, Project Intelligence |
| GitHub Integration | Issue fetch, branch/PR pipeline | Agent Layer, Warden |
| Docker Integration | Container status, logs, compose inspection | — (feeds Diagnostics) |
| Warden | Capability profiles, approval prompts, audit log | — (wraps all other components) |
| Daemon | Background watchers, auto-diagnose, alerting | Diagnostics Engine, Agent Layer, Warden |
| IDE Control | Launch/status for IDEs | — |

## 3. Data Model — `.nexus/` Filesystem Schema

```
.nexus/
│
├── project/
│   ├── context.json          # stack, frameworks, structure (from `nexus scan`)
│   ├── architecture.md        # human-authored or agent-drafted architecture notes
│   └── conventions.md         # coding conventions the agents should follow
│
├── tasks/
│   └── task-<id>/
│       ├── task.json          # original request, classification, assigned agent
│       ├── plan.json           # task graph / subtasks (Planner output)
│       ├── implementation.json # what was changed, by which agent, diff summary
│       ├── review.json         # Review Handoff artifact (see §4)
│       └── resolution.json     # final outcome: approved / fixed / abandoned
│
├── memory/
│   ├── decisions.jsonl         # append-only log of accepted decisions
│   ├── agent-handoffs.jsonl    # append-only log of every inter-agent handoff
│   └── events.jsonl            # append-only log of all agent actions (audit trail)
│
└── config/
    ├── agents.json             # per-agent config: enabled, executable/API path, capability profile ref
    ├── router.json             # routing rules (task type → preferred agent list)
    └── permissions.json        # Warden capability profiles per agent/role
```

**Rule (from ADR-003):** Nothing in `tasks/` or `memory/` is ever mutated in place after being written by an agent action — corrections are appended as new entries referencing the original (e.g. `review.json` v2 references v1), preserving full history.

## 4. Agent Layer — Interface Contract

Every adapter implements:

```python
from enum import Enum
from pydantic import BaseModel

class InvocationMode(str, Enum):
    cli      = "cli"       # adapter shells out to a subprocess
    api      = "api"       # adapter calls an HTTP/SDK API
    ide_only = "ide_only"  # adapter can only launch the IDE interactively;
                           # run() queues the task but does not execute headlessly

class AgentCapabilities(BaseModel):
    repo_reasoning:    bool          # can reason over an existing multi-file codebase
    terminal_access:   bool          # can execute shell commands itself (not just propose)
    multi_file_edit:   bool          # can make coordinated changes across files in one pass
    max_context_tokens: int          # approximate context window ceiling (used for routing)
    supports_streaming: bool         # can surface incremental output (dashboard progress)
    invocation_mode:   InvocationMode

class Agent:
    def run(self, task: Task) -> AgentResult:
        """Execute a task. Must respect Warden capability checks before
        any write/execute/push/delete call.
        For ide_only agents, run() opens the IDE with the task queued —
        it does not block waiting for headless completion."""

    def status(self) -> AgentStatus:
        """Ready / Installed / Unreachable, plus version info if available."""

    def capabilities(self) -> AgentCapabilities:
        """Structured capability profile. Used by the Router for recommendation
        and by the Swarm/Daemon to exclude ide_only agents from automated pipelines."""
```

`Task`, `AgentResult`, and `AgentCapabilities` are shared, agent-agnostic types — no adapter-specific fields leak upward. This is the enforcement mechanism for ADR-005.

**`invocation_mode` routing rule:** Any agent with `invocation_mode = ide_only` is automatically excluded from Swarm and Daemon task routing. It remains reachable via `nexus open` and `nexus ask` (where the user can manually launch it), but the Router will never assign it as the target of an automated pipeline stage.

**Initial capability estimates (to be verified during Phase 2 — ADR-014):**

| Agent | `repo_reasoning` | `terminal_access` | `multi_file_edit` | `invocation_mode` | Notes |
|---|---|---|---|---|---|
| Codex CLI | ✓ | ✓ | ✓ | `cli` | Strong headless mode, subprocess-friendly |
| Antigravity CLI | ✓ | ✓ | likely ✓ | `cli` | Google's Gemini CLI successor (`agy` command); verify headless/pipe support |
| Kiro | ✓ | — | ✓ | likely `ide_only` | IDE-native; verify whether CLI mode supports non-interactive execution |
| Cursor | ✓ | — | ✓ | likely `ide_only` | IDE-native; verify headless mode availability |

All values in this table are best-guess pre-verification. TC-2.1 through TC-2.5 in the Implementation Plan will confirm or correct each field against real behavior before any adapter is considered complete.

## 5. Review Handoff — Protocol Detail

**Trigger:** `nexus review` (manual) or automatic step within a Swarm/mission pipeline.

**Flow:**

```
Agent A (implement) → Shared Memory (implementation.json)
                            │
                            ▼
Agent B (review, different agent) → Shared Memory (review.json)
                            │
                            ▼
                nexus fix review → Agent A (structured findings)
```

**`review.json` schema:**

```json
{
  "type": "review",
  "task_id": "task-042",
  "round": 1,
  "implementation_agent": "codex",
  "review_agent": "antigravity",
  "findings": [
    {
      "severity": "medium",
      "file": "backend/auth/token.ts",
      "issue": "Refresh token is not rotated",
      "recommendation": "Rotate token after successful refresh"
    }
  ],
  "tests": { "passed": 31, "failed": 0 },
  "decision": "changes_requested"
}
```

`decision` is one of: `approved`, `changes_requested`, `blocked` (blocked = review agent flags something Warden-relevant, e.g. a security issue requiring human sign-off regardless of severity field).

Subsequent rounds increment `round` and are stored as separate files (`review.json`, `review-2.json`, ...) — never overwritten, per ADR-003.

## 6. Diagnostics Engine — Evidence Model

**Trigger:** `nexus diagnose` (manual) or Daemon-triggered on watcher alert.

**Evidence sources pulled in one pass:**

```
Git        → status, diff, recent commits
Project    → package.json / requirements.txt / config files / source structure
Docker     → containers, logs, compose file, Dockerfile
Environment → relevant environment variables
```

**Output schema:**

```json
{
  "type": "diagnosis",
  "problem": "Backend cannot connect to PostgreSQL.",
  "evidence": [
    "PostgreSQL container starts successfully",
    "Backend starts before PostgreSQL is ready",
    "Recent compose changes modified startup order",
    "Backend logs show connection refusal"
  ],
  "likely_root_cause": "Database readiness race condition.",
  "suggested_fix": "Add PostgreSQL healthcheck and configure backend startup dependency.",
  "confidence_note": "qualitative only — see ADR-006, no numeric score in v1"
}
```

`[Ask agent to fix]` passes this object directly into the Agent Layer as structured input to `run(task)` — the agent does not have to re-derive the diagnosis from scratch.

## 6a. AI Router — Default `router.json` (resolves PRD OI-3)

Agent names used here match the v1 roster from ADR-015: `codex`, `antigravity`, `kiro`, `cursor`. `claude` and `gemini` are not valid values — see ADR-015 for exclusion rationale.

```json
{
  "rules": [
    {
      "task_type": "backend_coding",
      "signals": ["api", "backend", "database", "server", "endpoint"],
      "preferred_agents": ["codex", "antigravity"]
    },
    {
      "task_type": "frontend_ui",
      "signals": ["component", "ui", "layout", "styling", "frontend"],
      "preferred_agents": ["kiro", "cursor", "antigravity"]
    },
    {
      "task_type": "research",
      "signals": ["research", "compare", "investigate options", "what should we use"],
      "preferred_agents": ["antigravity"]
    },
    {
      "task_type": "github_issue",
      "signals": ["issue", "bug report", "github"],
      "preferred_agents": ["codex", "antigravity"]
    },
    {
      "task_type": "testing",
      "signals": ["test", "coverage", "unit test", "integration test"],
      "preferred_agents": ["codex"]
    },
    {
      "task_type": "documentation",
      "signals": ["docs", "readme", "documentation", "comment"],
      "preferred_agents": ["antigravity", "codex"]
    },
    {
      "task_type": "review",
      "signals": ["review", "audit", "check this"],
      "preferred_agents": ["antigravity", "codex"]
    },
    {
      "task_type": "devops",
      "signals": ["docker", "deploy", "ci", "pipeline", "compose"],
      "preferred_agents": ["codex", "antigravity"]
    }
  ],
  "default_agent": "codex",
  "fallback_on_unavailable": true
}
```

Matching is signal-based keyword scoring in v1 (no ML classifier) — first version deliberately simple, per PRD NFR-5 (config over code). `default_agent` is used when no rule scores above threshold. `fallback_on_unavailable: true` means if the top-preferred agent's `status()` is `Unreachable`, the Router falls to the next agent in `preferred_agents` rather than failing the task. Note that any agent with `invocation_mode: ide_only` (see §4) will be skipped automatically for Swarm/Daemon stages regardless of its position in a `preferred_agents` list.

## 7. Warden — Enforcement Model

**Capability profile shape (`config/permissions.json`):**

```json
{
  "codex": {
    "read_source": "allow",
    "write_source": "allow",
    "execute_commands": "approval",
    "git_push": "approval",
    "delete_files": "approval",
    "network": "deny"
  }
}
```

Values: `allow`, `deny`, `approval`.

**Enforcement point:** Every call in Agent Layer, Swarm, Review Handoff, GitHub Integration, and Daemon that performs a write/execute/push/delete/network action must pass through a single Warden check function before executing. This is a hard architectural requirement — there is no code path that bypasses Warden for these action types (see ADR-002, ADR-004).

**Approval prompt shape:**

```
╭──────────── PERMISSION REQUEST ─────────────╮
Agent: Codex
Action: git push (branch: feature/auth)
Reason: Complete authentication task-042
Risk: HIGH
[Allow once] [Allow for task] [Deny] [Show details]
╰───────────────────────────────────────────────╯
```

Every decision (and every attempted action, approved or not) is appended to `memory/events.jsonl`, including the `task_id` the approval was scoped to.

**Approval scope rules (ADR-012):**

- Scope is always bound to a `.nexus/tasks/<id>` record — never to a conversational session or CLI process lifetime.
- `Allow once` — this single action only.
- `Allow for task` — all further actions of the *same risk-eligible type* within this same `task_id`. A new `task_id`, even in the same mission or session, always re-prompts.
- `git_push` and `delete_files` are **not eligible** for `Allow for task` scoping under any circumstance — every single push or delete action gets its own `Allow once` prompt, even mid-task, even if the user just approved one two seconds earlier.

## 8. Swarm Orchestrator — Pipeline Shape

```
Planner → { Architect | Coder | Researcher (parallel where independent) } → Tester → Review Handoff → (fix loop if changes_requested)
```

Each stage reads its input strictly from `.nexus/tasks/<id>/` artifacts written by the previous stage — never from another agent's live session state.

## 9. Daemon — Watcher Model

Each watcher (Git, Tests, Dependencies, Security, GitHub, Docker) runs on its own interval/trigger, calls into the Diagnostics Engine on anomaly detection, and may invoke the Agent Layer to investigate/draft a fix — always gated by Warden for any write action, per ADR-002.

**Watcher config schema (`config/daemon.json`):**

```json
{
  "watchers": {
    "git": { "mode": "event", "trigger": "on_commit" },
    "tests": { "mode": "interval", "interval_seconds": 300 },
    "dependencies": { "mode": "interval", "interval_seconds": 86400 },
    "security": { "mode": "interval", "interval_seconds": 86400 },
    "github": { "mode": "interval", "interval_seconds": 120 },
    "docker": { "mode": "interval", "interval_seconds": 30 }
  },
  "global": {
    "enabled": false,
    "auto_fix_attempt": false
  }
}
```

**Defaults rationale:**

- `git` watcher is event-triggered (file-system hook on commit), not polled — cheapest and most immediate.
- `docker` polls fastest (30s) since container crashes need near-real-time detection.
- `github` polls every 2 minutes — issue/PR state doesn't need sub-minute freshness.
- `tests` polls every 5 minutes by default (running a full suite repeatedly is expensive; tighten per-project if the suite is fast).
- `dependencies` and `security` poll daily — these change slowly and scanning is comparatively expensive.
- `global.enabled` defaults to `false` — the daemon must be explicitly turned on per project, it never auto-starts.
- `global.auto_fix_attempt` defaults to `false` — out of the box the daemon only alerts and diagnoses; drafting a fix attempt is an explicit opt-in, separate from the always-required push/delete approval gate.

## 10. Cross-Cutting Concerns

- **Idempotency:** Any mission/swarm stage that fails mid-way must be resumable from its last successfully-written artifact, not from scratch.
- **Traceability:** Every entry in `memory/events.jsonl` includes `timestamp`, `agent`, `action`, `task_id` (if applicable), and `result`.
- **Config over code:** `router.json` and `permissions.json` are the only places task-routing and permission logic should ever need to change for typical adjustments.
- **Static Warden profiles:** `permissions.json` is manually configured and never auto-updated from audit-log behavior. Dynamic trust scoring is explicitly out of scope for v1 (ADR-013).
