# Nexus — Implementation Plan

**Status:** Draft v1
**Depends on:** PRD, ADRs, System Architecture — build order below must not be reordered without a new ADR (see ADR-008).

---

## 0. Ground Rules

- Every phase ends only when its test cases pass, not when the code "looks done."
- No phase after Phase 5 (Warden) may write to source, execute shell commands, push to git, or delete files without Warden gating already being in place — this is enforced by phase ordering itself, not left to discipline.
- Every stage's structured artifacts (per `.nexus/` schema) must be inspected manually at least once per phase to confirm the schema is actually being followed, not just documented.

---

## Phase 1 — CLI Core + Universal Launcher

**Scope:** FR-1, FR-2, FR-3, FR-5, FR-6 (from PRD)

**Build:**
- Project scaffold: Python 3.11+ package, Typer CLI entry point, Pydantic models package for `.nexus/` schemas, pytest configured (per ADR-010)
- Command parser + subcommand dispatch
- Interactive shell mode (`NEXUS >`)
- `.nexus/` folder scaffolding on `nexus init`
- `nexus agents` (static status list to start — real health checks land in Phase 2)
- `nexus open <tool>`

**Test cases:**
- TC-1.1: `nexus init` in an empty directory creates the full `.nexus/` folder structure exactly as specified in the architecture doc.
- TC-1.2: `nexus init` run a second time in the same directory does not overwrite existing `context.json` / task history.
- TC-1.3: `nexus open codex` launches Codex; `nexus open doesnotexist` fails with a clear error, not a stack trace.
- TC-1.4: Interactive shell accepts both `agents` and `nexus agents` equivalently once inside the shell.
- TC-1.5: `nexus --help` and per-command `--help` output correct usage.

**Exit criteria:** Can be used daily as a pure launcher for at least a few days before Phase 2 starts.

---

## Phase 2 — Agent Abstraction

**Scope:** FR-4, FR-5 (real health checks), FR-7

**Agent roster (ADR-015 — free-only):** Codex CLI, Antigravity CLI (`agy`), Kiro, Cursor.
Claude Code (paid, no free tier) and Gemini CLI (retired June 18, 2026) are not included.

**Pre-build step — capability verification pass:**
Before writing any adapter, do a quick headless check on each of the four tools: can it run non-interactively, does it accept piped/file context, does it support a `--no-interactive` or equivalent flag? This determines the real `invocation_mode` and `terminal_access` values for each adapter's `capabilities()` return — do not guess from documentation, verify against actual installed behavior. Record findings before starting adapter code; the initial estimates table in System Architecture §4 is a starting point, not ground truth.

**Build:**
- `AgentCapabilities` Pydantic model (fields: `repo_reasoning`, `terminal_access`, `multi_file_edit`, `max_context_tokens`, `supports_streaming`, `invocation_mode`) — see System Architecture §4 for the full schema
- `Agent` base interface (`run`, `status`, `capabilities`)
- Adapters: Codex CLI, Antigravity CLI, Kiro, Cursor (four adapters, one file each)
- Live status detection per adapter
- Router exclusion logic: any adapter returning `invocation_mode = ide_only` is automatically skipped for Swarm and Daemon routing stages

**Test cases:**
- TC-2.1: Each adapter's `status()` correctly reports Ready/Installed/Unreachable against real local installs for all four agents.
- TC-2.2: `run()` on each adapter with a trivial task (e.g. "print hello world to a file") succeeds and returns a populated `AgentResult`. For any adapter confirmed as `ide_only`, `run()` opens the IDE with the task queued — test confirms the IDE opens and no headless result is awaited.
- TC-2.3: Adding a new adapter (build a throwaway 5th adapter as a test) requires touching only the new adapter file — no edits to router, planner, or CLI core (this directly verifies ADR-005).
- TC-2.4: `capabilities()` returns a fully-populated `AgentCapabilities` object for every adapter. `invocation_mode` differs between at least two adapters (e.g. `cli` vs. `ide_only`), and `terminal_access` differs between at least two adapters — confirming the Router has real signal to route on (verifies ADR-014).
- TC-2.5: An adapter failure (tool not installed, auth missing) surfaces a clear, specific error — never a silent no-op.
- TC-2.6: Any adapter with `invocation_mode = ide_only` is confirmed absent from the Router's candidate list when the Router is resolving a Swarm or Daemon stage target (verify via a Router unit test with a mocked agent registry, not just by reading the code).

**Exit criteria:** All four adapters pass TC-2.1 through TC-2.6. Every `AgentCapabilities` field value is verified against real behavior, not copied from docs. No agent-specific code exists outside its adapter file.

---

## Phase 3 — Project Intelligence + Shared Memory

