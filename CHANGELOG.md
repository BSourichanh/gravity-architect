# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
