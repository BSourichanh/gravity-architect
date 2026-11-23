# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Product Repository Guard (`plugin/scripts/init_workspace.py`):** refuses (exit code `1`, explicit `stderr` message or structured `--json` payload) to initialize a new workshop inside a directory containing `.git` and a code/plugin manifest (`plugin/plugin.json`, `plugin.json`, `pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, `pom.xml`, `setup.py`) without an existing `projects.json`, unless `--force` is passed (preserving idempotence when `projects.json` exists and empty/git-only workshop initialization).
- **CLI Ergonomics (`plugin/scripts/sync_tracking.py`):**
  - Added `default_architect_home()` fallback in `resolve_workspace_root(..., home_dir=...)` after `--config` > `--workspace` > `$GRAVITY_ARCHITECT_WORKSPACE` > `cwd` > unique subfolder detection.
  - Added `--max-stdout-bytes` (default `8192`, `0` = unlimited) with `format_delta_for_stdout()` emitting a bounded summary (exact status, `Cibles éditoriales LLM`, synthetic stats, `tracking/snapshots/delta.md` path) when `--print-delta` exceeds the threshold, and `--max-changelog-lines` (default `45`) forwarded to `extract_latest_changelog_section()`.
- **Validator D4 & Markdown Hygiene (`plugin/scripts/validate.py`):** lowered `plugin/rules/AGENTS.md` blocking ceiling to `> 1 000 B` with a `[WARN]` between `601` and `1 000 B` (blocking under `--strict`), and enforced UTF-8 no-BOM, LF, and budget limits on `rules/AGENTS.md`, `skills/gravity-architect/SKILL.md` (`<= 6 000 B`), `templates/AGENTS.md` (`<= 2 500 B`), and root `AGENTS.md` (`<= 2 500 B` when `root.name == "plugin"`).
- **Unit Tests:** added `unittest` coverage in `tests/test_init_and_install.py` and `tests/test_sync_tracking.py` for the product-repo guard, `_deploy_file()` literal return status, template principles, `resolve_workspace_root()` fallback isolation, `--max-stdout-bytes` / `--max-changelog-lines`, and validator D4 rules (including `601..1 000 B` `--strict` warning and `SKILL.md > 6 000 B` / BOM / CRLF rejection).

### Changed
- **Simplified `_deploy_file()` (`plugin/scripts/init_workspace.py`):** returns `"created" | "updated" | "skipped"` instead of mutating 3 list arguments.
- **Template, Rules & Skill Compaction:** added `KISS, YAGNI, DRY, SOLID, CUPID` to invariant 1 of `plugin/templates/AGENTS.md` (`<= 2 500 B`), compacted `plugin/rules/AGENTS.md` (`<= 520 B`, LF, no BOM, no frontmatter), compacted `plugin/skills/gravity-architect/SKILL.md` (`<= 5 800 B`, LF, no BOM), and compacted root `AGENTS.md` (`<= 1 650 B`, LF, 3 canonical sections preserved).

## [0.4.0] - 2026-11-22

### Added
- **Isolated Code & Architecture Audits (`audits/code/` & `/gravity-architect audit [projet|all]`):**
  - Added `plugin/templates/audit-code-readme.md` (index & audit journal strictly isolated from `audits/agents/`) and `plugin/templates/audit-code-template.md` (`CODE-XX-N` `P0`/`P1`/`P2`, KISS/YAGNI/DRY/SOLID/CUPID, invariants/`module.json`/Hot-Cold, security/hygiene/tests).
  - Updated `plugin/scripts/init_workspace.py` to idempotently deploy `audits/code/README.md`, `audits/code/_TEMPLATE.md`, and `audits/agents/.gitkeep` (preserving existing files unless `--force`).
  - Added `"audit-code-readme.md"` and `"audit-code-template.md"` to `REQUIRED_TEMPLATES` in `plugin/scripts/validate.py`.
  - Documented `/gravity-architect audit [projet|all]` in `plugin/skills/gravity-architect/SKILL.md`, `plugin/rules/AGENTS.md` (< 2 048 B, no YAML frontmatter), `README.md`, and `plugin/README.md`.
- **Unit Tests:** added isolated `unittest` coverage in `tests/test_init_and_install.py` and `tests/test_sync_tracking.py` for `audits/code/` idempotent deployment, compact archived handoffs (`ECOSYSTEM.md` & project cards), and SemVer CLI comparison (`compute_delta_with_state` & `apply_auto_doc_updates`).

### Fixed
- **AUD-01-04 (Hot Budget `ECOSYSTEM.md <= 6 000 B`):** compacted `_build_ecosystem_blocks()` in `plugin/scripts/sync_tracking.py` to render `archived_handoffs` as a single summary line, and capped `_format_project_handoffs_block()` on project cards to the 3 most recent entries plus `(+N plus anciens dans \`handoffs/archive/\`)`.
- **AUD-01-05 (SemVer CLI Comparison):** added `_parse_semver_tuple()` and `_compare_cli_versions()` in `plugin/scripts/sync_tracking.py` so `local >= latest` (e.g. `1.5.14` vs `v1.5.12`) never triggers false-positive `en retrait` alerts in `compute_delta_with_state()`, and `apply_auto_doc_updates()` distinguishes `*(en avance)*`, `*(écart)*`, and equal versions (with string fallback for non-SemVer values).

## [0.3.0] - 2026-11-22

### Added
- **Zero-Token Repository Discovery (`init_workspace.py --discover`):**
  - Read-only depth-1 scan of `--scan-dir` (default `--workspace`, excluding hidden `.xxx` directories and the workshop itself, never scanning `../` implicitly) with `--json` output (`workspace`, `scan_dir`, `initialized`, `candidates`).
  - Reuses `sync_tracking.py` (`detect_plugin_manifest`, `derive_validator_script`, `detect_version_source`, `run_readonly_cmd`) to extract `id`, `name`, portable POSIX `path`, `preset`, `plugin_manifest`, `validator_script`, `main_branch` (`main` > `master` > current), `default_dev_branch` (`dev` if present else `main_branch`), `role`, `has_changelog`, and `has_agents`.
- **Incremental Project Addition (`init_workspace.py --add <target>`):**
  - Repeatable `--add` accepting `<path>` or `id=<path>`, requiring an existing `projects.json`, failing closed before any write on duplicate `id` or resolved path, and generating `tracking/projects/<id>.md` when missing.
- **Built-In Presets, Impact Template & Guided Onboarding:**
  - Added `plugin/templates/impact-template.md` and enforced it in `plugin/scripts/validate.py` (`REQUIRED_TEMPLATES`).
  - Enriched `init_workspace.py` with path-only `--project <path>`, per-project auto-detected presets (and smart `default_preset` fallback), `--watch antigravity` (official 5 Antigravity surfaces, `tracking/antigravity/IMPACT.md` + `hot_budgets` entry), `--watch-url id=url`, `--public-mode`, and opt-in `--run-sync` / `--offline`.
  - Updated `plugin/skills/gravity-architect/SKILL.md` and `plugin/rules/AGENTS.md` for hybrid guided `/gravity-architect init` (`ask_question`) and `/gravity-architect add`.

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
