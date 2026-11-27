# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **[TASK-ARCH-03b] `SPI-1` Dashboard Provider & `SPI-1`/`SPI-2` `module.json` Contract (`SPEC-ARCH-01`):**
  - Added read-only `plugin/scripts/dashboard_provider.py` (`< 550` L, mode `0755`, 100 % Python 3.10+ stdlib) implementing the `SPI-1` CLI (`--view architect --since-signature --atelier --ws --json`, stdin `params`/`context`, fail-closed `--action` `rc=1`), 8-level atelier discovery precedence (`arg_workspace` -> `selected_atelier` -> `env_workspace` -> `architect_home` -> `env_architect_home` -> `ws_hint` -> `architect_registry` -> `module_home`), bilingual FR/EN parsing across `ECOSYSTEM.md`, `delta.md`, `specs/`, `tasks/` (with RO fallback to `handoffs/` only when `tasks/` is absent), and `audits/code/` (strictly excluding `audits/agents/` and symlinks/NTFS junctions via `_shared.path_safety`), and `MAX_PAYLOAD_BYTES = 450_000` budget truncation.
  - Declared `dashboard` (`SPI-1`: `scripts/dashboard_provider.py`, `views: ["architect"]`, `actions: []`) and `capture_policy` (`SPI-2`: `/gravity-architect`, consultative subcommand exclusions, `consultative_bypass: true`, `label_prefix: "architect"`) in `plugin/config/module.json`.
  - Added unit test suite `tests/test_dashboard_provider.py` covering CLI/stdin parity, `--since-signature` fast-path, full discovery precedence, bilingual FR/EN parsing, strict RO, `audits/agents/` and symlink/junction isolation, payload truncation, and `_shared.validator_core` contract/stdlib checks.
- **[TASK-ARCH-03a] Direct `CHANGELOG.md` links, `wave_name`/`spec_id` export, `tasks/` alignment & `_shared` atomic/lock I/O (`SPEC-ARCH-01`):**
  - Updated `plugin/core/waves.py` (`export_wave`) to emit `spec_id` on each task, aggregate distinct ordered `wave_name` values at the top level (`" | ".join(...)`), resolve self-workspace `atelier_id` / directory name, guard symlink/junction `--out` paths, and write `--out` atomically via `_shared.atomic_io.write_json_atomic`.
  - Ported `archive/pre-refonte-wip` (`ed9e78e`) direct `CHANGELOG.md` tracking to `plugin/core/git_collector.py` (`changelog_path`, optional `changelogs_dir`, zero `archives/changelogs/` copies) and `plugin/core/renderers.py` (`_render_active_artifacts_lines`, `format_project_tasks_block`, `_format_project_changelog_link`, `_shared.atomic_io.write_text_atomic` in `apply_auto_doc_updates`).
  - Reconciled `dev` and `wip` (`ed9e78e`) in `plugin/scripts/init_workspace.py` (`<= 450` L) and `plugin/scripts/sync_tracking.py` (`<= 250` L): `tasks/` deployment, `_derive_default_workspace_name`, `collect_atelier_hygiene_alerts`, `register_atelier` (`ateliers.json` MRU), and fail-closed `_shared.file_lock.exclusive_file_lock` + `_shared.atomic_io` with lock files isolated under `<architect_home>` (`ateliers.lock`, `locks/<sha256>.lock`).
  - Removed obsolete `plugin/templates/archives-readme.md` and `plugin/templates/handoff-template.md`; updated `plugin/templates/{AGENTS,ECOSYSTEM,project-card-template}.md` and unit suites (`tests/test_{core_structure,waves,sync_tracking,init_and_install}.py`) with zero legacy studio/bridge references.
- **[TASK-ARCH-02] `_shared` projection, slim `install.py`/`validate.py`, `PreInvocation` hook & EN docs (`SPEC-ARCH-01`):**
  - Projected `plugin/_shared/` and `plugin/.shared_manifest.json` from `gravity/shared/gravity_shared/` via `sync_shared.py --apply --repos gravity-architect`.
  - Replaced `install.py` (`562` L -> `78` L) with a thin launcher delegating to `_shared.installer_core` (`InstallSpec` + `run_installer`), keeping all 11 CLI flags, symlink/junction safety, `is_lock_oserror` in-place upgrade fallback, Windows `python3` rewrite, `agy --strict`, and atomic locked `sources.json` provenance.
  - Slimmed `plugin/scripts/validate.py` (`524` L -> `191` L, `< 300` L) onto `_shared.validator_core` with `ARCHITECT_ALLOWED_MODULES`, `REQUIRED_TEMPLATES` (`task-template.md`, excluding `archives-readme.md` and `handoff-template.md`), `hooks.json` unknown group key checks, `references/*.md` + `../README.md` link hygiene, `templates/projects.json` validation, and `_run_e2e_dry_run`.
  - Ported `plugin/hooks/pre_invocation_architect.py` (`~44` L, `0755`) onto `_shared.hook_runtime` and added `plugin/hooks.json` (`PreInvocation` active `"enabled": true`, `"python3"`).
  - Updated `plugin/plugin.json` (version `0.5.1`, 9 official fields, EN, zero `handoffs` drift), translated `SKILL.md` (`description <= 160` chars, `<= 6000` B), `README.md`, and `plugin/README.md` to 100% EN, and added `plugin/skills/gravity-architect/references/workflows-and-hygiene.md` (100% EN).
  - Updated `tests/test_init_and_install.py` for `_shared.{installer_core,validator_core}` & EN docs and enabled `test_pre_invocation_architect_hook_bare_vs_passthrough` in `tests/test_hooks_and_status.py`.
