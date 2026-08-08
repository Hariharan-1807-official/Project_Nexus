# Nexus — Architecture Decision Records (ADR)

Each ADR documents a decision that should **not** be casually revisited during implementation. If a future change contradicts one of these, treat that as a deliberate re-decision requiring a new ADR that supersedes it — not a silent drift.

---

## ADR-001: Nexus is a standalone project, separate from ATLAS

**Status:** Accepted

**Decision:** Nexus has no shared codebase, runtime, or repository with Project ATLAS. It is not a subsystem of ATLAS and is not planned to be merged into it.

**Rationale:** Both are "control everything" style systems conceptually, but they solve different problems (developer-agent orchestration vs. broader personal system control). Merging them prematurely risks scope confusion in both.

**Consequences:** Any future integration between the two must be an explicit, separately-decided ADR — never assumed.

---

## ADR-002: No autonomous destructive actions, ever — not just in v1

**Status:** Accepted

**Decision:** Git push, file deletion, PR merge, and any other externally-visible or irreversible action always require explicit human approval (`Allow once` / `Allow for task` / `Deny`), regardless of build phase, daemon mode, or swarm mode.

**Rationale:** Autonomous agents with unsupervised destructive capability is the single highest-risk failure mode of this entire project (a wrecked repo, deleted files, or a bad push at 3am with no one watching). The value of automation (diagnosis, investigation, drafting fixes) does not require removing the human checkpoint on irreversible actions.

**Consequences:** The Warden system (see ADR-004) must be built before any agent is granted write access to source, and before the Daemon (background watchers) is enabled at all.

---

## ADR-003: Agents communicate through structured artifacts, not conversational hand-off

**Status:** Accepted

**Decision:** All multi-agent coordination (Swarm, Review Handoff, mission pipelines) happens by reading/writing structured files under `.nexus/`, never by one agent's raw chat transcript being pasted into another's context.

**Rationale:** Structured artifacts are inspectable, diffable, replayable, and durable across sessions. Conversational hand-off is lossy, unauditable, and breaks the moment a session ends.

**Consequences:** Every new multi-agent workflow must define its artifact schema before implementation, not after. See System Architecture doc §3 for schemas.

---

## ADR-004: Warden (permission system) is designed before Swarm/Daemon are enabled

**Status:** Accepted

**Decision:** Build order places Warden's capability-profile and approval-prompt system ahead of enabling Swarm in write mode and ahead of enabling the Daemon. Agent abstraction and read-only diagnostics can be built and used before Warden exists; anything that writes to source, git, or the filesystem cannot.

**Rationale:** Directly follows from ADR-002. A permission system retrofitted onto agents that already have unrestricted write access is far weaker than one designed in from the start.

**Consequences:** Slower path to "agents can write code," but this is accepted as correct, not a shortcut to optimize away.

---

## ADR-005: The Agent Layer interface is the one contract everything else depends on

**Status:** Accepted

**Decision:** All agent tools (Claude, Codex, Gemini CLI, Kiro, Antigravity, Cursor, and any future tool) are accessed exclusively through one interface: `run(task)`, `status()`, `capabilities()`. No component above the Agent Layer (Router, Planner, Swarm, Diagnostics) may contain tool-specific logic.

