#!/usr/bin/env python3
"""Tests unitaires pour gravity-architect-plugin/scripts/sync_tracking.py (100 % stdlib)."""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

PLUGIN_SCRIPTS = (
    Path(__file__).resolve().parent.parent / "gravity-architect-plugin" / "scripts"
)
sys.path.insert(0, str(PLUGIN_SCRIPTS))

import sync_tracking  # noqa: E402


SAMPLE_AG_CHANGELOG = """# Changelog

## Antigravity App

### [v2.34.0](/releases?tab=hub&version=2.34.0 "View release 2.34.0")

Latest

November 20, 2026

### Gemini 4 Neon, MCP Apps, and more

*   MCP Apps support and Gemini 4 Neon for paid plans.
*   Dock icon adapts to Dark Mode.

---

Model launch·November 18, 2026

### Gemini 4 Neon

New default model.

---

### [v2.33.0](/releases?tab=hub&version=2.33.0 "View release 2.33.0")

November 17, 2026

### Connect over SSH

*   SSH & PR integration with /swarm support.

---

### [v2.32.0](/releases?tab=hub&version=2.32.0 "View release 2.32.0")

*   Dynamic Workflows

## IDE Extensions

Model launch·November 18, 2026

### Gemini 4 Neon

Model block before first release.

---

### [v1.13.0](/docs/ide/extensions/vscode "View VSCode")

*   Shortcuts update

---

### [v1.12.0](/docs/ide/extensions/vscode "View VSCode")

*   Instant startup

---

### [v1.11.0](/docs/ide/extensions/vscode "View VSCode")

*   Scoped diff review
"""


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return proc.stdout


