# Nexus — Usage Guide

> One CLI. One shared context. Every AI coding agent you already have.

---

## Installation

From the project root:

```powershell
pip install -e .
```

Verify:

```powershell
nexus --help
```

---

## The Two Ways to Use Nexus

### 1. One-shot (direct subcommand)

```powershell
nexus <command> [args]
```

### 2. Interactive shell

```powershell
nexus
```

```
NEXUS > <command>
```

Inside the shell, both `agents` and `nexus agents` work equivalently.

---

## Commands

### `nexus init`

Initialises the `.nexus/` folder structure in the current (or specified) directory.
Safe to run multiple times — never overwrites existing files.

```powershell
nexus init                  # initialise current directory
nexus init C:\my-project    # initialise a specific path
```

Creates:
```
.nexus/
├── project/
│   ├── context.json        ← populated by nexus scan (Phase 3)
│   ├── architecture.md
│   └── conventions.md
├── tasks/                  ← task artifacts written here by agents
├── memory/
│   ├── decisions.jsonl     ← append-only decision log
│   ├── agent-handoffs.jsonl
│   └── events.jsonl        ← full audit trail
└── config/
    ├── agents.json         ← which agents are enabled
    ├── router.json         ← routing rules (editable)
    ├── permissions.json    ← Warden capability profiles
    └── daemon.json         ← background watcher config
```

---

### `nexus agents`

Lists all configured agents with **live status** and version.

```powershell
nexus agents
```

```
╭─────────────────┬─────────┬────────┬───────────────────┬───────────────────────────────────────╮
│ Agent           │ Command │ Status │ Version           │ Note                                  │
├─────────────────┼─────────┼────────┼───────────────────┼───────────────────────────────────────┤
│ Codex CLI       │ codex   │ ready  │ codex-cli 0.147.0 │ OpenAI Codex CLI — free tier          │
│ Antigravity CLI │ agy     │ ready  │ 1.1.11            │ Google Antigravity CLI — free preview │
│ Kiro            │ kiro    │ ready  │ 1.0.212           │ AWS Kiro — free tier                  │
│ Cursor          │ cursor  │ ready  │ 3.15.6            │ Cursor — free Hobby tier              │
╰─────────────────┴─────────┴────────┴───────────────────┴───────────────────────────────────────╯
```

**Status values:**
- `ready` — installed and responding
- `installed` — found but didn't respond as expected
- `unreachable` — not found on PATH

---

### `nexus open <agent>`

Launches a named agent or IDE. Non-blocking — returns to the shell immediately.

```powershell
nexus open kiro         # opens Kiro with current directory
nexus open cursor       # opens Cursor with current directory
nexus open codex        # launches Codex CLI
nexus open antigravity  # launches Antigravity CLI
```

If the tool isn't installed, you'll get a clear error with the install command.

---

## Agent Roster (v1 — free only)

| Agent | Command | Headless mode | Terminal access | Context |
|---|---|---|---|---|
| Codex CLI | `codex` | `codex exec "<prompt>"` | ✓ | 200k |
| Antigravity CLI | `agy` | `agy --print "<prompt>"` | ✓ | 1M |
| Kiro | `kiro` | `kiro chat "<prompt>" --mode agent` | — | 128k |
| Cursor | `cursor` | `cursor agent "<prompt>"` | — | 200k |

**Not included (and why):**
- Claude Code — no free tier ($20/month minimum)
- Gemini CLI — retired June 18, 2026 (replaced by Antigravity CLI)

---

## Configuration Files

All config lives in `.nexus/config/` and is plain JSON — edit directly, no recompile needed.

### `agents.json` — enable/disable agents

```json
{
  "agents": [
    { "name": "codex",       "enabled": true,  "executable": "codex" },
    { "name": "antigravity", "enabled": true,  "executable": "agy"   },
    { "name": "kiro",        "enabled": true,  "executable": "kiro"  },
    { "name": "cursor",      "enabled": false, "executable": "cursor" }
  ]
}
```

