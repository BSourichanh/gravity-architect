# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Wave 2 (`atelier_status.py`, `PreInvocation` 0-token hook, `INT-07` & `INT-01/03/06`):**
  - Added `plugin/scripts/atelier_status.py` (100 % stdlib Python 3.10+, UTF-8 no-BOM, LF, zero disk writes, zero `gravity-metrics` capture) exposing `collect_atelier_status()`, `format_status_markdown()`, and CLI (`--workspace`, `--json`) with workspace resolution, active specs/tasks grouped by wave/status, strict SQLite `?mode=ro` + `PRAGMA query_only = ON` Bridge probe (symlink rejection, never creates missing `bridge.db`), `INT-07` hygiene alerts, and suggested actions.
  - Added `plugin/hooks.json` (`"python3 hooks/pre_invocation_architect.py"`) and `plugin/hooks/pre_invocation_architect.py` (100 % stdlib, 1s stdin timeout, active only on bare `/gravity-architect` or `/gravity-architect:gravity-architect` at `invocationNum` `0`/`None`, emitting ASCII-safe `injectSteps` + `terminationBehavior: "terminate"`).
  - Added `collect_atelier_hygiene_alerts()` and `extract_markdown_targets()` in `plugin/core/delta.py` (`INT-07`: `_TEMPLATE.md` drift, broken relative/`file:` links in Hot files & `audits/*/README.md`, and Hot budgets) and wired it into `plugin/scripts/sync_tracking.py` and `atelier_status.py`.
  - Added `has_real_python3()`, `fix_python_cmd()`, `--fix-python-cmd`, `_validate_hooks()`, `_validate_markdown_links()`, strict `SEMVER_RE` / `suggestedPrompts` / `disabled` / `author.name` checks (`INT-01/03/06`), and full `.py/.md/.json/.svg` BOM/LF checks in `plugin/scripts/validate.py`; wired automatic Windows `fix_python_cmd` into `install.py`.
  - Added `tests/test_hooks_and_status.py` and expanded `tests/test_core_structure.py`, `tests/test_init_and_install.py`, and `tests/test_sync_tracking.py`.
- **Wave 1 (`tasks/` & `plugin/core/waves.py`):**
  - Added `plugin/core/waves.py` (`<= 650 L`, 100 % stdlib Python 3.10+, exported in `plugin/core/__init__.py`) with `validate_waves(tasks, projects_cfg=None)` (*fail-closed*: integer `wave >= 1`, non-empty/known `target_project`, `<= 1` task per project per wave, disjoint normalized `target_files` per wave, acyclic 3-color DFS DAG with `dep != task_id`, existing `dep`, and `wave(dep) < wave(task)`, hybrid `::`/`~L` anchors on code files, and `<= 5` code files per task excluding tests/docs) and CLI `--check-waves`, `--workspace`, `--tasks-dir`, `--config`, `--json`.
  - Added `plugin/templates/task-template.md` (`Vague`, `Dépôt cible`, `Branche attendue`, `Dépendances`, `Profil workflow`, `Spec source`, `Date / Statut`, `## Ancres exactes` with `path::sym (~L...)`, `<= 5` code files, `caveman ultra` + `last_verified.patch` return) and optional `"post_commit_install_cmd": null` / `"verify_commands"` validation in `plugin/templates/projects.json` and `plugin/scripts/validate.py`.
  - Added `tests/test_waves.py` covering valid DAG, project/wave collision, file collision, cycle + `wave(dep) >= wave(task)`, missing hybrid anchor, `> 5` code files (excluding tests/docs), and CLI `--check-waves`.
- **Centralized Atelier Registry (`<architect_home>/ateliers.json`):**
  - Added `ATELIERS_REGISTRY_FILENAME`, `MAX_REGISTERED_ATELIERS = 20`, `resolve_ateliers_registry_path()`, and `register_atelier()` in `plugin/core/io_utils.py` (`schema_version: 1`, MRU ordering, canonical path deduplication, lazy stale-entry pruning, symlink rejection, corrupt-JSON recovery, atomic UTF-8/LF writes, and `GRAVITY_ARCHITECT_SKIP_REGISTRY=1` opt-out, without modifying `resolve_workspace_root()`).
  - Integrated `register_atelier()` (with facade re-exports) into `init_workspace()`, `add_projects_to_workspace()`, and `run_sync(dry_run=False)` while skipping writes on `--discover` and `--check` / `--dry-run`.
  - Updated `_run_e2e_dry_run()` in `plugin/scripts/validate.py` to isolate `GRAVITY_ARCHITECT_HOME` and verify `ateliers.json` creation on `init_workspace.py` and immutability on `sync_tracking.py --check`.
  - Added isolated `unittest` coverage for `register_atelier()`, registry integration, and test-suite isolation from `~/.gemini/`.