def _init_demo_repo(repo: Path, compliant: bool = False) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "plugin").mkdir()
    if compliant:
        manifest = {
            "name": "demo",
            "displayName": "Demo",
            "version": "0.1.0",
            "description": "Plugin de démonstration conforme au standard.",
            "logo": "assets/logo.svg",
            "suggestedPrompts": ["Cmd 1", "Cmd 2", "Cmd 3"],
            "author": {"name": "Tests"},
            "homepage": "https://example.com/demo",
            "repository": "https://example.com/demo.git",
        }
        (repo / "plugin" / "scripts").mkdir(parents=True)
        (repo / "plugin" / "scripts" / "validate.py").write_text("# ok\n", encoding="utf-8")
        (repo / "README.md").write_text("# Demo\n", encoding="utf-8")
        (repo / "install.py").write_text("# ok\n", encoding="utf-8")
        (repo / ".gitattributes").write_text("* text=auto eol=lf\n", encoding="utf-8")
        (repo / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
        (repo / "tests").mkdir()
        (repo / "AGENTS.md").write_text(
            "# Demo\n\n## Périmètre & Architecture\n- Plugin.\n\n"
            "## Invariants\n- Python stdlib.\n\n"
            "## Vérifications obligatoires\n- `unittest`\n",
            encoding="utf-8",
        )
    else:
        manifest = {"name": "demo", "displayName": "Demo", "version": "0.1.0"}
        (repo / "AGENTS.md").write_text("# Demo Agents\n- Rule 1\n", encoding="utf-8")

    (repo / "plugin" / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    (repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [0.1.0] - 2026-11-21\n- Initial release\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "chore: release v0.1.0")
    _git(repo, "tag", "v0.1.0")


class TestSyncTracking(unittest.TestCase):
    def test_resolve_workspace_root_direct_subfolder_env_and_ambiguity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # 1. Sous-dossier atelier unique auto-détecté (nom quelconque)
            ws = root / "my_atelier"
            ws.mkdir()
            (ws / "projects.json").write_text("{}\n", encoding="utf-8")
            (ws / "ECOSYSTEM.md").write_text("# Eco\n", encoding="utf-8")
            c_root, c_cfg = sync_tracking.resolve_workspace_root(cwd=root, env={})
            self.assertEqual(c_root, ws.resolve())
            self.assertEqual(c_cfg, (ws / "projects.json").resolve())

            # 2. Variable d'environnement prioritaire sur l'auto-détection cwd
            ws_env = root / "env_atelier"
            ws_env.mkdir()
            (ws_env / "projects.json").write_text("{}\n", encoding="utf-8")
            e_root, e_cfg = sync_tracking.resolve_workspace_root(
                cwd=root,
                env={"GRAVITY_ARCHITECT_WORKSPACE": str(ws_env)},
            )
            self.assertEqual(e_root, ws_env.resolve())
            self.assertEqual(e_cfg, (ws_env / "projects.json").resolve())

            # 3. Directement dans cwd
            d_root, d_cfg = sync_tracking.resolve_workspace_root(cwd=ws, env={})
            self.assertEqual(d_root, ws.resolve())
            self.assertEqual(d_cfg, (ws / "projects.json").resolve())

            # 4. Ambiguïté si deux sous-dossiers ateliers coexistent
            (ws_env / "ECOSYSTEM.md").write_text("# Eco 2\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                sync_tracking.resolve_workspace_root(cwd=root, env={})

    def test_multi_format_version_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            pkg_repo = root / "node-app"
            pkg_repo.mkdir()
            (pkg_repo / "package.json").write_text('{"name": "node-app", "version": "2.4.1"}\n', encoding="utf-8")
            self.assertEqual(sync_tracking.detect_version_source({}, pkg_repo), "package.json")
            self.assertEqual(
                sync_tracking.parse_version_from_text("package.json", (pkg_repo / "package.json").read_text("utf-8"))["version"],
                "2.4.1",
            )

            py_repo = root / "py-app"
            py_repo.mkdir()
            (py_repo / "pyproject.toml").write_text(
                '[project]\nname = "py-app"\nversion = "0.9.5"\n', encoding="utf-8"
            )
            self.assertEqual(sync_tracking.detect_version_source({}, py_repo), "pyproject.toml")
            self.assertEqual(
                sync_tracking.parse_version_from_text("pyproject.toml", (py_repo / "pyproject.toml").read_text("utf-8"))["version"],
                "0.9.5",
            )

            rust_repo = root / "rust-app"
            rust_repo.mkdir()
            (rust_repo / "Cargo.toml").write_text(
                '[package]\nname = "rust-app"\nversion = "1.0.3"\n', encoding="utf-8"
            )
            self.assertEqual(sync_tracking.detect_version_source({}, rust_repo), "Cargo.toml")
            self.assertEqual(
                sync_tracking.parse_version_from_text("Cargo.toml", (rust_repo / "Cargo.toml").read_text("utf-8"))["version"],
                "1.0.3",
            )

            cfg_repo = root / "cfg-app"
            cfg_repo.mkdir()
            (cfg_repo / "setup.cfg").write_text("[metadata]\nname = cfg-app\nversion = 3.1.0\n", encoding="utf-8")
            self.assertEqual(sync_tracking.detect_version_source({}, cfg_repo), "setup.cfg")
            self.assertEqual(
                sync_tracking.parse_version_from_text("setup.cfg", (cfg_repo / "setup.cfg").read_text("utf-8"))["version"],
                "3.1.0",
            )

            ver_repo = root / "plain-app"
            ver_repo.mkdir()
            (ver_repo / "VERSION").write_text("# comment\n4.2.0\n", encoding="utf-8")
            self.assertEqual(sync_tracking.detect_version_source({}, ver_repo), "VERSION")
            self.assertEqual(
                sync_tracking.parse_version_from_text("VERSION", (ver_repo / "VERSION").read_text("utf-8"))["version"],
                "4.2.0",
            )

            custom_json = '{"meta": {"release": "5.0.0"}}'
            self.assertEqual(
                sync_tracking.parse_version_from_text("custom.json", custom_json, version_json_path="meta.release")["version"],
                "5.0.0",
            )

    def test_parse_antigravity_changelog_and_markdown_watch(self) -> None:
        surfaces = [
            {"heading": "Antigravity App", "slug": "app"},
            {"heading": "IDE Extensions", "slug": "ide-extensions"},
        ]
        parsed = sync_tracking.parse_antigravity_changelog(
            SAMPLE_AG_CHANGELOG, surfaces=surfaces, releases_per_surface=2
        )
        self.assertEqual(parsed["app"]["versions"], ["v2.34.0", "v2.33.0"])
        self.assertEqual(parsed["ide-extensions"]["versions"], ["v1.13.0", "v1.12.0"])

        md_watch = (
            "# Releases\n\n"
            "## [Unreleased]\n- Ignore me\n\n"
            "## [2.1.0] - 2026-11-22\n- Added plugin hook API\n- UI polish\n\n"
            "## [2.0.0] - 2026-11-10\n- Major rewrite\n"
        )
        w_parsed = sync_tracking.parse_markdown_changelog_watch(
            md_watch, watch_id="mytool", watch_name="MyTool", releases_limit=2, keywords=["hook"]
        )
        self.assertEqual(w_parsed["mytool"]["versions"], ["2.1.0", "2.0.0"])
        self.assertEqual(w_parsed["mytool"]["release_titles"]["2.1.0"], "2026-11-22")
        self.assertEqual(w_parsed["mytool"]["release_digests"]["2.1.0"], ["Added plugin hook API"])

    def test_extract_relevant_antigravity_bullets_filters_and_truncates(self) -> None:
        block = (
            "*   Added MCP Apps and hook validation.\n"
            "*   Dock icon adapts to Dark Mode.\n"
            "*   " + ("run_workflow " * 20) + "\n"
        )
        res = sync_tracking.extract_relevant_antigravity_bullets(
            block, ["mcp", "run_workflow"], max_bullets=5, max_chars=40
        )
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0], "Added MCP Apps and hook validation.")
        self.assertTrue(res[1].endswith("…"))
        self.assertLessEqual(len(res[1]), 40)

    def test_extract_latest_changelog_section_and_unreleased(self) -> None:
        md_non_empty = (
            "# Changelog\n\n"
            "## [Unreleased]\n\n### Added\n- Pending item\n\n"
            "## [0.1.2] - 2026-11-22\n\n### Fixed\n- Bug X\n"
        )
        res1 = sync_tracking.extract_latest_changelog_section(md_non_empty)
        self.assertTrue(res1["has_unreleased"])
        self.assertTrue(res1["unreleased_has_content"])
        self.assertEqual(res1["latest_changelog_version"], "Unreleased")
        self.assertEqual(res1["latest_released_changelog_version"], "0.1.2")
        self.assertEqual(res1["latest_released_changelog_date"], "2026-11-22")

        md_empty = (
            "# Changelog\n\n"
            "## [Unreleased]\n\n"
            "## [0.1.2] - 2026-11-22\n\n### Fixed\n- Bug X\n"
        )
        res2 = sync_tracking.extract_latest_changelog_section(md_empty)
        self.assertTrue(res2["has_unreleased"])
        self.assertFalse(res2["unreleased_has_content"])
        self.assertEqual(res2["latest_changelog_version"], "0.1.2")

    def test_evaluate_project_compliance_generic_vs_antigravity_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # 1. Projet générique minimal -> OK sans bruit Antigravity
            gen_repo = tmp_path / "gen-proj"
            gen_repo.mkdir()
            (gen_repo / "README.md").write_text("# Generic\n", encoding="utf-8")
            comp_gen = sync_tracking.evaluate_project_compliance({"id": "gen"}, gen_repo, default_preset="generic")
            self.assertTrue(comp_gen["ok"], comp_gen["issues"])

            # Règles opt-in génériques
            comp_opt = sync_tracking.evaluate_project_compliance(
                {"id": "gen", "compliance": {"required_files": ["README.md", "LICENSE"], "required_dirs": ["src"]}},
                gen_repo,
                default_preset="generic",
            )
            self.assertFalse(comp_opt["ok"])
            self.assertIn("LICENSE manquant", comp_opt["issues"])
            self.assertIn("src/ manquant", comp_opt["issues"])

            # 2. Preset antigravity-plugin strict
            ok_repo = tmp_path / "ok-proj"
            _init_demo_repo(ok_repo, compliant=True)
            cfg_ag = {
                "id": "demo",
                "preset": "antigravity-plugin",
                "plugin_manifest": "plugin/plugin.json",
                "validator_script": "plugin/scripts/validate.py",
                "changelog": "CHANGELOG.md",
                "agents_file": "AGENTS.md",
            }
            comp_ok = sync_tracking.evaluate_project_compliance(cfg_ag, ok_repo)
            self.assertTrue(comp_ok["ok"], comp_ok["issues"])

            bad_repo = tmp_path / "bad-proj"
            _init_demo_repo(bad_repo, compliant=False)
            (bad_repo / "AGENTS.md").write_text("# Trop long\n" + ("x" * 2600), encoding="utf-8")
            comp_bad = sync_tracking.evaluate_project_compliance(cfg_ag, bad_repo)
            self.assertFalse(comp_bad["ok"])
            joined = " | ".join(comp_bad["issues"])
            self.assertIn("champs manquants", joined)
            self.assertIn("> 2500 o", joined)
            self.assertIn("section(s) manquante(s)", joined)
            self.assertIn("README.md manquant", joined)

    def test_evaluate_hot_budgets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tracking" / "projects").mkdir(parents=True)
            (root / "AGENTS.md").write_text("ok\n", encoding="utf-8")
            (root / "ECOSYSTEM.md").write_text("x" * 6500, encoding="utf-8")
            (root / "tracking" / "projects" / "demo.md").write_text("y" * 3600, encoding="utf-8")

            report = sync_tracking.evaluate_hot_budgets(root, None, ["demo"])
            self.assertFalse(report["AGENTS.md"]["over_budget"])
            self.assertTrue(report["ECOSYSTEM.md"]["over_budget"])
            self.assertTrue(report["tracking/projects/demo.md"]["over_budget"])

    def test_collect_project_snapshot_stable_wip_branches_install_drift_and_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "demo-proj"
            _init_demo_repo(repo)
            _git(repo, "checkout", "-b", "dev")
            (repo / "plugin" / "plugin.json").write_text(
                json.dumps({"name": "demo", "displayName": "Demo", "version": "0.2.0"}),
                encoding="utf-8",
            )
            _git(repo, "add", "-A")
            _git(repo, "commit", "-m", "feat: bump dev")

            (repo / "tracked.txt").write_text("v2\n", encoding="utf-8")
            (repo / ".agents").mkdir()
            (repo / ".agents" / "state.json").write_text("{}\n", encoding="utf-8")

            changelogs_dir = tmp_path / "archives" / "changelogs"
            cfg = {
                "id": "demo",
                "name": "Demo",
                "path": str(repo),
                "preset": "antigravity-plugin",
                "plugin_manifest": "plugin/plugin.json",
                "changelog": "CHANGELOG.md",
                "main_branch": "main",
                "default_dev_branch": "dev",
                "runtime_ignore_paths": [".agents/", ".agents"],
            }
            snap = sync_tracking.collect_project_snapshot(
                cfg,
                base_dir=tmp_path,
                changelogs_dir=changelogs_dir,
                installed_plugins_map={"demo": {"name": "demo", "version": "0.1.0"}},
                concept_root=tmp_path,
            )

            self.assertTrue(snap["exists"])
            self.assertEqual(snap["stable"]["version"], "0.2.0")
            self.assertEqual(snap["stable"]["installed_version"], "0.1.0")
            self.assertTrue(snap["stable"]["install_drift"])
            self.assertEqual(snap["stable"]["latest_tag"], "v0.1.0")
            self.assertEqual(snap["stable"]["branches"]["dev_ahead_of_main"], 1)
            self.assertEqual(snap["wip"]["code_wip_count"], 1)

            (repo / "tracked.txt").unlink()
            snap_rt = sync_tracking.collect_project_snapshot(
                cfg,
                base_dir=tmp_path,
                changelogs_dir=changelogs_dir,
                concept_root=tmp_path,
            )
            self.assertEqual(snap_rt["wip"]["code_wip_count"], 0)
            self.assertTrue(snap_rt["wip"]["runtime_only_wip"])

            missing = sync_tracking.collect_project_snapshot(
                {"id": "absent", "path": "./does-not-exist"},
                base_dir=tmp_path,
                changelogs_dir=changelogs_dir,
                concept_root=tmp_path,
            )
            self.assertFalse(missing["exists"])

    def test_version_integrity_tag_on_dev_and_no_merges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "demo"
            _init_demo_repo(repo, compliant=True)
            _git(repo, "checkout", "-b", "dev")

            manifest = json.loads((repo / "plugin" / "plugin.json").read_text(encoding="utf-8"))
            manifest["version"] = "0.1.2"
            (repo / "plugin" / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
            (repo / "CHANGELOG.md").write_text(
                "# Changelog\n\n"
                "## [0.1.2] - 2026-11-22\n- Release 0.1.2\n\n"
                "## [0.1.0] - 2026-11-21\n- Initial\n",
                encoding="utf-8",
            )
            _git(repo, "add", "-A")
            _git(repo, "commit", "-m", "chore: release v0.1.2")
            _git(repo, "tag", "v0.1.2")

            # Merge commit sur main puis fast-forward / alignement dev -> 0 commit non tagué grâce à --no-merges
            _git(repo, "checkout", "main")
            _git(repo, "merge", "--no-ff", "dev", "-m", "Merge dev into main for v0.1.2")
            _git(repo, "checkout", "dev")
            _git(repo, "merge", "--ff-only", "main")

            cfg = {
                "id": "demo",
                "name": "Demo",
                "path": str(repo),
                "preset": "antigravity-plugin",
                "plugin_manifest": "plugin/plugin.json",
                "validator_script": "plugin/scripts/validate.py",
                "changelog": "CHANGELOG.md",
                "main_branch": "main",
                "default_dev_branch": "dev",
            }
            snap_merged = sync_tracking.collect_project_snapshot(
                cfg, base_dir=root, changelogs_dir=root / "archives" / "changelogs", concept_root=root
            )
            self.assertTrue(snap_merged["stable"]["branches"]["latest_tag_on_main"])
            self.assertEqual(snap_merged["stable"]["branches"]["commits_since_latest_tag"], 0)

            # Vrai commit non-merge après tag
            (repo / "README.md").write_text("# Demo\nNext feature.\n", encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-m", "feat: post-tag work")
            snap_after = sync_tracking.collect_project_snapshot(
                cfg, base_dir=root, changelogs_dir=root / "archives" / "changelogs", concept_root=root
            )
            self.assertEqual(snap_after["stable"]["branches"]["commits_since_latest_tag"], 1)

    def test_install_audit_content_hash_enabled_flag_and_orphan_plugin_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "demo"
            _init_demo_repo(repo, compliant=True)
            (repo / "plugin" / "hooks.json").write_text('{"cmd": "python3 hook.py"}\n', encoding="utf-8")

            fake_home = root / "home"
            inst_plugins = fake_home / "config" / "plugins"
            inst_demo = inst_plugins / "demo"
            shutil.copytree(repo / "plugin", inst_demo)
            (inst_demo / "hooks.json").write_text('{"cmd": "python hook.py"}\r\n', encoding="utf-8")
            (inst_demo / "__pycache__").mkdir()
            (inst_demo / "__pycache__" / "mod.pyc").write_bytes(b"\x00\x01")
            (inst_plugins / "orphan-dir" / "sidecars").mkdir(parents=True)
            (fake_home / "config" / "config.json").write_text(
                json.dumps({"plugins": {"demo": {"enabled": False}}}),
                encoding="utf-8",
            )

            env = sync_tracking.collect_local_antigravity_env(gemini_home=fake_home)
            self.assertEqual(env["orphan_plugin_dirs"], ["orphan-dir"])
            self.assertEqual([p["name"] for p in env["installed_plugins"]], ["demo"])
            self.assertFalse(env["installed_plugins"][0]["enabled"])

            installed_map = {p["name"]: p for p in env["installed_plugins"]}
            cfg = {
                "id": "demo",
                "name": "Demo",
                "path": str(repo),
                "preset": "antigravity-plugin",
                "plugin_manifest": "plugin/plugin.json",
                "validator_script": "plugin/scripts/validate.py",
                "changelog": "CHANGELOG.md",
                "main_branch": "main",
                "default_dev_branch": "dev",
            }
            snap = sync_tracking.collect_project_snapshot(
                cfg,
                base_dir=root,
                changelogs_dir=root / "archives" / "changelogs",
                installed_plugins_map=installed_map,
                concept_root=root,
                default_preset="antigravity-plugin",
            )
            self.assertFalse(snap["stable"]["install_content_drift"])
            self.assertFalse(snap["stable"]["installed_enabled"])

            (inst_demo / "scripts" / "validate.py").write_text("# drifted\n", encoding="utf-8")
            snap2 = sync_tracking.collect_project_snapshot(
                cfg,
                base_dir=root,
                changelogs_dir=root / "archives" / "changelogs",
                installed_plugins_map=installed_map,
                concept_root=root,
                default_preset="antigravity-plugin",
            )
            self.assertTrue(snap2["stable"]["install_content_drift"])
            self.assertEqual(snap2["stable"]["install_content_diff_files"], ["scripts/validate.py"])

            delta = sync_tracking.compute_delta(
                None,
                {
                    "synced_at": "2026-11-22T02:00:00+01:00",
                    "environment": env,
                    "projects": [snap2],
                    "watches": {},
                },
                root,
            )
            joined = "\n".join(delta["hygiene_alerts"])
            self.assertIn("diffère du dépôt à version égale (1 fichier(s) : scripts/validate.py)", joined)
            self.assertIn("désactivé dans `config.json` (`enabled: false`)", joined)
            self.assertIn("dossier(s) sans `plugin.json` (`orphan-dir`)", joined)

    def test_collect_concept_artifacts_ignores_templates_and_tracks_archives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "specs" / "archive").mkdir(parents=True)
            (root / "handoffs" / "archive").mkdir(parents=True)
            (root / "specs" / "_TEMPLATE.md").write_text("# Template\n", encoding="utf-8")
            (root / "handoffs" / "_TEMPLATE.md").write_text("# Template\n", encoding="utf-8")
            (root / "specs" / "2026-11-22-demo.md").write_text(
                "# Spec Demo\n- **Statut :** `validated`\n- **Projets impactés :** `alpha`\n",
                encoding="utf-8",
            )
            (root / "handoffs" / "2026-11-22-alpha-demo.md").write_text(
                "# Handoff Demo\n- **Dépôt cible :** `alpha`\n- **Date / Statut :** `2026-11-22` — `ready`\n",
                encoding="utf-8",
            )
            arts = sync_tracking.collect_concept_artifacts(root)
            self.assertEqual(len(arts["specs"]), 1)
            self.assertEqual(len(arts["pending_handoffs"]), 1)

            blk = sync_tracking._format_project_handoffs_block(
                "alpha",
                {
                    "pending_handoffs": [
                        {"filename": "2026-11-22-alpha-beta-x.md", "rel_path": "h1.md", "title": "AB", "status": "ready", "target_project": "alpha-beta"},
                        {"filename": "2026-11-22-alpha-x.md", "rel_path": "h2.md", "title": "A", "status": "ready", "target_project": "alpha"},
                    ],
                    "archived_handoffs": [],
                },
            )
            self.assertIn("2026-11-22-alpha-x.md", blk)
            self.assertNotIn("2026-11-22-alpha-beta-x.md", blk)

    def test_delta_auto_blocks_idempotence_editorial_state_and_watches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "demo"
            _init_demo_repo(repo, compliant=True)
            _git(repo, "checkout", "-b", "dev")

            (root / "tracking" / "projects").mkdir(parents=True)
            (root / "tracking" / "antigravity").mkdir(parents=True)
            (root / "specs" / "archive").mkdir(parents=True)
            (root / "handoffs" / "archive").mkdir(parents=True)
            (root / "AGENTS.md").write_text("# Architect\n", encoding="utf-8")

            (root / "ECOSYSTEM.md").write_text(
                "# Tableau\n"
                "<!-- AUTO:START:ecosystem-meta -->\nold\n<!-- AUTO:END:ecosystem-meta -->\n"
                "<!-- AUTO:START:ecosystem-projects -->\nold\n<!-- AUTO:END:ecosystem-projects -->\n"
                "<!-- AUTO:START:ecosystem-watches -->\nold\n<!-- AUTO:END:ecosystem-watches -->\n"
                "<!-- AUTO:START:ecosystem-artifacts -->\nold\n<!-- AUTO:END:ecosystem-artifacts -->\n"
                "<!-- AUTO:START:ecosystem-hygiene -->\nold\n<!-- AUTO:END:ecosystem-hygiene -->\n",
                encoding="utf-8",
            )
            (root / "tracking" / "projects" / "demo.md").write_text(
                "# Demo\n<!-- AUTO:START:project-meta:demo -->\nold\n<!-- AUTO:END:project-meta:demo -->\n"
                "Prose projet intacte.\n"
                "<!-- AUTO:START:project-handoffs:demo -->\nold\n<!-- AUTO:END:project-handoffs:demo -->\n",
                encoding="utf-8",
            )
            (root / "tracking" / "antigravity" / "IMPACT.md").write_text(
                "# Impact\n<!-- AUTO:START:watch-meta:antigravity -->\nold\n<!-- AUTO:END:watch-meta:antigravity -->\n"
                "Analyse manuelle préservée.\n",
                encoding="utf-8",
            )

            cfg_path = root / "projects.json"
            cfg_path.write_text(
                json.dumps(
                    {
                        "schema_version": 5,
                        "default_preset": "antigravity-plugin",
                        "watches": [
                            {
                                "id": "antigravity",
                                "name": "Google Antigravity",
                                "type": "antigravity-changelog",
                                "url": "https://example.invalid/changelog.md",
                                "out_dir": "tracking/antigravity",
                                "impact_file": "tracking/antigravity/IMPACT.md",
                                "releases_per_surface": 2,
                                "surfaces": [{"heading": "Antigravity App", "slug": "app"}],
                            }
                        ],
                        "projects": [
                            {
                                "id": "demo",
                                "name": "Demo",
                                "path": "demo",
                                "preset": "antigravity-plugin",
                                "plugin_manifest": "plugin/plugin.json",
                                "validator_script": "plugin/scripts/validate.py",
                                "changelog": "CHANGELOG.md",
                                "agents_file": "AGENTS.md",
                                "main_branch": "main",
                                "default_dev_branch": "dev",
                                "role": "Demo project",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            out_dir = root / "tracking"
            fake_home = root / "home"
            fake_home.mkdir()

            with mock.patch.object(sync_tracking, "fetch_antigravity_changelog", return_value=SAMPLE_AG_CHANGELOG):
                _, d1 = sync_tracking.run_sync(
                    config_path=cfg_path, out_dir=out_dir, gemini_home=fake_home, concept_root=root
                )
                self.assertTrue(d1["needs_editorial_update"])
                self.assertIn("ECOSYSTEM.md", d1["auto_updated_files"])

                app_file = out_dir / "antigravity" / "releases" / "app.md"
                app_mtime_before = app_file.stat().st_mtime_ns

                # 2e passage sans édition prose ni --ack-editorial : persiste EDITORIAL_UPDATE_REQUIRED
                _, d2 = sync_tracking.run_sync(
                    config_path=cfg_path, out_dir=out_dir, gemini_home=fake_home, concept_root=root
                )
                self.assertTrue(d2["needs_editorial_update"])
                self.assertEqual(app_file.stat().st_mtime_ns, app_mtime_before)

                # Édition prose -> auto-acquittement
                demo_card = root / "tracking" / "projects" / "demo.md"
                demo_card.write_text(
                    demo_card.read_text(encoding="utf-8").replace("Prose projet intacte.", "Prose mise à jour."),
                    encoding="utf-8",
                )
                impact_doc = root / "tracking" / "antigravity" / "IMPACT.md"
                impact_doc.write_text(
                    impact_doc.read_text(encoding="utf-8").replace("Analyse manuelle préservée.", "Analyse mise à jour."),
                    encoding="utf-8",
                )
                _, d2_acked = sync_tracking.run_sync(
                    config_path=cfg_path, out_dir=out_dir, gemini_home=fake_home, concept_root=root
                )
                self.assertFalse(d2_acked["needs_editorial_update"])

                # Modification AGENTS.md + CHANGELOG.md -> puis --ack-editorial CLI
                (repo / "AGENTS.md").write_text(
                    "# Demo\n\n## Périmètre & Architecture\n- Plugin.\n\n"
                    "## Invariants\n- Python stdlib.\n- Rule 2.\n\n"
                    "## Vérifications obligatoires\n- `unittest`\n",
                    encoding="utf-8",
                )
                (repo / "CHANGELOG.md").write_text(
                    "# Changelog\n\n## [0.1.1] - 2026-11-22\n- Fix B\n\n## [0.1.0] - 2026-11-21\n- Initial\n",
                    encoding="utf-8",
                )
                _, d3 = sync_tracking.run_sync(
                    config_path=cfg_path, out_dir=out_dir, gemini_home=fake_home, concept_root=root
                )
                self.assertTrue(d3["needs_editorial_update"])
                self.assertEqual(d3["editorial_targets"], ["tracking/projects/demo.md"])

                ack_buf = io.StringIO()
                with contextlib.redirect_stdout(ack_buf):
                    rc_ack = sync_tracking.main(
                        [
                            "--workspace",
                            str(root),
                            "--offline",
                            "--ack-editorial",
                            "--print-delta",
                        ]
                    )
                self.assertEqual(rc_ack, 0)
                self.assertIn("NO_EDITORIAL_CHANGES", ack_buf.getvalue())

    def test_zero_churn_on_unchanged_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "demo"
            _init_demo_repo(repo, compliant=True)
            _git(repo, "checkout", "-b", "dev")
            (root / "tracking" / "projects").mkdir(parents=True)
            (root / "AGENTS.md").write_text("# Architect\n", encoding="utf-8")
            (root / "ECOSYSTEM.md").write_text(
                "# Eco\n"
                "<!-- AUTO:START:ecosystem-meta -->\n<!-- AUTO:END:ecosystem-meta -->\n"
                "<!-- AUTO:START:ecosystem-projects -->\n<!-- AUTO:END:ecosystem-projects -->\n"
                "<!-- AUTO:START:ecosystem-watches -->\n<!-- AUTO:END:ecosystem-watches -->\n"
                "<!-- AUTO:START:ecosystem-artifacts -->\n<!-- AUTO:END:ecosystem-artifacts -->\n"
                "<!-- AUTO:START:ecosystem-hygiene -->\n<!-- AUTO:END:ecosystem-hygiene -->\n",
                encoding="utf-8",
            )
            (root / "tracking" / "projects" / "demo.md").write_text(
                "# Demo\n<!-- AUTO:START:project-meta:demo -->\n<!-- AUTO:END:project-meta:demo -->\n"
                "<!-- AUTO:START:project-handoffs:demo -->\n<!-- AUTO:END:project-handoffs:demo -->\n",
                encoding="utf-8",
            )
            cfg_path = root / "projects.json"
            cfg_path.write_text(
                json.dumps(
                    {
                        "schema_version": 5,
                        "default_preset": "generic",
                        "watches": [],
                        "projects": [
                            {
                                "id": "demo",
                                "name": "Demo",
                                "path": "demo",
                                "changelog": "CHANGELOG.md",
                                "agents_file": "AGENTS.md",
                                "main_branch": "main",
                                "default_dev_branch": "dev",
                                "role": "Demo",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            out_dir = root / "tracking"
            sync_tracking.run_sync(
                config_path=cfg_path, out_dir=out_dir, concept_root=root, ack_editorial=True
            )
            sync_tracking.run_sync(
                config_path=cfg_path, out_dir=out_dir, concept_root=root
            )

            watched = [
                out_dir / "snapshots" / "ecosystem_snapshot.json",
                out_dir / "snapshots" / "ecosystem_snapshot.md",
                out_dir / "snapshots" / "delta.json",
                out_dir / "snapshots" / "delta.md",
                out_dir / "snapshots" / "editorial_state.json",
                root / "ECOSYSTEM.md",
                root / "tracking" / "projects" / "demo.md",
            ]
            mtimes_before = {p: p.stat().st_mtime_ns for p in watched}

            next_day = datetime(2026, 11, 23, 9, 0, tzinfo=timezone(timedelta(hours=1)))
            with mock.patch.object(sync_tracking, "datetime") as mock_dt:
                mock_dt.now.return_value = next_day
                _, d_next = sync_tracking.run_sync(
                    config_path=cfg_path, out_dir=out_dir, concept_root=root
                )
            self.assertFalse(d_next["needs_editorial_update"])
            self.assertEqual(d_next["auto_updated_files"], [])
            for p in watched:
                self.assertEqual(p.stat().st_mtime_ns, mtimes_before[p], str(p))

    def test_main_offline_does_not_touch_source_repo_and_zero_watches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "no-changelog"
            repo.mkdir()
            _git(repo, "init", "-b", "main")
            _git(repo, "config", "user.name", "Test User")
            _git(repo, "config", "user.email", "test@example.com")
            (repo / "package.json").write_text('{"name": "pkg", "version": "1.0.0"}\n', encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-m", "init")
            before_head = _git(repo, "rev-parse", "HEAD").strip()

            cfg_path = tmp_path / "projects.json"
            cfg_path.write_text(
                json.dumps(
                    {
                        "schema_version": 5,
                        "default_preset": "generic",
                        "watches": [],
                        "projects": [
                            {
                                "id": "nochg",
                                "name": "NoChg",
                                "path": "no-changelog",
                                "default_dev_branch": "main",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            out_dir = tmp_path / "tracking"
            rc = sync_tracking.main(["--config", str(cfg_path), "--out-dir", str(out_dir), "--offline"])
            self.assertEqual(rc, 0)

            snap = json.loads((out_dir / "snapshots" / "ecosystem_snapshot.json").read_text(encoding="utf-8"))
            self.assertEqual(snap["projects"][0]["stable"]["version"], "1.0.0")
            self.assertEqual(snap["environment"]["installed_plugins"], [])
            self.assertEqual(_git(repo, "rev-parse", "HEAD").strip(), before_head)
            self.assertEqual(_git(repo, "status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()
