# Nexus — Vision & Concept

**Status:** Approved concept, pre-implementation
**Owner:** [User]
**Related:** Standalone project. Explicitly separate from Project ATLAS (no shared codebase, no dependency in either direction).

---

## 1. The One-Line Pitch

Nexus is a control plane that coordinates heterogeneous AI coding agents through shared project context, structured handoffs, diagnostics, and development workflows — through a single CLI.

It is **not** another coding agent. It is the layer that manages the coding agents you already have (Claude, Codex, Gemini CLI, Kiro, Antigravity, Cursor) plus the tools around them (GitHub, Docker).

## 2. The Problem

A developer using multiple AI coding tools today has to:

- Remember which tool is best for which kind of task
- Manually switch between CLIs, IDEs, and browser tabs
- Re-explain project context to each tool separately
- Manually copy output from one tool into another for review
- Manually correlate Git status, Docker state, and agent output when debugging
- Manually create branches, run tests, and open PRs after an agent finishes

Every tool is isolated. There is no shared memory, no routing intelligence, and no coordination layer above them.

## 3. The Core Idea

```
                 YOU
                  │
                  ▼
             ┌─────────┐
             │  NEXUS  │
             └────┬────┘
                  │
      ┌───────────┼───────────┐
      ▼           ▼           ▼
   AI Agents    GitHub      Docker
      │
 ┌────┼─────────────┐
 ▼    ▼      ▼      ▼
Codex Claude Gemini Kiro
                    │
               Antigravity
```

One CLI. One shared project context. Every agent plugs into the same interface, the same memory, and the same permission system.

Agents are **replaceable**. Today it's Codex + Claude + Gemini. Tomorrow it could be a different set, or a local model. Nexus's architecture doesn't change either way — that's the point of the Agent Layer abstraction (see System Architecture doc).

## 4. What Using It Feels Like

```
cd my-project
nexus
```

```
NEXUS >
```

```
NEXUS > what's broken?
NEXUS > implement the fix
NEXUS > ask Claude to review it
NEXUS > run everything in Docker
NEXUS > commit this
NEXUS > create the PR
```

You never have to think about which underlying tool did the work.

## 5. Illustrative Scenarios

### 5.1 Task routing

```
nexus ask "I need to implement JWT authentication"
```

```
Analyzing task...

Type: Backend implementation
Complexity: Medium
Files likely affected: 8–15

Recommended agent:
→ Codex

Reason:
Strong repository-level coding + terminal workflow.

Launch Codex? [Y/n]
```

### 5.2 Review Handoff (first-class feature)

Codex finishes an implementation. Instead of the user manually pasting code into another chat:

```
nexus review
```

sends the implementation to a different agent (e.g. Claude) as a structured review request. The review comes back as structured findings, not prose:

```json
{
  "type": "review",
  "task_id": "task-042",
  "implementation_agent": "codex",
  "review_agent": "claude",
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

```
nexus fix review
```

routes those exact findings back to Codex — Codex doesn't start from scratch, it knows precisely what changed and why.

### 5.3 GitHub issue → PR pipeline

```
nexus issue 42
```

```
GitHub Issue #42
Users randomly get logged out.

Labels: bug, authentication, high-priority
Assigned agent: → Debugger / Codex

Start investigation? [Y/n]
```

```
Investigation complete.
Root cause: Refresh token expiry calculation.
Files affected: backend/auth/token.ts
Proposed fix: 3 files
Tests: ✓ 47 passed
```

```
nexus pr
```

creates the branch, commits, pushes, and opens the PR.

### 5.4 Diagnostics Engine (first-class feature, not just "Docker status")

```
nexus diagnose
```

Pulls evidence from multiple sources at once — Git, project files, Docker, environment:

```
DIAGNOSIS
────────────────────────────

Problem:
Backend cannot connect to PostgreSQL.

Evidence:
• PostgreSQL container starts successfully
• Backend starts before PostgreSQL is ready
• Recent compose changes modified startup order
• Backend logs show connection refusal

Likely root cause:
Database readiness race condition.

Suggested fix:
Add PostgreSQL healthcheck and configure
backend startup dependency.

[Ask agent to fix]
```

Note: no fabricated confidence percentage (e.g. "94%") in v1. Confidence scoring is deferred until Nexus has actually collected historical diagnosis → fix → outcome data to calibrate against (see ADR-006).

### 5.5 Mission mode — single natural-language request

```
nexus "Add Google OAuth to this project and make sure it works with Docker."
```

```
Mission: Add Google OAuth

[1/7] Researching OAuth requirements     ✓
[2/7] Designing architecture             ✓
[3/7] Implementing backend               ✓
[4/7] Implementing frontend              ✓
[5/7] Updating Docker                    ✓
[6/7] Running tests                      ✓
[7/7] Reviewing changes                  ⟳

Current agent: Claude
Current task: Security review
```

### 5.6 Background daemon (later phase)

```
NEXUS DAEMONS
────────────────────────────
Git Watcher          ●
Test Monitor         ●
Dependency Monitor   ●
Security Monitor     ●
GitHub Monitor       ●
Docker Monitor       ●
```

```
[ALERT]
CI failed on branch: feature/auth
Failure: TypeScript compilation
Agent assigned: Debugger
Status: Investigating...
```

```
[RESOLVED]
Debugger fixed issue.
Tests: 52/52 passed.
No push performed. Approval required.
```

Auto-diagnosis and auto-fix are allowed. Auto-push and auto-delete are never allowed without explicit approval — this is a hard boundary, not a default (see ADR-002).

## 6. What This Is Not

- Not a new AI coding agent — it orchestrates existing ones.
- Not a public product for v1 — single-user, personal tool.
- Not part of ATLAS — no shared code, no shared runtime, no merge planned.
- Not a fully autonomous system — every destructive or externally-visible action (push, delete, PR merge) requires explicit human approval, permanently, regardless of build phase.

## 7. Guiding Principle

> Agents communicate through structured artifacts, not vague conversational state.

Every stage of work (task → plan → implementation → test results → review → fix → re-test → final) leaves a structured record in `.nexus/`. This gives Nexus persistent, inspectable development history — and makes the whole system debuggable, auditable, and agent-agnostic.