**Rationale:** This is what makes agents replaceable (per the Vision doc's core thesis — "the agents are replaceable, Nexus doesn't"). If this contract leaks, every future agent swap becomes a multi-file refactor instead of a new adapter.

**Consequences:** Adding a new agent = write one new adapter file. Removing/replacing an agent = delete one adapter file. This must remain true throughout the project's life; any PR that violates it should be treated as a bug, not a style preference.

---

## ADR-006: No fabricated confidence scores in diagnostics

**Status:** Accepted

**Decision:** `nexus diagnose` output never displays a numeric confidence percentage (e.g. "94%") unless it is backed by real historical calibration data (diagnosis → fix → verified-correct outcome, tracked over time). Until that data exists, diagnostics show evidence and reasoning only, with at most a qualitative strength indicator.

**Rationale:** A fabricated precision number is actively worse than none — it invites misplaced trust in a root-cause guess that hasn't been validated against outcomes.

**Consequences:** A future "calibrated confidence" feature is possible, but it is a distinct, later feature gated on outcome-tracking data existing — not a cosmetic addition to v1.

---

## ADR-007: Diagnostics Engine and Review Handoff are first-class components, not sub-features

**Status:** Accepted

**Decision:** Diagnostics Engine is architected as its own component that reads from Git, Docker, project files, and environment together — not folded into "Docker Integration." Review Handoff is architected as its own protocol with a defined JSON schema — not folded into "Swarm Orchestrator" as an implicit behavior.

**Rationale:** Both patterns are independently valuable and reusable outside their originating context (diagnostics can be invoked outside a Docker failure; review handoff can be invoked outside a swarm run). Treating them as first-class keeps their interfaces clean and testable in isolation.

**Consequences:** Each gets its own schema, its own section in the System Architecture doc, and its own test cases in the Implementation Plan.

---

## ADR-008: Complete architecture, sequential build — not staged MVP releases

**Status:** Accepted

**Decision:** The full system architecture (all components in the PRD) is designed upfront and locked via these ADRs. Implementation proceeds in a fixed dependency order (CLI Core → Agent Layer → Project Intelligence → GitHub/Docker → Planner → Swarm → Warden → Daemon). Components not yet built are simply not invoked — there is no "v0.1 public/visible release" at intermediate stages.

**Rationale:** The build order is dictated by technical dependency (you cannot build Swarm reliably on an unproven Agent Layer), not by a deliberate "ship small first" MVP philosophy. The user wants a complete product, and this order gets there without debugging multiple unproven layers simultaneously.

**Consequences:** "Complete" is measured against the PRD's Success Criteria (§7), not against how early something became usable.

---

## ADR-009: Computer vision / screen-awareness layer is explicitly undecided

**Status:** Open — not yet accepted or rejected

**Decision (pending):** `nexus see` and any screen-state-awareness functionality is tracked as an open scope item. It is not included in the locked v1 scope and must not be started until explicitly greenlit via a follow-up ADR.

**Rationale:** Carried over from the original concept doc's "Personal Reality OS" tangent; never explicitly confirmed as in-scope by the user.

**Consequences:** If greenlit later, it becomes its own accepted ADR and gets its own architecture section. Until then, no design or implementation work should target it.

---

## ADR-010: Implementation language is Python

**Status:** Accepted

**Decision:** Nexus is implemented in Python 3.11+, using Typer for the CLI layer, Pydantic for all `.nexus/` artifact schemas (task, review, diagnosis, config), and pytest for the test cases defined in the Implementation Plan.

**Rationale:** The project is fundamentally an orchestration layer around subprocesses and CLI tools, not a UI-heavy or performance-critical system — Python's subprocess/IO ergonomics fit directly. It also matches existing familiarity, removing a learning-curve tax from a project that's already large in scope.

**Consequences:** The Agent interface pseudocode in the System Architecture doc is literal Python from this point forward, not illustrative pseudocode. Any future component (Warden, Daemon, adapters) is written in Python unless a specific, documented reason forces an exception (e.g. a tool only exposing a non-Python native binding) — and any such exception gets its own ADR rather than being a silent one-off.

---

## ADR-011: `investigate` and `solve` are separate commands, not one command with hidden phase-gated behavior

**Status:** Accepted

**Decision:** `nexus investigate <issue>` is a read-only command (fetch issue, analyze, propose root cause and file list, no writes) and ships in Phase 4. `nexus solve <issue>` is the full write-capable pipeline (branch, modify, test, review, commit) and does not exist as a command until Phase 6, once Warden is live.

**Rationale:** A `solve` command that silently can't write code during Phase 4 is a confusing UX and an ADR-002 risk in disguise — it invites someone to assume "solve" means "solve" before the safety layer exists. Splitting into two honestly-named commands removes the ambiguity entirely: `investigate` never implies a write, `solve` is only ever available once it's safe to mean what it says.

**Consequences:** PRD FR-25/26/27 and the Implementation Plan's Phase 4/Phase 6 test cases are updated to reflect two distinct commands rather than one command with deferred capability.

---

## ADR-012: Warden approval scope is bound to `task_id`, never to session — and high-risk actions ignore scoping entirely

**Status:** Accepted

**Decision:** "Task" in Warden's approval scoping always means one `.nexus/tasks/<id>` unit of work — never a conversational session or CLI process lifetime. `Allow for task` grants matching-risk approvals only within that specific task_id; a new task_id always requires a fresh prompt, even within the same mission or session. Additionally, `git_push` and `delete_files` — regardless of chosen scope — are always single-action `Allow once` approvals. They can never be blanket-approved for a whole task, mission, or session.

**Rationale:** "Task" was ambiguous between two real meanings in the system (a Shared Memory task record vs. a user's working session), and leaving it ambiguous would have meant either an accidental over-broad grant (session-scoped) or an unenforced one (nobody agreeing on what it meant). Tying scope strictly to the artifact-backed `task_id` keeps it consistent with ADR-003 (structured artifacts, not conversational state) — the scope of an approval is itself an inspectable fact in `.nexus/`, not an implicit runtime assumption. The additional carve-out for push/delete directly reinforces ADR-002: even "for this one task" is too broad a blanket for genuinely irreversible actions.

**Consequences:** Warden's approval prompt and its audit log entries must record the `task_id` an approval was scoped to. TC-5.3 and TC-5.4 in the Implementation Plan are updated to test this boundary explicitly, including a case where a task performs two separate `git_push` actions and both require separate approvals.

---

## ADR-013: Warden trust scoring is manual, static configuration — no dynamic scoring in v1

**Status:** Accepted

**Decision:** Capability profiles in `config/permissions.json` are always manually configured, for the entire v1 build including through the Daemon phase. Dynamic or derived trust scoring — where an agent "earns" broader permissions from a positive audit-log track record — is explicitly not in scope for v1.

**Rationale:** Dynamic trust scoring cuts directly against two of the project's core principles. First, NFR-5 (config over code): if Warden's decisions become a function of accumulated runtime history rather than a static, inspectable config file, the permission model is no longer auditable from a single file. Second, ADR-003 (structured artifacts, not conversational state): trust derived from behavioral observation is the permission-system equivalent of conversational state — it's runtime-accumulated, not explicitly authored. There is also a specific safety concern: if trust is earned automatically, a compromised or subtly misbehaving agent could accumulate a run of unremarkable actions before doing something harmful, gradually climbing toward `git_push` approval without any deliberate human decision. That is not a trade worth making for the automation convenience it buys.

**Consequences:** The Daemon phase (Phase 7) does not need to design or implement any trust-scoring mechanism — it simply uses whatever static profiles are configured in `permissions.json`, identical to every other component. If dynamic trust scoring is wanted later, it is a distinct, separately-scoped feature built on top of the audit log (which will already exist from Warden's logging) — not something solved inline. It requires its own ADR, its own schema, and its own safety analysis before any implementation begins.

---

## ADR-014: `AgentCapabilities` fields are a defined contract, verified per-agent during Phase 2

**Status:** Accepted

**Decision:** The `capabilities()` method on every adapter returns a structured `AgentCapabilities` object with the following defined fields:

- `repo_reasoning` (bool) — can the agent reason over an existing multi-file codebase, not just a single snippet
- `terminal_access` (bool) — can the agent execute shell commands itself, vs. only proposing them
- `multi_file_edit` (bool) — can the agent make coordinated changes across multiple files in one pass
- `max_context_tokens` (int, approximate) — rough ceiling for the model's context window; used by the Router to route large-repo tasks away from smaller-context tools
- `supports_streaming` (bool) — whether the adapter can surface incremental output; relevant for how Nexus renders progress in the dashboard
- `invocation_mode` (enum: `cli` / `api` / `ide_only`) — determines whether the adapter shells out to a subprocess, calls an HTTP API, or can only launch the tool interactively (`ide_only` means `run()` amounts to "open the IDE with this task queued," not true headless execution)

**Rationale:** Without defined fields, `capabilities()` is structurally present but functionally useless — the Router has no guaranteed signals to route on, and TC-2.4's "capabilities differ meaningfully between agents" check has no agreed-upon vocabulary. `invocation_mode` is particularly important: Kiro's `ide_only` status (if confirmed during Phase 2 verification) means it is unsuitable for Swarm or Daemon automation and should only be reachable via `nexus open`. That distinction cannot be made without a typed field.

**Consequences:** The initial field values for each adapter are best guesses going into Phase 2 — they must be verified against each tool's actual current behavior (headless test, piped context, non-interactive mode) before the adapters are considered complete. TC-2.4 is updated to test that `invocation_mode` differs between at least two adapters, and that any adapter with `invocation_mode: ide_only` is excluded from Swarm and Daemon task routing. No adapter-specific capability values are locked in this ADR; they are determined empirically during Phase 2 and recorded in the adapter files.

---

## ADR-015: Only free-access agents are included in the v1 agent roster

**Status:** Accepted

**Decision:** Nexus v1 supports only agents that are free to access with no mandatory paid subscription. The v1 agent roster is:

| Agent | Tool | Free access basis |
|---|---|---|
| Codex CLI | OpenAI Codex CLI | Free tier available (usage-capped, rolling window) |
| Antigravity CLI | Google Antigravity CLI | Free during public preview; successor to Gemini CLI (retired June 18, 2026) |
| Kiro | AWS Kiro | Free tier (50 interactions/month) |
| Cursor | Cursor | Free Hobby tier available |

Excluded agents and reasons:

- **Claude Code** — no free tier; requires $20/month Claude Pro minimum. Excluded from v1.
- **Gemini CLI** — retired June 18, 2026. All individual/free-tier access ended; Google's official migration path is Antigravity CLI. The `gemini` command is dead; the adapter would be a no-op.

**Rationale:** Nexus is a personal, single-developer tool (PRD §4). Adding agents that require paid subscriptions the user does not already have creates a mandatory cost barrier to running v1 at all. The free-only constraint keeps the system fully operable without any subscription purchases. Agents on this list are included because they have verified free access paths as of the project's current date; this is checked, not assumed. Future agents may be added if they have a free tier — each addition gets a new ADR entry or an amendment here.

**Consequences:** All references to "Claude" and "Gemini CLI" in the PRD, System Architecture doc, Vision doc agent list, and Implementation Plan adapters are updated to reflect the new roster. The `router.json` defaults in System Architecture §6a are updated to route across the four supported agents only. Phase 2 builds adapters for exactly these four tools, not six. The review handoff examples that showed `claude` as `review_agent` should be understood as illustrative — in v1 the review agent will be one of the four listed above, selected by the Router.
