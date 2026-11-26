# Advanced Workflows & Operational Hygiene

On-demand reference loaded from [`SKILL.md`](../SKILL.md) *(progressive disclosure: 0 tokens at initial load)*.

## 1. Post-Task Status, Waves & `wave_plan_v1` / Native Execution Contract

### Mandatory Status After Drafting a Task
- After creating `tasks/<YYYY-MM-DD>-<repo>-<slug>.md` (wave, dependencies, `Workflow profile` `quick` or `standard`, hybrid `::` / `~L` anchors, cap `<= 5` code files excluding tests/docs, `Spec ID`, `Spec source`, `Acceptance Criteria Covered`, and `CHANGELOG.md` listed in scope/`target_files` as a non-code worktree deliverable) and verifying with `python "<PLUGIN_DIR>/core/waves.py" --check-waves --workspace .`, explicitly display the status **`drafted, not deployed`**.
- Remind the user that the wave can be compiled into `wave_plan_v1` (`--export-wave <N>`) and executed by default via native `/swarm` in isolated `git worktree`s (or `run_workflow` on explicit opt-in), without ever starting code execution before human approval.

### Production Launch & `git worktree` Isolation
- **Neutral compilation (`core/waves.py --export-wave <N>`):** compiles a validated wave (*fail-closed*: rejects empty wave, DAG/anchor errors, invalid profile, missing `repo_root`, missing/unvalidated `Spec source`, or `draft`/`done`/`archived`/`cancelled` status) into a `wave_plan_v1` JSON manifest (`schema_version`, `workspace`, `wave`, optional `wave_name`, and `tasks` with `repo_id`, `repo_root`, `expected_branch`, `profile`, `plan_file`, `target_files`, `status`).
- **Default execution via native `/swarm`:** consumes `wave_plan_v1` inside isolated temporary `git worktree` checkouts (via `gravity-workflow` CLI helper if installed or native `git worktree add`; never edit `../<repo>` directly). Optimized topology: fast-model builders (`Hydrogen` / `3.8 Flash`) in detached worktrees, compact public briefs with a 1-line Caveman directive (`SessionStart` hooks are disabled by default), warm cache (`waiting`) for targeted remediation before post-apply `kill`, cold reviewer without `fork` (adaptive `quick` shared vs `standard`/`deep` cross-model critique with exact `tasks/*.md` paths and `grep -rn` on Linux/POSIX), and zero `@monitor` by default.
- **Explicit opt-in workflow engine (`run_workflow`, if `gravity-workflow` is installed):** only on explicit user request, consumes `wave_plan_v1` in parallel isolated `git worktree`s (*fail-isolated* per repo), routing `quick` for docs, templates, UI, or simple CLIs and `standard` for security, hooks, AST, installer, or `core/` modules. Validate any `run_workflow` script containing top-level `await` with an AST harness (`ast.PyCF_ALLOW_TOP_LEVEL_AWAIT`).
- **`update_steps` labels:** name each step by its concrete business objective in 3-6 words (e.g., *"Deliver Live backend & CLI"*), never generic numbered titles (*"Wave 1"*, *"Execute Wave N"*).

## 2. Token Hygiene, Plan Mode & Delegation

### `sync` No-Op in Plan Mode
- When `/gravity-architect` or `/gravity-architect sync` runs in Plan Mode:
  - Run `sync_tracking.py --check --print-delta`.
  - If the delta returns `NO_EDITORIAL_CHANGES` with `0` auto-updated files (`<!-- AUTO:START/END -->`) **and** the workshop is already registered, reply directly in 5-8 lines **without calling `exit_plan_mode`**.

### `exit_plan_mode(plan=...)` Content
- Never copy a full spec, task, or audit report into `exit_plan_mode(plan=...)`.
- Keep `plan` as a concise structural summary (scope, target files, expected checks); full details live in `specs/`, `tasks/`, or `audits/code/`.

### Multi-File Exploration & `/compact` Rule (`> 250k`)
- Never load a cluster of source files from tracked repositories into the root session; after reading the micro-delta, delegate any multi-file read-only exploration to a dedicated `research` subagent with bounded scope.
- After generating a batch of `tasks`, suggest `/compact` or a fresh session to the user, and compact the root session whenever context exceeds **`> 250k` tokens** to preserve context budget.

## 3. `--ack-editorial` Guard & Ordered Git / Install Closure

### `--ack-editorial` Guard Against Dirty WIP
- Never run `sync_tracking.py --ack-editorial` while tracked repositories still have uncommitted WIP (`git status` dirty or unvalidated changes in progress).
- Run `--offline --ack-editorial --print-delta` only after editorial updates are applied and tracked repository state is clean.

