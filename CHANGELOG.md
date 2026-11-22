# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-11-22

### Added
- **Gravity Module Contract (`plugin/config/module.json` — schema v1):**
  - Declared `id: "architect"`, `plugin_name: "gravity-architect"`, centralized storage metadata (`subdir: "architect"`, `env_override: "GRAVITY_ARCHITECT_HOME"`), `/gravity-architect` command, capabilities, and signals.
  - Added strict validation of `config/module.json` v1 in `plugin/scripts/validate.py`.
- **Centralized Storage Helper (`default_architect_home()`):**
  - Resolves `$GRAVITY_ARCHITECT_HOME` > `$GRAVITY_HOME/architect` > `~/.gemini/gravity/architect` in `plugin/scripts/sync_tracking.py` while keeping `--workspace` > `$GRAVITY_ARCHITECT_WORKSPACE` > `.` workshop discovery unchanged.
- **Opt-In Public / Privacy Mode (`privacy.public_mode` / `public_mode` in `projects.json`):**
  - Defaults to `false` for full backwards compatibility.
  - When enabled (`true`), `ECOSYSTEM.md` (`ecosystem-meta`) lists only installed plugins matching tracked projects, `ecosystem-hygiene` suppresses `orphan_plugin_dirs` alerts for third-party directories, and machine absolute paths (`home`, `agy_path`, `plugins_dir`, `install_path`, absolute repo paths) are masked/omitted across `ECOSYSTEM.md`, `tracking/projects/*.md`, `ecosystem_snapshot.md`, and `delta.md`.

### Changed
- **Standardized Plugin Directory (`gravity-architect-plugin/` → `plugin/`):**
  - Moved plugin source to `plugin/`, updated `plugin/plugin.json` (`version: "0.2.0"`, strictly 9 official Antigravity fields, UTF-8 without BOM), `install.py` (`PLUGIN_SOURCE = REPO_ROOT / "plugin"`), `plugin/skills/gravity-architect/SKILL.md`, `AGENTS.md`, `README.md`, and `plugin/README.md`.
- **Plugin Manifest Auto-Detection (`sync_tracking.py` & `init_workspace.py`):**
  - Auto-detects `plugin/plugin.json` first, then `{project_id}-plugin/plugin.json`, then root `plugin.json`, and derives `validator_script` cleanly from the manifest directory.
  - Updated `plugin/templates/projects.json` with `"privacy": {"public_mode": false}` and `init_workspace.py` preset defaults to `plugin/plugin.json`.

## [0.1.0] - 2026-11-22

### Added
- **Standalone Generic Antigravity Plugin (`gravity-architect-plugin/` — 100% Python 3 stdlib):**
  - Manifest `plugin.json` (9 official Antigravity fields, UTF-8 without BOM), 1:1 SVG logo, lightweight `rules/AGENTS.md`, and `/gravity-architect` skill (`init`, `sync`, `status`, `spec`, `handoff`, `archive`).
  - Generic template pack (`templates/`) for initializing isolated Hot/Cold design workshops (`AGENTS.md` ≤ 2,500 B, `ECOSYSTEM.md` ≤ 6,000 B, `projects.json` `schema_version: 5`, spec/handoff/project-card templates, and cold `archives/`).
- **Read-Only Multi-Project Sync Engine (`scripts/sync_tracking.py` — schema v5):**
  - Automatic workshop discovery (`--config`, `--workspace`, `GRAVITY_ARCHITECT_WORKSPACE`, `.` or unique subfolder containing `projects.json` + `ECOSYSTEM.md`).
  - Multi-format version parsing (`plugin.json`, `package.json`, `pyproject.toml`, `Cargo.toml`, `setup.cfg`, `VERSION`, or custom `version_json_path`) across disk and Git `main`/`dev` revisions.
  - Branch & tag integrity checks (`main` vs `dev`, `latest_tag_on_main`, `--no-merges` post-tag commits, `[Unreleased]` vs latest release in `CHANGELOG.md`).
  - Declarative `compliance` rules (`generic` default) plus opt-in `antigravity-plugin` preset (9-field manifest check, `config.json` `enabled` inspection, OS-normalized content hash audit via `compare_plugin_dirs()`).
  - Opt-in technology `watches` (`markdown-changelog` and `antigravity-changelog`), persistent `editorial_state.json` with prose auto-ack / `--ack-editorial`, and zero-churn writes on unchanged syncs.
- **Bootstrapper, Strict Validator & Cross-Platform Installer:**
  - `scripts/init_workspace.py` (idempotent deployment with `--preset` and `--project`), `scripts/validate.py --strict` (AST stdlib check, leak prevention, E2E dry-run), `install.py` (staged copy with rollback, `--check`, `--uninstall`), and `tests/` (`unittest`).