- **[TASK-ARCH-01] Anti-drift guardrails, DAG/Spec validation & `AUD-05-09` (`SPEC-GOV-02`):**
  - Ported and hardened `plugin/core/io_utils.py` (`<= 650` L) with bilingual FR/EN artifact headers, `TASK_ID_RE`, `SPEC_ID_RE`, `SPEC_SOURCE_RE`, `AC_LINE_RE`, `WAVE_NAME_RE`, `parse_artifact_file()` metadata extraction (`task_id`, `spec_id`, `spec_source`, `acceptance_criteria`, `wave_name`), and `tasks/` + temporary `handoffs/` collection in `collect_concept_artifacts()`.
  - Ported and hardened `plugin/core/waves.py` (`<= 650` L): fail-closed DAG, `<= 5` code files, hybrid `::`/`~L` anchors, `atelier_id` / `workspace_root.name` self-workspace recognition without modifying `projects.json["projects"]`, fail-closed `Spec ID` / `Spec source` (`status == "validated"` inside `specs/`) / `Acceptance Criteria Covered` enforcement, and optional `wave_name` emission in `wave_plan_v1`.
  - Ported `plugin/scripts/atelier_status.py` (`<= 650` L, strictly read-only, zero git subprocesses) with deterministic `AUD-05-09` stale/orphaned `ready` task detection (archived/superseded/missing spec, `task_id` in target `CHANGELOG.md`, `new file` anchors already present on disk).
  - Ported `_TEMPLATE_DRIFT_PAIRS`, `extract_markdown_targets()`, `_iter_atelier_hygiene_files()`, and `collect_atelier_hygiene_alerts()` into `plugin/core/delta.py` (`<= 650` L).
  - Aligned `plugin/templates/{spec,task,audit-code,project-card}-template.md` (LF, UTF-8 no-BOM) and added isolated unit suites `tests/test_waves.py` and `tests/test_hooks_and_status.py`.

## [0.5.1] - 2026-11-24

### Added
- **CLI Parity (`install.py`):** added `--strict` (overrides `--skip-validate`, runs read-only strict validation in `--check`, passes `--strict` to `agy plugin validate`) and `--no-fix-python` (documented ecosystem parity no-op) to reach `11/11` installer CLI flags.

### Changed
- **Docs & UX Alignment:** aligned `plugin/plugin.json` `suggestedPrompts` on `/cmd — résumé` (`<= 100` chars) and added the "Démarrage 2 min & Place dans l'écosystème" callout (**Palier 3 — Multi-projets**, `gravity` Core prerequisite, `/gravity-architect init` -> `/gravity-architect sync`, `gravity/docs/` hub links) to `README.md` and `plugin/README.md`.
- **Modular Core Split (`plugin/core/`):** extracted `plugin/scripts/sync_tracking.py` and `plugin/scripts/init_workspace.py` into 6 cohesive SRP modules under `plugin/core/` (`io_utils.py`, `discovery.py`, `git_collector.py`, `watches.py`, `delta.py`, `renderers.py`, each `<= 650 L`, 100 % Python 3.10+ stdlib, atomic UTF-8 no-BOM / LF writes).
- **Backward-Compatible Script Facades:** reduced `plugin/scripts/sync_tracking.py` (`<= 250 L`) and `plugin/scripts/init_workspace.py` (`<= 450 L`) to strict backward-compatible facades re-exporting all existing API symbols and CLI flags.
- **Validator & Tests:** updated `ALLOWED_LOCAL_MODULES` and required directories in `plugin/scripts/validate.py` for `core/` and its 6 submodules, and added `tests/test_core_structure.py` verifying line budgets, LF/no-BOM hygiene, facade re-exports, atomic writes, and recursive installation via `install.py`.

## [0.5.0] - 2026-11-23

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