### `router.json` — routing rules (who handles what)

```json
{
  "rules": [
    {
      "task_type": "backend_coding",
      "signals": ["api", "backend", "database", "server", "endpoint"],
      "preferred_agents": ["codex", "antigravity"]
    }
  ],
  "default_agent": "codex",
  "fallback_on_unavailable": true
}
```

Signal matching is keyword-based in v1. Edit freely — changes take effect immediately.

### `permissions.json` — Warden capability profiles

```json
{
  "codex": {
    "read_source":      "allow",
    "write_source":     "approval",
    "execute_commands": "approval",
    "git_push":         "approval",
    "delete_files":     "approval",
    "network":          "deny"
  }
}
```

Values: `allow` / `deny` / `approval`. All agents ship conservative by default.

---

## Interactive Shell — Full Command Reference

Inside `NEXUS >`:

| Command | What it does |
|---|---|
| `init [path]` | Initialise .nexus/ here or at path |
| `agents` | Live agent status table |
| `open <agent>` | Launch an agent |
| `help` | Show command list |
| `exit` / `quit` | Leave the shell |

Both `agents` and `nexus agents` work — prefix is optional.

---

## Easter Eggs

Because every good CLI deserves a few.

Try these inside the interactive shell (`nexus` then `NEXUS >`):

| Command | What happens |
|---|---|
| `hello` | Nexus says hi |
| `roast` | One of the agents gets roasted |
| `fortune` | Developer fortune cookie |
| `haiku` | A haiku about AI coding |
| `matrix` | Boot sequence |
| `sudo` | Warden has thoughts |
| `rm -rf` | Also Warden has thoughts |
| `why` | The real reason Nexus exists |
| `zen` | The guiding principle |
| `42` | You know |
| `coffee` | ☕ |
| `flip` | (╯°□°）╯︵ ┻━┻ |

---

## Build Phases

Nexus is built in phases. Commands available now vs. coming later:

| Phase | Status | Commands |
|---|---|---|
| Phase 1 — CLI Core | ✅ Complete | `init`, `agents`, `open`, interactive shell |
| Phase 2 — Agent Abstraction | ✅ Complete | Live status, capability profiles, adapter layer |
| Phase 3 — Project Intelligence | ✅ Complete | `scan`, `health`, `status`, `explain` |
| Phase 4 — GitHub + Docker + Diagnostics | ✅ Complete | `issue`, `investigate`, `docker`, `diagnose`, `pr` |
| Phase 5 — Warden | 🔜 Next | Permission prompts, audit log |
| Phase 6 — Planner + Swarm + Review | 🔜 | `mission`, `swarm`, `review`, `solve` |
| Phase 7 — Background Daemon | 🔜 | `daemon`, background watchers |
| Phase 8 — IDE Control | 🔜 | `ide`, `ide current` |

---

## Running Tests

```powershell
# All tests
python -m pytest tests/ -v

# Phase-specific
python -m pytest tests/test_phase1.py -v
python -m pytest tests/test_phase2.py -v
```

Current test count: **102 tests, 0 failures.**

---

## Project Structure

```
Project_Nexus/
├── document/               ← specs, ADRs, architecture, this file
├── src/
│   └── nexus/
│       ├── agents/         ← one adapter file per agent
│       │   ├── base.py     ← Agent base class + PATH resolver
│       │   ├── codex.py
│       │   ├── antigravity.py
│       │   ├── kiro.py
│       │   └── cursor.py
│       ├── cli/
│       │   └── main.py     ← all CLI commands + interactive shell
│       ├── core/
│       │   └── scaffold.py ← nexus init logic
│       └── models/         ← Pydantic schemas (Task, AgentResult, etc.)
├── tests/
│   ├── test_phase1.py
│   └── test_phase2.py
└── pyproject.toml
```

---

*Last updated: Phase 2 complete.*