- **Skill Progressive Disclosure & Hygiene (`skills/gravity-architect/references/workflows-and-hygiene.md`):**
  - Added `plugin/skills/gravity-architect/references/workflows-and-hygiene.md` (UTF-8 without BOM, LF, zero leaks) detailing post-task wave checks & Bridge gateway, Plan Mode / token hygiene, WIP `--ack-editorial` guard, `manage_thread(action="get_job")`, `ecosystem_install.py --update --modules <...> --strict` closure guidance, and `../` discovery on argumentless `/gravity-architect add`.
  - Enforced existence and UTF-8/LF hygiene checks for `skills/gravity-architect/references/*.md` in `plugin/scripts/validate.py` (`_validate_skills()`) and added regression tests in `tests/test_core_structure.py` and `tests/test_init_and_install.py`.

### Changed
- **Wave 2 (4-Phase Cycle & Hybrid Checkpoint Docs):**
  - Updated `plugin/rules/AGENTS.md` (`<= 513 B`), `plugin/skills/gravity-architect/SKILL.md` (`<= 6 000 B`), `plugin/skills/gravity-architect/references/workflows-and-hygiene.md` (§6), `README.md`, and `plugin/README.md` to formalize bare `/gravity-architect` (`PreInvocation` 0-token RO) vs `/gravity-architect "<instruction>"` 4-phase cycle (`Conception` -> `Planification` with hybrid `RequestFeedback=True` and/or `ask_question` checkpoint -> `Production` with Bridge `batch_id` -> `Validation` with `verify_commands` and end-of-Validation reinstall).
- **Wave 1 (`tasks/` Unification across Core, Facades, Validator, Templates, Rules & Docs):**
  - Extended `parse_artifact_file()` and `collect_concept_artifacts()` in `plugin/core/io_utils.py` (`<= 650 L`) to scan `tasks/` and `tasks/archive/` (`pending_tasks`, `archived_tasks`, dropping `handoffs/`) and parse `id`, `wave`/`wave_raw`, `dependencies`, `workflow_profile`, `target_files`, and `anchors`.
  - Updated `compute_delta_with_state()` (`plugin/core/delta.py`) to include `artifacts`, updated `render_delta_markdown()` (`plugin/core/renderers.py`) to render `## Artefacts actifs` grouped by `Vague <N>` / `Sans vague`, renamed `format_project_handoffs_block()` to `format_project_tasks_block()` (`project-tasks:<id>`), updated `build_ecosystem_blocks()` / `apply_auto_doc_updates()`, and aligned `sync_tracking.py` / `init_workspace.py` / `validate.py` (`ALLOWED_LOCAL_MODULES` + `task-template.md`).
  - Removed `plugin/templates/handoff-template.md` and updated templates (`spec-template.md`, `project-card-template.md` with `Installé local` + 3 Invariants bullets + `project-tasks:<id>`, `audit-code-template.md`, `AGENTS.md`, `ECOSYSTEM.md`, `archives-readme.md`, `impact-template.md`, `projects.json`), `plugin/plugin.json` (`0.5.1`), `plugin/rules/AGENTS.md`, `plugin/skills/gravity-architect/SKILL.md`, `workflows-and-hygiene.md`, root `AGENTS.md`, `README.md`, and `plugin/README.md`.
- **Skill Compaction & Operational Hygiene (`SKILL.md <= 6 000 B`):**
  - Compacted `plugin/skills/gravity-architect/SKILL.md` (`<= 6 000 B`, keeping `plugin/rules/AGENTS.md <= 513 B` untouched) to embed the 5 operational rules (Bridge gateway with `rédigé, non déployé` status and single summary `ask_question`, Plan Mode no-op `sync` without `exit_plan_mode`, concise `exit_plan_mode` / read-only `research` delegation / `/compact` suggestion, WIP guard on `--ack-editorial` + `get_job` + `ecosystem_install.py`, and `../` recommendation on `/gravity-architect add`) with a relative link to `references/workflows-and-hygiene.md`, and synchronized `README.md` and `plugin/README.md`.
