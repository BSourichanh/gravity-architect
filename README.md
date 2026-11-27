# Gravity Architect

> ### 2-Minute Quickstart & Ecosystem Role
> - **Tier:** **Tier 3 — Multi-Project** *(prerequisite: [`gravity`](https://github.com/BSourichanh/gravity) Core)*
> - **Role:** Orchestrate a Hot/Cold design workshop (`specs/`, `tasks/`, `audits/code/`) and track multiple repositories in strict read-only mode.
> - **Start:** `/gravity-architect init` then `/gravity-architect sync` (or bare `/gravity-architect` for 0-token status)
> - **Docs Hub (`gravity/docs/`):** [Getting Started](https://github.com/BSourichanh/gravity/blob/main/docs/getting-started.md) · [User Journey](https://github.com/BSourichanh/gravity/blob/main/docs/user-journey.md) · [Command Cheatsheet](https://github.com/BSourichanh/gravity/blob/main/docs/command-cheatsheet.md) · [Troubleshooting & Lifecycle](https://github.com/BSourichanh/gravity/blob/main/docs/troubleshooting-and-lifecycle.md)

> Generic Antigravity plugin (**100% Python 3.10+ standard library**) in the [Gravity](https://github.com/BSourichanh/gravity) ecosystem dedicated to architecture framing, multi-project design workshops, specifications (`specs/`), wave-planned tasks (`tasks/` + `wave_plan_v1`), **Hot / Cold** token budgets, privacy mode (`privacy.public_mode`), and read-only multi-repository tracking.

---

## Repository Layout

```text
gravity-architect/
├── AGENTS.md                        # Plugin developer charter (<= 2,500 B)
├── CHANGELOG.md                     # Release history (Keep a Changelog / SemVer)
├── LICENSE                          # MIT License
├── README.md                        # Repository documentation
├── install.py                       # Slim cross-platform installer/uninstaller (~70 L via _shared.installer_core)
├── plugin/                          # Standalone Antigravity plugin
│   ├── plugin.json                  # Official 9-field manifest
│   ├── hooks.json                   # PreInvocation hook configuration (enabled: true)
│   ├── config/module.json           # Gravity module contract (schema_version: 1, SPI-1 dashboard, SPI-2 capture_policy)
│   ├── README.md                    # Plugin user guide
│   ├── assets/logo.svg              # 1:1 square logo
│   ├── rules/AGENTS.md              # Lightweight activation rule
│   ├── hooks/pre_invocation_architect.py # 0-token PreInvocation status hook (_shared.hook_runtime)
│   ├── _shared/                     # Synced Python 3.10+ stdlib core projected from gravity/shared/gravity_shared/
│   ├── skills/gravity-architect/    # /gravity-architect skill + references/workflows-and-hygiene.md
│   ├── templates/                   # Hot/Cold workshop templates (spec, task, project card, audit-code, ...)
│   ├── core/                        # SRP core (io_utils, discovery, git_collector, watches, delta, renderers, waves)
│   └── scripts/                     # CLIs (sync_tracking, init_workspace, atelier_status, dashboard_provider) & slim validate.py (< 300 L)
└── tests/                           # Standard-library unittest suite
```

---

## Installation

> Requirement: **Python 3.10+** (100% standard library, zero external dependencies).

### Option 1 — Automatic Installer (Recommended, Windows / macOS / Linux)

```bash
git clone https://github.com/BSourichanh/gravity-architect.git
cd gravity-architect
python install.py
```

[`install.py`](install.py) delegates to [`plugin/_shared/installer_core.py`](plugin/_shared/installer_core.py), supporting all **11 CLI flags**, copying [`plugin/`](plugin/) to `~/.gemini/config/plugins/gravity-architect/`, setting POSIX executable permissions (`0755`), rewriting `"python3"` on Windows copies when needed, checking symlink/junction safety, handling locked file fallbacks, running `validate.py --strict` on a staged copy, and recording provenance in `$GRAVITY_HOME/core/sources.json`.

Useful commands:

```powershell
python install.py --check                                 # Inspect environment and installed status
python install.py --dry-run                               # Preview operations without writing
python install.py --force                                 # Upgrade or reinstall
python install.py --scope workspace --workspace <path>    # Install inside a target project (.agents/plugins/)
python install.py --uninstall                             # Cleanly uninstall
```

### Option 2 — Antigravity CLI (`agy`)

```bash
python install.py --method agy
# or directly:
agy plugin validate ./plugin --strict
agy plugin install ./plugin
```

---

## Quick Usage

Inside a target workshop (initialized via `/gravity-architect init` or `init_workspace.py`):

```powershell
python plugin/scripts/init_workspace.py --workspace ./my-workshop --discover --json
python plugin/scripts/init_workspace.py --workspace ./my-workshop --project ../my-app --watch antigravity
python plugin/scripts/init_workspace.py --workspace ./my-workshop --add ../other-repo
python plugin/scripts/sync_tracking.py --workspace ./my-workshop --print-delta
python plugin/core/waves.py --check-waves --workspace ./my-workshop --json
python plugin/core/waves.py --export-wave 1 --workspace ./my-workshop --json
python plugin/scripts/atelier_status.py --workspace ./my-workshop --json
python plugin/scripts/sync_tracking.py --workspace ./my-workshop --offline --ack-editorial --print-delta
```

Inside Antigravity, invoke `/gravity-architect` (0-token `PreInvocation` status) or `/gravity-architect [init|add|sync|status|spec|task|archive|audit]` (see [`plugin/README.md`](plugin/README.md) and [`plugin/skills/gravity-architect/references/workflows-and-hygiene.md`](plugin/skills/gravity-architect/references/workflows-and-hygiene.md)).

### Key Capabilities
- **Shared Core & Slim Entrypoints:** `install.py` (~70 L) and `plugin/scripts/validate.py` (< 300 L) delegate to `plugin/_shared/` (`installer_core`, `validator_core`, `hook_runtime`), synchronized from `gravity/shared/gravity_shared/`.
- **0-Token Bare `/gravity-architect` Hook:** `plugin/hooks.json` activates `hooks/pre_invocation_architect.py` (`PreInvocation`, `enabled: true`) backed by read-only `scripts/atelier_status.py` (`AUD-05-09` stale `ready` task detection).
- **Anti-Drift Wave Planning (`core/waves.py`):** fail-closed DAG ordering, file-disjointness per wave, `<= 5` code files per task, hybrid `::`/`~L` anchors, `Spec ID`/`Spec source` (`status == "validated"`)/`Acceptance Criteria Covered` enforcement, `wave_plan_v1` export for native `/swarm` execution (with `run_workflow` available as explicit opt-in).
- **Isolated Code Audits (`audits/code/`):** read-only Code & Architecture audits (`CODE-XX-N` `P0`/`P1`/`P2`) strictly separated from `audits/agents/`.
- **Product Repo Guard & Privacy Mode:** `init_workspace.py` refuses accidental initialization inside product repositories without `--force`, and `privacy.public_mode` filters `ECOSYSTEM.md` and masks local machine paths.
- **`SPI-1` & `SPI-2` Ecosystem Integration:** [`plugin/scripts/dashboard_provider.py`](plugin/scripts/dashboard_provider.py) serves read-only workshop state (`ateliers.json`, specs, wave tasks, `audits/code/`) to the unified `gravity` Core cockpit (`SPI-1`), while [`plugin/config/module.json`](plugin/config/module.json) declares `capture_policy` (`SPI-2`) for `gravity-metrics`.

---

## Developer Verification

```powershell
python plugin/scripts/validate.py --strict
agy plugin validate ./plugin --strict
python -m unittest discover -s tests -p "test_*.py" -v
```

---

## Documentation & Releases

- [`CHANGELOG.md`](CHANGELOG.md) — Release history (`v0.5.1` / `[Unreleased]`)
- [`plugin/README.md`](plugin/README.md) — Full plugin guide and `/gravity-architect` commands
- [`AGENTS.md`](AGENTS.md) — Charter, invariants, and mandatory checks

---

## License

Distributed under the MIT License — see [`LICENSE`](LICENSE) for details.