**Scope:** FR-11, FR-12, FR-13, FR-14

**Build:**
- `nexus scan` → `project/context.json`
- `nexus health` (build/test/lint/deps/security/docker/GitHub status)
- `nexus status`, `nexus explain`
- Shared Memory read/write layer (`tasks/`, `memory/*.jsonl`)

**Test cases:**
- TC-3.1: `nexus scan` on a real React+Node project correctly identifies stack, frameworks, and structure.
- TC-3.2: `nexus health` correctly flags a deliberately broken build (e.g. a syntax error introduced on purpose) as failing.
- TC-3.3: Two consecutive agent runs (from Phase 2) both receive the same `context.json` automatically, without the user re-explaining the project (verifies FR-13).
- TC-3.4: `memory/events.jsonl` is append-only — a manual attempt to edit a past entry via the normal API is rejected or not exposed.
- TC-3.5: `nexus explain` after several scans/health checks produces an accurate human-readable summary of current project state.

**Exit criteria:** Any agent invocation automatically carries real project context; project state can be inspected without opening the code.

---

## Phase 4 — GitHub + Docker Integration, Diagnostics Engine

**Scope:** FR-25, FR-26, FR-27 through FR-34

**Build:**
- `nexus issue <n>`
- `nexus investigate <n>` — read-only issue analysis command (see ADR-011). `nexus solve` does **not** exist yet at this phase; there is no partial/crippled version of it.
- `nexus pr` (behind manual confirmation)
- `nexus docker`
- Diagnostics Engine (`nexus diagnose`) pulling from Git + project + Docker + env