- **Architect Posture & Auto-Closure on `dev` with Global Fail-Closed Guard (`DOC-08` — `rules/AGENTS.md`, `templates/AGENTS.md`, `SKILL.md`, `workflows-and-hygiene.md`):**
  - Unified `plugin/rules/AGENTS.md` (`<= 513 B`), `plugin/templates/AGENTS.md` (`<= 2 500 B`), and `plugin/skills/gravity-architect/SKILL.md` (`<= 6 000 B`) to strictly separate read-only source code in tracked repositories (implementation delegated to target sessions) from automated `dev` closure (`git add`/`commit` on `dev`, non-force `git push origin dev`, `ecosystem_install.py --update --modules <...> --strict`, workshop archiving, and optional final `gravity-metrics` closure) once a plan/spec is validated, Bridge jobs are closed (`0` active), review is clean, and `100 %` of mandatory checks pass (global *fail-closed* guard: halt before any `commit`/`push` on any failure or non-`dev` branch).
  - Preserved explicit human-approval gates for `merge dev -> main`, SemVer tags, and releases, and no automatic `commit`/`push` on simple `/gravity-architect sync` (even with `--commit`).
  - Reordered `plugin/skills/gravity-architect/references/workflows-and-hygiene.md` (§3) so `commit`/`push origin dev` + `ecosystem_install.py --update` precede workshop archiving (`specs/archive/`, `tasks/archive/`) and `sync_tracking.py --offline --ack-editorial --print-delta` (eliminating WIP conflicts), followed by optional `gravity-metrics` closure, and synchronized `README.md`, `plugin/README.md`, and `tests/test_init_and_install.py`.
- **Empty-Workspace Greenfield Onboarding (`init_workspace.py`, `SKILL.md`, `ECOSYSTEM.md`):**
  - Added `_derive_default_workspace_name(ws_root)` in `plugin/scripts/init_workspace.py` to derive a readable default workspace name via `humanize_id(ws_root.name)` while falling back to `DEFAULT_WORKSPACE_NAME` (`"Mon Atelier Projets"`) for generic directory names (`""`, `"."`, `"/"`, `"tmp"`, `"temp"`, `"workspace"`, `"projects"`, `"repos"`, `"github"`) and preserving existing `workspace_name` on idempotent runs without `--name`.
  - Updated `plugin/skills/gravity-architect/SKILL.md` (`<= 6 000 B`) and added section `5. Onboarding sur workspace vide (greenfield)` in `plugin/skills/gravity-architect/references/workflows-and-hygiene.md` to route `/gravity-architect` to guided `init` when `./projects.json` is absent, offer a single `ask_question` (`0` project / `../` / direct paths), and initialize `0`-project workshops in one command (`init_workspace.py --workspace . --run-sync --offline`, without `--ack-editorial`).
  - Updated `plugin/templates/ECOSYSTEM.md` under `### Pistes actives` to point to `/gravity-architect add <chemin>` and `/gravity-architect spec <slug>` while preserving all `<!-- AUTO:START/END -->` blocks and LF line endings, and synchronized tests (`tests/test_init_and_install.py`) and docs (`README.md`, `plugin/README.md`).
- **End-of-Cycle `gravity-metrics` Closure (`SKILL.md`, `workflows-and-hygiene.md`):**
  - Formalized the 4-step end-of-lot closure sequence in `plugin/skills/gravity-architect/references/workflows-and-hygiene.md` (§3) with final optional `gravity-metrics` `cli.py archive <conversation_id> -l "<slug>" --workspace .` (with `--update-sealed` on later push/release in the same sealed session, never `--force`, tolerating `PendingBridgeJobsError`, silent no-op if absent).
  - Added a concise pointer under `archive <slug>` in `plugin/skills/gravity-architect/SKILL.md` (`<= 6 000 B`), removed the obsolete `gravity-metrics` entry from `PRIVATE_LEAK_RES` in `plugin/scripts/validate.py`, added regression tests in `tests/test_init_and_install.py`, and documented the optional final closure in `README.md` and `plugin/README.md`.

### Fixed
- **Idempotent `init_workspace()` Registry Name:** preserved existing `workspace_name` from `projects.json` in `<architect_home>/ateliers.json` when `init_workspace()` is re-run idempotently without an explicit `--name` (`DEFAULT_WORKSPACE_NAME` fallback only on creation, `--force`, or explicit `--name`).

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
