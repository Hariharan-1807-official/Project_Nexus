# Nexus — Product Requirements Document (PRD)

**Status:** Draft v1
**Owner:** [User]
**Type:** Personal-use product, single developer, not for public distribution (v1)

---

## 1. Summary

Nexus is a unified CLI that acts as a control plane over AI coding agents (Codex CLI, Antigravity CLI, Kiro, Cursor) and supporting developer tools (GitHub, Docker). It routes tasks to the right agent, coordinates multi-agent workflows, maintains shared project context, and enforces a permission layer over any action an agent takes.

**Agent roster constraint (ADR-015):** v1 includes only agents with a verified free access tier. Claude Code (no free tier, $20/month minimum) and Gemini CLI (retired June 18, 2026 — succeeded by Antigravity CLI) are excluded. The supported roster is: Codex CLI, Antigravity CLI, Kiro, Cursor.

## 2. Goals

| Goal | Description |
|---|---|
| G1 | Eliminate manual tool-switching between AI coding agents and dev tools |
| G2 | Give every agent the same project context automatically |
| G3 | Make agent output cross-checkable (one agent reviews another's work) |
| G4 | Turn GitHub issues into investigated, tested, PR-ready fixes with minimal manual steps |
| G5 | Provide fast, evidence-based diagnosis when a project breaks (Git/Docker/config/env correlated) |
| G6 | Keep every destructive or externally-visible action gated behind explicit approval |
| G7 | Keep the system agent-agnostic — swapping or adding an agent should never require rearchitecting |

## 3. Non-Goals (v1)

- No public release, no Play Store / npm publish / marketing
- No cloud-hosted service — runs locally, on the user's machine
- No autonomous push/merge/delete without approval, at any build phase
- No multi-user support, no team features
- No custom LLM training — Nexus orchestrates existing agent CLIs/APIs, it does not replace them
- Computer vision / screen-awareness layer (`nexus see`) — **open scope item**, not committed for v1 (tracked separately, build only if explicitly greenlit later)

## 4. Users

Single user (the builder). Primary environment: Windows desktop, working across multiple project repos with a mix of the listed agents/IDEs already installed. All supported agents have a verified free access tier (ADR-015).

## 5. Functional Requirements

### 5.1 CLI Core
- FR-1: `nexus` with no args enters an interactive shell (`NEXUS >`) that accepts natural-language commands in addition to fixed subcommands.
- FR-2: `nexus <subcommand>` supports direct one-shot invocation without entering the shell.
- FR-3: A `.nexus/` folder is created per project on `nexus init`; a global config lives outside any project folder.

### 5.2 Agent Layer
- FR-4: All supported tools (Codex CLI, Antigravity CLI, Kiro, Cursor) are accessed through one common `Agent` interface: `run(task)`, `status()`, `capabilities()`. See ADR-015 for the free-only roster rationale and ADR-014 for the `capabilities()` field contract.
- FR-5: `nexus agents` lists all configured agents (Codex CLI, Antigravity CLI, Kiro, Cursor) and their live status (Ready / Installed / Unreachable).
- FR-6: `nexus open <tool>` launches the named tool directly.
- FR-7: Adding a new agent requires only a new adapter implementing the `Agent` interface — no changes to router, planner, or swarm logic. New agents may be added to the roster if they have a verified free access tier (ADR-015).

### 5.3 AI Router
- FR-8: `nexus ask "<task>"` classifies the task (domain, complexity, likely file impact) and recommends one agent with a stated reason.
- FR-9: Routing rules are user-editable (`config/router.json`), not hardcoded.
- FR-10: The user can always override the recommended agent before launch.

### 5.4 Shared Memory / Project Intelligence
- FR-11: `nexus scan` inspects the repo and produces a project profile (stack, frameworks, structure) stored in `.nexus/project/context.json`.
- FR-12: `nexus health` reports build/test/lint/dependency/security/Docker/GitHub status in one view.
- FR-13: Every agent invocation automatically receives the current project context — no manual re-explaining.
- FR-14: `nexus status` / `nexus explain` surface current project state and recent decisions in human-readable form.

### 5.5 Planner / Task Graph
- FR-15: `nexus mission "<goal>"` decomposes a natural-language goal into an ordered task graph with dependencies.
- FR-16: `nexus dashboard` shows live progress of an active mission.
- FR-17: A mission can be paused; resuming does not lose completed-task state.

### 5.6 Swarm Orchestrator
- FR-18: Defined agent roles: Architect, Coder, Debugger, Reviewer, Security, Researcher, Tester, DevOps, Documentation, GitHub Manager.
- FR-19: `nexus swarm "<goal>"` runs a multi-agent pipeline (Planner → Architect/Coder/Researcher → Tester) with visible per-stage progress.
- FR-20: Agents in a swarm communicate only through structured artifacts written to `.nexus/tasks/<task-id>/` — never through raw chat history passed hand-to-hand.

### 5.7 Review Handoff (first-class)
- FR-21: `nexus review` sends a completed implementation to a different agent for structured review (see schema in System Architecture doc).
- FR-22: Review output always includes: findings list (with severity + file + recommendation), test results, and an explicit decision (`approved` / `changes_requested`).
- FR-23: `nexus fix review` routes the exact structured findings back to the original implementing agent — no re-summarization by the user.
- FR-24: One review can be re-run after a fix (`nexus review` again) to confirm resolution; history of all rounds is retained under the task.

### 5.8 GitHub Integration
- FR-25: `nexus issue <n>` fetches and displays a GitHub issue with labels and a recommended agent.
- FR-26: `nexus investigate <n>` (Phase 4, read-only) runs analysis only: root-cause hypothesis, affected files, proposed approach — makes zero code changes. Ships before Warden exists (see ADR-011).
- FR-26a: `nexus solve <n>` (Phase 6, requires Warden) runs the full pipeline: branch → assign agent → investigate → modify → test → review → commit. Does not exist as a command until Warden is live.
- FR-27: `nexus pr` opens a pull request from the current branch's changes; PR creation always requires explicit confirmation.
- FR-28: Git push is never performed without an explicit approval step, regardless of daemon/swarm mode — and per ADR-012, every individual push requires its own approval, never a blanket one.

### 5.9 Docker Integration
- FR-29: `nexus docker` shows live container status (name, port, state).
- FR-30: Docker logs, Dockerfile, and compose config are readable inputs to the Diagnostics Engine (FR-31–33), not a separate silo.

### 5.10 Diagnostics Engine (first-class, cross-cutting)
- FR-31: `nexus diagnose` correlates evidence from Git (status/diff/recent commits), project files (package.json, configs), Docker (containers/logs/compose), and environment variables.
- FR-32: Output is a structured diagnosis: problem statement, evidence list, likely root cause, suggested fix.
- FR-33: No fabricated confidence percentage is shown in v1 (see ADR-006). An evidence-strength indicator (e.g. a qualitative bar) is acceptable; a numeric "confidence %" is not, until backed by real historical calibration data.
- FR-34: `[Ask agent to fix]` from a diagnosis routes directly into the Agent Layer with the diagnosis as structured input.

### 5.11 Warden (Permission System)
- FR-35: Every agent/role has a capability profile: `read_source`, `write_source`, `execute_commands`, `git_push`, `delete_files`, `network` — each independently scoped (allow / deny / approval-required).
- FR-36: Any action marked `approval-required` blocks and prompts the user with: agent, action, reason, risk level, and options (`Allow once` / `Allow for task` / `Deny` / `Show details`).
- FR-37: All agent actions (not just risky ones) are written to an audit log (`memory/agent-handoffs.jsonl` / `memory/events.jsonl`).
- FR-38: Default capability profiles ship conservative (no `git_push`, no `delete_files` without approval) and must be explicitly loosened by the user per project.

### 5.12 Background Daemon
- FR-39: `nexus daemon` runs watchers (Git, Tests, Dependencies, Security, GitHub, Docker) in the background.
- FR-40: On detecting a failure, the daemon auto-assigns an agent to investigate and, if configured, to attempt a fix — but never auto-pushes or auto-merges.
- FR-41: Daemon activity is fully visible in the audit log and via `nexus dashboard`.

### 5.13 IDE Control
- FR-42: `nexus ide <tool>` launches the named IDE; `nexus ide current` reports the active IDE/project/branch/open-file state where the IDE exposes that information.

## 6. Non-Functional Requirements

- NFR-1: **Safety over autonomy.** Any ambiguity between "let the agent proceed" and "ask the user" resolves to asking the user, for the entire lifetime of the product — not just v1.
- NFR-2: **Agent-agnostic core.** No component outside the Agent Layer may contain agent-specific logic (e.g. no `if tool == "codex"` outside the Codex adapter).
- NFR-3: **Inspectability.** Every multi-step workflow must be reconstructable after the fact purely from `.nexus/` artifacts, without relying on terminal scrollback.
- NFR-4: **Local-first.** No required cloud dependency beyond the agent APIs/CLIs and GitHub themselves.
- NFR-5: **Config over code.** Routing rules and permission profiles are editable JSON, not recompiled logic.

## 7. Success Criteria (v1 "complete product" definition)

Nexus v1 is considered complete when, for a real project:

1. The user can go from "GitHub issue number" to "tested, reviewed PR" using only Nexus commands.
2. At least two different agents have been used interchangeably for the same task type without any Nexus code change.
3. A Review Handoff round-trip (implement → review → fix → re-verify) has completed successfully at least once end-to-end.
4. A real Docker/project failure has been diagnosed correctly by `nexus diagnose` at least once.
5. No push, delete, or PR-merge action has ever occurred without an explicit approval prompt.
6. Full history of a completed mission is reconstructable from `.nexus/` alone.

## 8. Open Items

- OI-1: Computer vision / screen-awareness layer — in or out of scope, and if in, at which phase. (Tracked as ADR-009, still open.)
- ~~OI-2: Whether Warden trust scoring is manually configured per agent or derived from observed audit-log behavior over time.~~ — **Resolved.** Manual static configuration only for all of v1, including Daemon phase. See ADR-013.
- ~~OI-3: Default routing rules~~ — **Resolved.** See System Architecture §6a for the v1 `router.json` draft.
- ~~OI-4: Implementation language~~ — **Resolved.** Python 3.11+ / Typer / Pydantic / pytest. See ADR-010.
- ~~OI-5: Daemon polling defaults~~ — **Resolved.** See System Architecture §9.
- ~~OI-6: Agent roster and free-only constraint~~ — **Resolved.** Supported agents: Codex CLI, Antigravity CLI, Kiro, Cursor. Claude Code excluded (paid). Gemini CLI excluded (retired June 18, 2026). See ADR-015.
