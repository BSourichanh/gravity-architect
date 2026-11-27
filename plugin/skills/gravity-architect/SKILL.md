---
name: gravity-architect
description: "Orchestrate Hot/Cold design workshops, specs, wave tasks, and read-only repo tracking via /gravity-architect [init|add|sync|status|spec|task|archive|audit]."
---

# Gravity Architect — Design Workshop & Read-Only Repo Tracking

## Strict Rules
1. **Engine resolution:** scripts live in `~/.gemini/config/plugins/gravity-architect/scripts/` (or `./plugin/scripts/`).
2. **Strict read-only outside the workshop:** never create, edit, delete, or run mutating Git commands inside tracked repositories (`projects.json`) from the workshop root; code edits occur only inside isolated `git worktree` checkouts during Production.
3. **Token economy:** run `sync_tracking.py --print-delta` and read the micro-delta before inspecting tracked repos. Delegate multi-file RO exploration to `research`, and run `/compact` when root context exceeds `> 250k` tokens.

## Routing

### 0. Bare `/gravity-architect` vs `/gravity-architect "<instruction>"`
- **Bare `/gravity-architect` (0-token `PreInvocation`):** intercepted by `hooks/pre_invocation_architect.py` -> `scripts/atelier_status.py` (strict RO, 0 disk writes). Displays active specs, wave tasks, hygiene alerts, and suggested actions.
- **`/gravity-architect "<instruction>"` (4-phase cycle — [`references/workflows-and-hygiene.md`](references/workflows-and-hygiene.md)):**
  1. **Conception:** RO `research` -> `/grill-me` -> `/plan` -> `specs/<YYYY-MM-DD>-<slug>.md` (`Statut: validated`).
  2. **Planning:** exact `::` / `~L` anchors from `research` -> `tasks/<YYYY-MM-DD>-<repo>-<slug>.md` (`<= 5` code files excluding tests/docs, `quick`/`standard` profile, `Spec ID`/`Spec source`/`Acceptance Criteria Covered`) -> `core/waves.py --check-waves --workspace .` -> **1** hybrid checkpoint (`RequestFeedback=True` and/or `ask_question`), print **`drafted, not deployed`**.
  3. **Production:** compile `core/waves.py --export-wave <N>` (`wave_plan_v1`), execute via native `/swarm` in isolated `git worktree`s (`run_workflow` opt-in only), include `[Unreleased]` in `CHANGELOG.md` per worktree, `/compact` at `> 250k` tokens.
  4. **Validation:** strict RO from root (0 direct code/`CHANGELOG.md` edits), run `verify_commands` (100% pass, fail-closed), close on `dev` (`git add`/`commit` + `git push origin dev`, never `--force`) + `ecosystem_install.py --update --modules <...> --strict` (`merge dev -> main`, tags, and releases require explicit human approval), archive to `specs/archive/` and `tasks/archive/`, and run `--offline --ack-editorial --print-delta` *(triggers silent best-effort `gravity-metrics` closure when tracked repos have 0 dirty WIP, backed by `Stop` hook safety net per [`references/workflows-and-hygiene.md`](references/workflows-and-hygiene.md) §3)*.

### 1. `/gravity-architect init` *(guided hybrid onboarding)*
1. **Initialized (`./projects.json` present):** run `python "<PLUGIN_DIR>/scripts/init_workspace.py" --workspace .` *(idempotent without `--force`)* and suggest `/gravity-architect add <path...>`.
2. **Empty workspace (`./projects.json` absent):** 0-token CWD scan via `init_workspace.py --workspace . --discover --json`. If `candidates` is empty, never scan `../` implicitly — ask via 1 `ask_question`: empty workshop (`0` repos via `--run-sync --offline`), scan `../` (`--discover --scan-dir ../ --json`), or direct paths.
3. **Guided selection & sync:** pick repos, watches (`antigravity` / `--watch-url`), `public_mode` (`false` default), run `init_workspace.py --workspace .`, then *(unless `--no-sync` or `--run-sync`)* `sync_tracking.py --workspace . --print-delta` -> update `tracking/projects/*.md` -> `sync_tracking.py --workspace . --offline --ack-editorial --print-delta`.

### 2. `/gravity-architect add <path...>`
1. Without arguments, if tracked repos use `../`, recommend `../` first via `ask_question`.
2. Run `python "<PLUGIN_DIR>/scripts/init_workspace.py" --workspace . --add "<PATH>"` *(repeatable, `<path>` or `id=path`, fail-closed)*, then sync and `--offline --ack-editorial --print-delta` *(unless `--no-sync`)*.

### 3. `/gravity-architect status` & `/gravity-architect sync`
- **`status`:** read only `tracking/snapshots/delta.md` (or `ECOSYSTEM.md`); summarize in 5-8 lines.
- **`sync` (default):** verify `./projects.json` exists, run `python "<PLUGIN_DIR>/scripts/sync_tracking.py" --print-delta` (`--check` in Plan Mode).
  - **`NO_EDITORIAL_CHANGES` (without `--full`):** read nothing else (in Plan Mode, reply directly without calling `exit_plan_mode`).
  - **`EDITORIAL_UPDATE_REQUIRED` (or `--full`):** edit only `Cibles éditoriales LLM` (keep `<!-- AUTO:START/END -->` and Hot budgets), then run `sync_tracking.py --offline --ack-editorial --print-delta` (never `--ack-editorial` with dirty WIP in tracked repos).
  - **Git posture:** never auto-commit/push on `sync` (`--commit` touches workshop files only, never `git push`).

### 4. `/gravity-architect spec <slug>` · `task <repo> <slug>` · `archive <slug>` · `audit [repo|all]`
- **`spec <slug>`:** challenge need, check existing tools first, create `specs/<YYYY-MM-DD>-<slug>.md` from `specs/_TEMPLATE.md`.
- **`task <repo> <slug>`:** create `tasks/<YYYY-MM-DD>-<repo>-<slug>.md` from `tasks/_TEMPLATE.md` (`<= 5` code files, `Spec ID`/`Spec source`/`Acceptance Criteria Covered`, `::`/`~L` anchors), run `core/waves.py --check-waves --workspace .`, report `drafted, not deployed`.
- **`archive <slug>`:** move delivered spec/tasks to `specs/archive/` and `tasks/archive/` (`done`), update active tracks, `--offline --ack-editorial --print-delta`.
- **`audit [repo|all]`:** strict read-only Code & Architecture audit -> write `audits/code/<YYYY-MM-DD>-audit-code-<target>.md` (`CODE-XX-N` `P0`/`P1`/`P2`) and update `audits/code/README.md` *(isolated from `audits/agents/`)*.
