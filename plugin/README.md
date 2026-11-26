# Gravity Architect Plugin

> ### 2-Minute Quickstart & Ecosystem Role
> - **Tier:** **Tier 3 — Multi-Project** *(prerequisite: [`gravity`](https://github.com/BSourichanh/gravity) Core)*
> - **Role:** Orchestrate a Hot/Cold design workshop (`specs/`, `tasks/`, `audits/code/`) and track multiple repositories in strict read-only mode.
> - **Start:** `/gravity-architect init` then `/gravity-architect sync` (or bare `/gravity-architect` for 0-token status)
> - **Docs Hub (`gravity/docs/`):** [Getting Started](https://github.com/BSourichanh/gravity/blob/main/docs/getting-started.md) · [User Journey](https://github.com/BSourichanh/gravity/blob/main/docs/user-journey.md) · [Command Cheatsheet](https://github.com/BSourichanh/gravity/blob/main/docs/command-cheatsheet.md) · [Troubleshooting & Lifecycle](https://github.com/BSourichanh/gravity/blob/main/docs/troubleshooting-and-lifecycle.md)

Generic Antigravity plugin (**100% Python 3.10+ standard library**) built around a shared `_shared/` foundation, cohesive SRP `core/` modules, slim CLI entrypoints (`scripts/`), and a 0-token `PreInvocation` hook (`hooks/pre_invocation_architect.py`) to run multi-project design workshops, author specs (`specs/`), split wave-validated tasks (`tasks/`), maintain **Hot / Cold** token budgets, and track repositories in strict read-only mode.

## `/gravity-architect` Commands

- `/gravity-architect` *(bare, 0-token `PreInvocation`)*: runs `hooks/pre_invocation_architect.py` -> `scripts/atelier_status.py` in strict read-only mode to display active specs, wave tasks by status, `AUD-05-09` / hygiene alerts, and suggested actions.
- `/gravity-architect init [--workspace <dir>] [--name "<Title>"] [--preset generic|antigravity-plugin]`: initializes an isolated design workshop (`AGENTS.md`, `ECOSYSTEM.md`, `projects.json`, `specs/`, `tasks/`, `audits/code/`, `audits/agents/`, `tracking/`) via guided discovery (`init_workspace.py --discover --json`, `ask_question`, `--watch antigravity` / `--watch-url` / `--public-mode` / `--run-sync`) and initial sync.
- `/gravity-architect add <path...>`: incrementally and fail-closed adds one or more repositories (`<path>` or `id=path`) via `init_workspace.py --add`, creates `tracking/projects/<id>.md`, and runs editorial sync.
- `/gravity-architect [sync] [--offline] [--check] [--full] [--ack-editorial] [--commit]`: read-only synchronization across `projects.json` repositories, updating `<!-- AUTO:START/END -->` blocks at zero LLM tokens and emitting a compact micro-delta.
- `/gravity-architect status`: summarizes current status from `tracking/snapshots/delta.md` (or `ECOSYSTEM.md`) without re-running collection.
- `/gravity-architect spec <slug>` · `/gravity-architect task <repo> <slug>` · `/gravity-architect archive <slug>`: frames specs, splits wave tasks (`<= 5` code files, `Spec ID`/`Spec source`/`Acceptance Criteria Covered`, `::`/`~L` anchors, `core/waves.py --check-waves`), compiles `wave_plan_v1` (`--export-wave <N>`) for native `/swarm` execution (`run_workflow` opt-in only), and archives completed work (`specs/archive/`, `tasks/archive/`).
- `/gravity-architect audit [repo|all]`: runs a strict read-only **Code & Architecture** audit on tracked repositories, writes `audits/code/<YYYY-MM-DD>-audit-code-<target>.md` from `audits/code/_TEMPLATE.md` (`CODE-XX-N` `P0`/`P1`/`P2`), and updates `audits/code/README.md` (strictly isolated from `audits/agents/`).

See [`skills/gravity-architect/SKILL.md`](skills/gravity-architect/SKILL.md) and [`skills/gravity-architect/references/workflows-and-hygiene.md`](skills/gravity-architect/references/workflows-and-hygiene.md) for full lifecycle rules.

### Initialization CLI Options (`scripts/init_workspace.py`)
- `--discover [--scan-dir <dir>] [--json]`: depth-1 read-only scan of candidate Git repositories (never leaves CWD implicitly) extracting `id`, `name`, `path`, `preset`, `plugin_manifest`, `validator_script`, `main_branch`, `default_dev_branch`, `role`, `has_changelog`, and `has_agents`.
- `--project <path|id=path>`: auto-detects preset and metadata from a path or `id=path`.
- `--add <path|id=path>` *(repeatable)*: fail-closed incremental addition to an existing `projects.json`.
- `--watch antigravity` / `--watch-url id=url` / `--public-mode` / `--run-sync [--offline]`: watch presets, privacy mode, and opt-in initial sync.
- **Product repository guard (`--force` / `--json`):** refuses initializing a new workshop inside a `.git` repository containing a code/plugin manifest unless `--force` is passed.

### Synchronization, Waves & Validation CLIs
- **`scripts/sync_tracking.py`:** falls back to `default_architect_home()` (`$GRAVITY_ARCHITECT_HOME` > `$GRAVITY_HOME/architect` > `~/.gemini/gravity/architect`) after `--config` > `--workspace` > `$GRAVITY_ARCHITECT_WORKSPACE` > `cwd` > unique subfolder; supports `--max-stdout-bytes <N>` (default `8192`) and `--max-changelog-lines <N>` (default `45`).
- **`core/waves.py`:** `--check-waves --workspace <dir> [--json]` enforces fail-closed DAG, file-disjointness, `<= 5` code files, hybrid `::`/`~L` anchors, and `Spec ID`/`Spec source` (`validated`)/`Acceptance Criteria Covered`; `--export-wave <N>` emits `wave_plan_v1`.
- **`scripts/validate.py`:** slim (< 300 L) strict validator powered by `_shared.validator_core` (`--strict`, `--fix-python-cmd`, `--json`, `--plugin-root`).

## Multi-Repo Tracking, Module Contract & Privacy Mode

- **Gravity module contract:** [`config/module.json`](config/module.json) (`schema_version: 1`, `id: "architect"`, storage `$GRAVITY_ARCHITECT_HOME` > `$GRAVITY_HOME/architect` > `~/.gemini/gravity/architect`).
- **Auto-detected manifests & multi-format versions:** checks `plugin/plugin.json`, `{id}-plugin/plugin.json`, `plugin.json`; reads versions from `plugin.json`, `package.json`, `pyproject.toml`, `Cargo.toml`, `setup.cfg`, `VERSION`/`.txt`, or `version_json_path`.
- **Branch-aware Git & changelogs:** tracks `main` vs `dev`, latest tag on `main`, untagged non-merge commits, `[Unreleased]` vs latest release, and ignores non-runtime WIP.
- **Privacy mode (`privacy.public_mode`):** opt-in (`false` default) in `projects.json`; when `true`, `ECOSYSTEM.md` lists only tracked plugin installs, suppresses `orphan_plugin_dirs` for third-party folders, and masks local machine paths in generated Markdown.

Minimal plugin & privacy configuration in `projects.json`:

```json
{
  "schema_version": 5,
  "default_preset": "antigravity-plugin",
  "privacy": { "public_mode": false },
  "projects": [
    {
      "id": "my-plugin",
      "path": "../my-plugin",
      "plugin_manifest": "plugin/plugin.json",
      "validator_script": "plugin/scripts/validate.py"
    }
  ]
}
```