### Ordered Cycle Closure & Final `gravity-metrics`
Follow these 4 steps strictly in order at the end of a cycle:
1. **Reviews & verification (*fail-closed* global):** confirm the plan/spec is validated, the wave is complete, the review is clean, and **100%** of mandatory `verify_commands` pass (e.g., `audit_ecosystem.py --verify-parallel --strict` across the ecosystem). If any verification fails or regresses, or if a repo is on the wrong branch or reports a blocker, **stop before any `commit`/`push`** across the batch and request human arbitration.
2. **Auto-closure on `dev` & coordinated ecosystem install:** run `git add`/`commit` on `dev` + `git push origin dev` *(never `--force`)* + coordinated reinstall via `ecosystem_install.py --update --modules <...> --strict` (`python3` on Linux/macOS, `python` on Windows, rather than isolated `install.py --strict` so installed modules stay aligned). Maintain strict read-only posture in Phase 4: **zero direct edits to `CHANGELOG.md` or code from the workshop root** — `[Unreleased]` entries must come from builders inside worktrees via `target_files`. `merge dev -> main`, SemVer tags, and releases require **explicit human approval** *(a plain `/gravity-architect sync`, even with `--commit`, never commits in tracked repos nor runs `git push`)*.
3. **Workshop archiving & `--ack-editorial`:** once tracked repos are clean and pushed to `dev`, move `specs/` -> `specs/archive/` and `tasks/` -> `tasks/archive/` (`done`), update active tracks, and run `sync_tracking.py --offline --ack-editorial --print-delta`.
4. **Optional `gravity-metrics` closure as the very last step *(root workshop session only)*:** if `~/.gemini/config/plugins/gravity-metrics/scripts/cli.py` exists *(or `%USERPROFILE%\.gemini\config\plugins\gravity-metrics\scripts\cli.py` on Windows; silent no-op — zero errors or messages — if absent)*, seal the current root session capture:
   - `python3 ~/.gemini/config/plugins/gravity-metrics/scripts/cli.py archive <conversation_id> -l "<slug>" --workspace .` *(on Windows: `python` on `%USERPROFILE%\...`)*
   - If a release (`merge dev -> main`, SemVer tag, or `main`/tag push) occurs a turn later in the **same** already-sealed conversation, re-run with `--update-sealed`.
   - Never pass `--force`.

## 4. `/gravity-architect add` Without Arguments (`../`)

- If `/gravity-architect add` is invoked without a target path:
  1. Inspect `projects.json` in the current workshop.
  2. If tracked repositories already use relative paths under `../` (`../<repo>`), propose `../` as the **first recommended option** via `ask_question` before scanning another directory.
  3. After user confirmation, run `python "<PLUGIN_DIR>/scripts/init_workspace.py" --workspace . --discover --scan-dir ../ --json` and add selected candidates with `--add`.

## 5. Empty Workspace Onboarding (Greenfield)

- **Pre-check (`./projects.json` absent):** before `sync`, `status`, `spec`, `task`, or `add`, verify `./projects.json` exists in the current directory (or a unique workshop subfolder under `.`). Never call `sync_tracking.py` blindly or confuse an empty folder with `<architect_home>/projects.json`: route directly to guided `init`.
- **Discovery & 1-step `ask_question`:** run `init_workspace.py --workspace . --discover --json` (CWD only). If `candidates: []`, ask **1 single `ask_question`** offering:
  1. *(a)* Initialize an empty workshop (`0` repos),
  2. *(b)* Scan parent directory `../` (`--scan-dir ../`),
  3. *(c)* Provide explicit repository paths.
- **Options & naming:** `--name` is optional (otherwise derived from the directory name outside generic names, falling back to `Mon Atelier Projets`), `public_mode=false` by default; `public_mode` and `--watch-url` remain advanced options.
- **Fast 0-repo init:** run 1 command `python "<PLUGIN_DIR>/scripts/init_workspace.py" --workspace . --run-sync --offline` (0 `--ack-editorial` pass needed).
- **Suggested next commands:** `/gravity-architect add <path>` (track an existing repo) and `/gravity-architect spec <slug>` (start a specification).

## 6. 4-Phase Cycle, Hybrid Checkpoint & Native Execution

### Bare `/gravity-architect` vs `"<instruction>"`
- **Bare `/gravity-architect`:** intercepted by the `PreInvocation` hook (`hooks/pre_invocation_architect.py` -> `scripts/atelier_status.py`) in strict read-only mode (`0` disk writes, `0` `ateliers.json` writes, `0` `gravity-metrics` capture). Displays active specs, tasks by wave/status, hygiene alerts (`AUD-05-09`), and suggested next actions.
- **`/gravity-architect "<instruction>"`:** orchestrates a structured **4-phase** cycle:
  1. **Conception:** RO `research` delegation -> `/grill-me` challenge -> `/plan` framing and `specs/<YYYY-MM-DD>-<slug>.md`.
  2. **Planning:** exact symbol and line-range anchors from `research` (`::` / `~L`) -> split `tasks/<YYYY-MM-DD>-<repo>-<slug>.md` (`<= 5` code files, `quick` or `standard` profile) -> check `core/waves.py --check-waves` -> **1 single checkpoint** presented via artifact (`RequestFeedback=True`) **and/or explicit `ask_question`** *(the `Proceed` button is absent on some Antigravity surfaces)*.
  3. **Production:** compile via `core/waves.py --export-wave <N>` (`wave_plan_v1`), then execute by default via native `/swarm` in isolated `git worktree`s (fast builders in `waiting` warm cache + post-apply `kill`, cold reviewer without `fork`, adaptive `quick`/`standard`, zero `@monitor` by default, 1-line Caveman directive per brief, exact `tasks/*.md` paths for reviewer, `grep -rn` on Linux/POSIX; `run_workflow` opt-in only), including `[Unreleased]` in `CHANGELOG.md` inside each worktree, compact `<= 10`-line per-repo summary, mini-checkpoint on `dev` between waves, business-goal `update_steps` titles in 3-6 words (never *"Wave N"*), and root `/compact` above `> 250k` tokens.
  4. **Validation:** strict RO from root (**0 direct edits to `CHANGELOG.md` or code**), run `verify_commands` (`100%` passing, fail-closed, e.g., `audit_ecosystem.py --verify-parallel --strict`) -> `git add`/`commit`/`push origin dev` *(never `--force`)* -> archive (`specs/archive/`, `tasks/archive/`, `--offline --ack-editorial`) -> update ecosystem docs -> reinstall only at end of Validation (`ecosystem_install.py --update --modules <...> --strict`) -> final summary -> optional `gravity-metrics` closure (§3).