**Test cases:**
- TC-4.1: `nexus issue 42` against a real repo correctly displays title, labels, and a recommended agent.
- TC-4.2: `nexus investigate 42` produces a root-cause hypothesis and proposed file list without making any code changes (verify no files are modified — this is enforced structurally by the command not calling any write path, not by a Warden check that doesn't exist yet).
- TC-4.2a: `nexus solve 42` is confirmed **not present** in the CLI's command list at this phase (explicit negative test — guards against ADR-011 quietly eroding).
- TC-4.3: `nexus docker` accurately reflects real container state (start/stop a test container and confirm status updates).
- TC-4.4: Deliberately break a docker-compose startup order (as in the architecture doc's Postgres example) and confirm `nexus diagnose` identifies the same root cause a human would.
- TC-4.5: `nexus diagnose` output contains no numeric confidence score (verifies ADR-006 compliance) — this should be an explicit automated check, not just a manual read-through.
- TC-4.6: `nexus pr` always stops at a confirmation prompt before creating anything, even when run non-interactively (fails safe, not silently skips confirmation).

**Exit criteria:** Diagnostics correctly root-causes at least one real, naturally-occurring failure (not just the seeded test case) before moving on.

---

## Phase 5 — Warden (Permission System)

**Scope:** FR-35 through FR-38

**Build:**
- Capability profile schema + loader (`config/permissions.json`)
- Central Warden check function, wired into every write/execute/push/delete/network call site across all components built so far
- Approval prompt UI (`Allow once` / `Allow for task` / `Deny` / `Show details`)
- Audit logging to `memory/events.jsonl`

**Test cases:**
- TC-5.1: An agent with `write_source: deny` cannot write a file, full stop — attempt is blocked and logged.
- TC-5.2: An agent with `write_source: approval` triggers a prompt; choosing `Deny` results in no file change and a logged denial.
- TC-5.3: Choosing `Allow for task` permits further writes within the same task without re-prompting, but a **new** task still requires a fresh approval.
- TC-5.4: `git_push` is `approval` by default for every shipped agent profile — verify this is true for all adapters from Phase 2, not just one.
- TC-5.4a: Within a single task, trigger two separate `git_push` actions — confirm **both** require their own `Allow once` prompt, and that choosing `Allow for task` on the first push does not silently cover the second (verifies ADR-012's push/delete carve-out).
- TC-5.4b: Within a single task, trigger two separate `write_source` (medium-risk) actions after choosing `Allow for task` on the first — confirm the second proceeds without re-prompting, and a third action under a **different** `task_id` (same mission) does re-prompt (verifies ADR-012's task_id scoping boundary).
- TC-5.5: Attempt a code path that tries to bypass Warden directly (a deliberate red-team test call) — confirm it's architecturally impossible, not just discouraged (verifies ADR-002/ADR-004 are actually enforced, not aspirational).
- TC-5.6: Every allowed AND denied action appears in `memory/events.jsonl` with correct timestamp, agent, action, result, and the `task_id` the approval was scoped to.

**Exit criteria:** No write/execute/push/delete action can occur anywhere in the system without passing through Warden. This is the hard gate before Phase 6.

---

## Phase 6 — Planner + Swarm Orchestrator + Review Handoff

**Scope:** FR-15 through FR-24

**Build:**
- `nexus mission "<goal>"` → task graph
- `nexus dashboard`
- Swarm pipeline (Planner → role agents → Tester)
- Review Handoff (`nexus review`, `nexus fix review`) with full `review.json` schema
- `nexus solve <n>` — now that Warden exists, this ships as the full write-capable pipeline built on top of `nexus investigate` from Phase 4 (see ADR-011)

**Test cases:**
- TC-6.1: `nexus mission "add a health-check endpoint"` produces a task graph with correct dependency ordering (endpoint code before tests, etc.).
- TC-6.2: A mission interrupted mid-way (kill the process after task 3 of 7) resumes correctly from Phase 3's artifact state on next run (verifies idempotency, System Architecture §10).
- TC-6.3: A full swarm run on a small real task produces `implementation.json` and `review.json` for the same `task_id`, both correctly cross-referenced.
- TC-6.4: Review Handoff round 2 (`review-2.json`) exists as a separate file after a fix-and-re-review cycle — round 1 is untouched (verifies ADR-003).
- TC-6.5: `nexus fix review` passes the exact structured findings back to the implementing agent — confirm via logs that the agent's input included the specific `findings` array, not a re-summarized version.
- TC-6.6: A review with `decision: blocked` (e.g. seeded security finding) halts the pipeline and requires explicit human sign-off, not just agent-side auto-continue.
- TC-6.7: `nexus solve 42` end-to-end on a real issue produces a committed, tested, reviewed branch — and the eventual `git push`/PR step still requires its own `Allow once` approval per ADR-012, even though the rest of the pipeline ran automatically.

**Exit criteria:** A full task → implement → review → fix → re-verify cycle completes with two different agents, entirely through structured artifacts, with correct Warden gating throughout.

---

## Phase 7 — Background Daemon

**Scope:** FR-39 through FR-41

**Build:**
- Watchers: Git, Tests, Dependencies, Security, GitHub, Docker
- Alert → auto-diagnose → optional auto-fix-attempt pipeline
- Dashboard integration

**Test cases:**
- TC-7.0: `config/daemon.json` loads with the documented defaults (System Architecture §9) when not overridden; `global.enabled` and `global.auto_fix_attempt` both default to `false` — confirm the daemon does not run at all on a fresh install without explicit opt-in.
- TC-7.1: Breaking a test on a watched branch triggers an alert within the configured polling interval (300s default for the tests watcher).
- TC-7.2: Daemon-triggered diagnosis and fix-attempt still passes through Warden identically to a manually-triggered one (no daemon-specific bypass exists).
- TC-7.3: A daemon-detected fix is never pushed automatically — confirm the branch remains local/unpushed and a pending-approval entry appears in the dashboard.
- TC-7.4: Stopping the daemon cleanly leaves no orphaned watcher processes.
- TC-7.5: Daemon activity across a multi-hour run produces a complete, readable audit trail in `memory/events.jsonl`.

**Exit criteria:** Daemon can run unattended for an extended period with zero unauthorized writes, pushes, or deletions — verified against the audit log, not assumed.

---

## Phase 8 — IDE Control (can run in parallel with Phase 4 onward)

**Scope:** FR-42

**Build:**
- `nexus ide <tool>`, `nexus ide current`

**Test cases:**
- TC-8.1: `nexus ide antigravity` launches Antigravity against the current project directory.
- TC-8.2: `nexus ide current` correctly reports IDE/project/branch where the IDE exposes that data; degrades gracefully (clear "not available" message) where it doesn't.

**Exit criteria:** Optional convenience layer working for at least one IDE with genuine automation support.

---

## Deferred / Not Started

- Computer vision / screen-awareness layer — blocked on ADR-009 resolution. No test cases defined until greenlit.
- Calibrated diagnostic confidence scoring — blocked on sufficient historical outcome data existing (ADR-006). No test cases defined until that data collection mechanism itself is designed.

---

## Cross-Phase Regression Checklist

Run before considering any phase "done," not just its own new test cases:

- [ ] All previous phases' test cases still pass
- [ ] `memory/events.jsonl` remains append-only and complete
- [ ] No component outside Agent Layer contains tool-specific logic (spot-check via grep for tool names outside `agents/` adapters)
- [ ] No write/execute/push/delete path exists that bypasses Warden (once Phase 5 is complete)
- [ ] `.nexus/` folder for a real test project remains fully human-readable and reconstructable into a narrative of what happened
- [ ] No reference to `claude`, `gemini`, or `gemini-cli` exists in `router.json`, `permissions.json`, or any adapter file (ADR-015 — these tools are excluded from v1)
