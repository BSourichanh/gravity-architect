#!/usr/bin/env python3
"""Tests unitaires pour init_workspace.py, validate.py et install.py (100 % stdlib)."""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = REPO_ROOT / "plugin"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(PLUGIN_ROOT))
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from _shared import installer_core, validator_core  # noqa: E402
import init_workspace  # noqa: E402
import install  # noqa: E402
import validate  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return proc.stdout


def _make_git_repo(repo: Path, branch: str = "main", dev_branch: bool = False) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", branch)
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("# Demo\n\nPremiere phrase utile.\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "chore: init")
    if dev_branch:
        _git(repo, "branch", "dev")


class TestInitAndInstall(unittest.TestCase):
    def test_init_workspace_generic_and_idempotence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "atelier"
            res = init_workspace.init_workspace(
                ws,
                name="Atelier Test",
                preset="generic",
                projects=[("web", "../web"), ("api", "../api")],
            )
            self.assertIn("AGENTS.md", res["created"])
            self.assertIn("ECOSYSTEM.md", res["created"])
            self.assertIn("projects.json", res["created"])
            self.assertIn("tracking/projects/web.md", res["created"])
            self.assertIn("tracking/projects/api.md", res["created"])

            cfg = json.loads((ws / "projects.json").read_text(encoding="utf-8"))
            self.assertEqual(cfg["schema_version"], 5)
            self.assertEqual(cfg["workspace_name"], "Atelier Test")
            self.assertEqual(cfg["default_preset"], "generic")
            self.assertEqual([p["id"] for p in cfg["projects"]], ["web", "api"])

            # Modification manuelle préservée sans --force
            (ws / "ECOSYSTEM.md").write_text("# Custom\n", encoding="utf-8")
            res2 = init_workspace.init_workspace(ws, name="Atelier Test 2")
            self.assertEqual(res2["created"], [])
            self.assertIn("ECOSYSTEM.md", res2["skipped"])
            self.assertEqual((ws / "ECOSYSTEM.md").read_text(encoding="utf-8"), "# Custom\n")

            # --force écrase proprement
            res3 = init_workspace.init_workspace(ws, name="Atelier Reset", force=True)
            self.assertIn("ECOSYSTEM.md", res3["updated"])
            self.assertIn("Atelier Reset", (ws / "ECOSYSTEM.md").read_text(encoding="utf-8"))

    def test_init_workspace_antigravity_plugin_preset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ag-atelier"
            rc = init_workspace.main(
                [
                    "--workspace",
                    str(ws),
                    "--preset",
                    "antigravity-plugin",
                    "--project",
                    "myplug=../myplug",
                ]
            )
            self.assertEqual(rc, 0)
            cfg = json.loads((ws / "projects.json").read_text(encoding="utf-8"))
            self.assertEqual(cfg["privacy"], {"public_mode": False})
            self.assertEqual(cfg["projects"][0]["preset"], "antigravity-plugin")
            self.assertEqual(cfg["projects"][0]["plugin_manifest"], "plugin/plugin.json")
            self.assertEqual(cfg["projects"][0]["validator_script"], "plugin/scripts/validate.py")

    def test_validate_plugin_strict_passes_and_rejects_leaks_and_bad_module(self) -> None:
        report = validate.Report()
        validate.validate_plugin(PLUGIN_ROOT, report)
        self.assertTrue(report.ok(strict=True), f"Errors: {report.errors} | Warnings: {report.warnings}")

        with tempfile.TemporaryDirectory() as tmp:
            bad_plug = Path(tmp) / "bad-plugin"
            shutil.copytree(PLUGIN_ROOT, bad_plug, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            (bad_plug / "README.md").write_text("# Bad\nLocal path C:\\Users\\alice\\work\n", encoding="utf-8")
            bad_rep = validate.Report()
            validate.validate_plugin(bad_plug, bad_rep)
            self.assertFalse(bad_rep.ok(strict=True))
            self.assertTrue(any("Chemin personnel" in e for e in bad_rep.errors), bad_rep.errors)

            bad_mod_plug = Path(tmp) / "bad-mod-plugin"
            shutil.copytree(PLUGIN_ROOT, bad_mod_plug, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            mod_path = bad_mod_plug / "config" / "module.json"
            mod_data = json.loads(mod_path.read_text(encoding="utf-8"))
            mod_data["schema_version"] = 99
            mod_data["commands"] = ["gravity-architect"]
            mod_path.write_text(json.dumps(mod_data), encoding="utf-8")
            mod_rep = validate.Report()
            validate.validate_plugin(bad_mod_plug, mod_rep)
            self.assertFalse(mod_rep.ok(strict=True))
            joined = " | ".join(mod_rep.errors)
            self.assertIn("schema_version", joined)
            self.assertIn("commands", joined)

            mod_path.unlink()
            missing_mod_rep = validate.Report()
            validate.validate_plugin(bad_mod_plug, missing_mod_rep)
            self.assertFalse(missing_mod_rep.ok(strict=True))
            self.assertTrue(any("config/module.json" in e for e in missing_mod_rep.errors))

    def test_install_copy_check_dry_run_install_upgrade_and_uninstall(self) -> None:
        self.assertEqual(install.PLUGIN_SOURCE, REPO_ROOT / "plugin")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "plugins" / "gravity-architect"
            self.assertEqual(install.main(["--check", "--target", str(target)]), 0)
            self.assertEqual(install.main(["--dry-run", "--target", str(target)]), 0)
            self.assertFalse(target.exists())

            # Installation réelle
            self.assertEqual(install.main(["--target", str(target)]), 0)
            self.assertTrue(install.is_gravity_architect_plugin_dir(target))
            self.assertTrue((target / "config" / "module.json").is_file())

            # Refus sans --force
            self.assertEqual(install.main(["--target", str(target)]), 1)
            # Mise à niveau avec --force
            self.assertEqual(install.main(["--target", str(target), "--force"]), 0)

            # Désinstallation propre
            self.assertEqual(install.main(["--uninstall", "--target", str(target)]), 0)
            self.assertFalse(target.exists())

    def test_install_cli_strict_and_no_fix_python_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "plugins" / "gravity-architect"

            # --dry-run --strict --no-fix-python (and --strict overrides --skip-validate), zero disk writes
            dry_buf = io.StringIO()
            with contextlib.redirect_stdout(dry_buf):
                rc_dry = install.main(
                    [
                        "--dry-run",
                        "--skip-validate",
                        "--strict",
                        "--no-fix-python",
                        "--target",
                        str(target),
                    ]
                )
            self.assertEqual(rc_dry, 0)
            self.assertIn("validate.py --strict", dry_buf.getvalue())
            self.assertFalse(target.parent.exists())

            # --check --strict passes in read-only mode with zero disk writes
            chk_buf = io.StringIO()
            with contextlib.redirect_stdout(chk_buf):
                rc_chk = install.main(["--check", "--strict", "--target", str(target)])
            self.assertEqual(rc_chk, 0)
            self.assertIn("Strict validation: PASSED (0 error, 0 warning)", chk_buf.getvalue())
            self.assertFalse(target.parent.exists())

            # --check --strict returns 1 when strict validation fails
            fail_proc = subprocess.CompletedProcess(
                args=["validate.py"], returncode=1, stdout="", stderr="Strict error"
            )
            with mock.patch.object(installer_core, "run_plugin_validation", return_value=fail_proc):
                err_buf = io.StringIO()
                with contextlib.redirect_stderr(err_buf):
                    rc_fail = install.main(["--check", "--strict", "--target", str(target)])
            self.assertEqual(rc_fail, 1)
            self.assertIn("Strict validation: FAILED", err_buf.getvalue())

            # --method agy --dry-run includes --strict on agy plugin validate
            agy_buf = io.StringIO()
            with mock.patch("shutil.which", return_value="/usr/bin/agy"):
                with contextlib.redirect_stdout(agy_buf):
                    rc_agy = install.main(["--method", "agy", "--dry-run"])
            self.assertEqual(rc_agy, 0)
            self.assertIn("plugin validate", agy_buf.getvalue())
            self.assertIn("--strict", agy_buf.getvalue())

    def test_discover_repositories_scope_and_metadata_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = root / "atelier"
            ws.mkdir()

            # Atelier vide -> aucun scan implicite hors du dossier courant
            buf_empty = io.StringIO()
            with contextlib.redirect_stdout(buf_empty):
                rc = init_workspace.main(["--workspace", str(ws), "--discover", "--json"])
            self.assertEqual(rc, 0)
            payload_empty = json.loads(buf_empty.getvalue())
            self.assertEqual(payload_empty["candidates"], [])
            self.assertFalse(payload_empty["initialized"])

            # 1. Plugin Antigravity sur main + dev + CHANGELOG + AGENTS
            plug_repo = root / "My.Plugin"
            _make_git_repo(plug_repo, branch="main", dev_branch=True)
            (plug_repo / "plugin").mkdir()
            (plug_repo / "plugin" / "plugin.json").write_text(
                json.dumps(
                    {
                        "name": "my-plugin",
                        "displayName": "My Cool Plugin",
                        "version": "0.1.0",
                        "description": "Plugin de test complet.",
                    }
                ),
                encoding="utf-8",
            )
            (plug_repo / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
            (plug_repo / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")

            # 2. Dépôt générique sur master sans dev, avec package.json
            app_repo = root / "web-app"
            _make_git_repo(app_repo, branch="master", dev_branch=False)
            (app_repo / "package.json").write_text(
                json.dumps({"name": "web-app", "description": "App Node generique"}),
                encoding="utf-8",
            )

            # 3. Dépôt worktree avec fichier .git + README seul + branche custom
            wt_repo = root / "wt-tool"
            wt_repo.mkdir()
            (wt_repo / ".git").write_text("gitdir: ../fake-gitdir\n", encoding="utf-8")
            (wt_repo / "README.md").write_text(
                "# WT Tool\n\n[![badge](x)](y)\n\nOutil worktree rapide. Autre phrase.\n",
                encoding="utf-8",
            )

            # 4. Dossiers ignorés : .hidden, sous-niveau, et ws lui-même
            hidden_repo = root / ".hidden-repo"
            _make_git_repo(hidden_repo, branch="main")
            nested_parent = root / "group"
            nested_parent.mkdir()
            _make_git_repo(nested_parent / "nested-repo", branch="main")

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = init_workspace.main(
                    ["--workspace", str(ws), "--discover", "--scan-dir", str(root), "--json"]
                )
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            by_id = {c["id"]: c for c in payload["candidates"]}
            self.assertEqual(set(by_id.keys()), {"my-plugin", "web-app", "wt-tool"})

            p_cand = by_id["my-plugin"]
            self.assertEqual(p_cand["name"], "My Cool Plugin")
            self.assertEqual(p_cand["path"], "../My.Plugin")
            self.assertEqual(p_cand["preset"], "antigravity-plugin")
            self.assertEqual(p_cand["plugin_manifest"], "plugin/plugin.json")
            self.assertEqual(p_cand["validator_script"], "plugin/scripts/validate.py")
            self.assertEqual(p_cand["main_branch"], "main")
            self.assertEqual(p_cand["default_dev_branch"], "dev")
            self.assertEqual(p_cand["role"], "Plugin de test complet.")
            self.assertTrue(p_cand["has_changelog"])
            self.assertTrue(p_cand["has_agents"])

            a_cand = by_id["web-app"]
            self.assertEqual(a_cand["preset"], "generic")
            self.assertEqual(a_cand["main_branch"], "master")
            self.assertEqual(a_cand["default_dev_branch"], "master")
            self.assertEqual(a_cand["role"], "App Node generique")

            w_cand = by_id["wt-tool"]
            self.assertEqual(w_cand["role"], "Outil worktree rapide.")

            # Cross-drive fallback sur _compute_portable_path
            with mock.patch("os.path.relpath", side_effect=ValueError("different drive")):
                abs_path = init_workspace._compute_portable_path(app_repo, ws)
            self.assertEqual(Path(abs_path), app_repo.resolve())

    def test_init_with_path_only_watches_public_mode_and_run_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plug_repo = root / "plug-a"
            _make_git_repo(plug_repo, branch="main", dev_branch=True)
            (plug_repo / "plug-a-plugin").mkdir()
            (plug_repo / "plug-a-plugin" / "plugin.json").write_text(
                json.dumps(
                    {
                        "name": "plug-a",
                        "displayName": "Plug A",
                        "version": "1.0.0",
                        "description": "Plugin A",
                    }
                ),
                encoding="utf-8",
            )
            gen_repo = root / "app-b"
            _make_git_repo(gen_repo, branch="main", dev_branch=False)
            (gen_repo / "pyproject.toml").write_text(
                '[project]\nname = "app-b"\ndescription = "Backend Python"\n',
                encoding="utf-8",
            )

            # 1. Projet mixte -> default_preset == "generic", chacun garde son preset détecté
            ws_mixed = root / "ws-mixed"
            rc = init_workspace.main(
                [
                    "--workspace",
                    str(ws_mixed),
                    "--project",
                    str(plug_repo),
                    "--project",
                    str(gen_repo),
                    "--watch",
                    "antigravity",
                    "--watch",
                    "antigravity",
                    "--watch-url",
                    "mytool=https://example.com/CHANGELOG.md",
                    "--public-mode",
                    "--run-sync",
                    "--offline",
                ]
            )
            self.assertEqual(rc, 0)
            cfg = json.loads((ws_mixed / "projects.json").read_text(encoding="utf-8"))
            self.assertEqual(cfg["default_preset"], "generic")
            self.assertEqual(cfg["privacy"], {"public_mode": True})
            self.assertEqual(cfg["hot_budgets"]["tracking/antigravity/IMPACT.md"], 6000)

            proj_map = {p["id"]: p for p in cfg["projects"]}
            self.assertEqual(proj_map["plug-a"]["preset"], "antigravity-plugin")
            self.assertEqual(proj_map["plug-a"]["plugin_manifest"], "plug-a-plugin/plugin.json")
            self.assertEqual(proj_map["plug-a"]["validator_script"], "plug-a-plugin/scripts/validate.py")
            self.assertEqual(proj_map["app-b"]["preset"], "generic")
            self.assertEqual(proj_map["app-b"]["role"], "Backend Python")

            watches_map = {w["id"]: w for w in cfg["watches"]}
            self.assertEqual(set(watches_map.keys()), {"antigravity", "mytool"})
            ag_watch = watches_map["antigravity"]
            self.assertEqual(ag_watch["type"], "antigravity-changelog")
            self.assertEqual(ag_watch["url"], "https://antigravity.google/docs/changelog.md")
            self.assertEqual(
                [s["slug"] for s in ag_watch["surfaces"]],
                ["app", "cli", "ide-extensions", "sdk", "ide"],
            )
            self.assertEqual(watches_map["mytool"]["type"], "markdown-changelog")
            self.assertTrue((ws_mixed / "tracking" / "antigravity" / "IMPACT.md").is_file())
            self.assertTrue((ws_mixed / "tracking" / "snapshots" / "delta.md").is_file())

            # Idempotence IMPACT.md sans --force
            impact_path = ws_mixed / "tracking" / "antigravity" / "IMPACT.md"
            impact_path.write_text("# Custom Impact\n", encoding="utf-8")
            self.assertEqual(
                init_workspace.main(["--workspace", str(ws_mixed), "--watch", "antigravity"]),
                0,
            )
            self.assertEqual(impact_path.read_text(encoding="utf-8"), "# Custom Impact\n")

            # 2. Uniquement des plugins sans --preset -> default_preset == "antigravity-plugin"
            ws_plugins = root / "ws-plugins"
            self.assertEqual(
                init_workspace.main(["--workspace", str(ws_plugins), "--project", str(plug_repo)]),
                0,
            )
            cfg_p = json.loads((ws_plugins / "projects.json").read_text(encoding="utf-8"))
            self.assertEqual(cfg_p["default_preset"], "antigravity-plugin")

    def test_add_projects_fail_closed_and_creates_cards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = root / "atelier"
            repo1 = root / "repo-one"
            repo2 = root / "repo-two"
            _make_git_repo(repo1, branch="main", dev_branch=True)
            _make_git_repo(repo2, branch="main", dev_branch=False)

            # Échec si atelier non initialisé
            err_buf = io.StringIO()
            with contextlib.redirect_stderr(err_buf):
                rc_uninit = init_workspace.main(["--workspace", str(ws), "--add", str(repo1)])
            self.assertNotEqual(rc_uninit, 0)

            # Init avec repo1
            self.assertEqual(
                init_workspace.main(["--workspace", str(ws), "--project", str(repo1)]),
                0,
            )

            # Doublon d'id ou de chemin résolu refusé fail-closed avant écriture
            before_json = (ws / "projects.json").read_text(encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertNotEqual(
                    init_workspace.main(["--workspace", str(ws), "--add", str(repo1)]), 0
                )
                self.assertNotEqual(
                    init_workspace.main(
                        ["--workspace", str(ws), "--add", f"alias-one={repo1}"]
                    ),
                    0,
                )
                self.assertNotEqual(
                    init_workspace.main(
                        ["--workspace", str(ws), "--add", str(repo2), "--add", f"dup={repo2}"]
                    ),
                    0,
                )
            self.assertEqual((ws / "projects.json").read_text(encoding="utf-8"), before_json)
            self.assertFalse((ws / "tracking" / "projects" / "repo-two.md").exists())

            # Ajout valide de repo2
            self.assertEqual(
                init_workspace.main(["--workspace", str(ws), "--add", str(repo2)]),
                0,
            )
            raw_bytes = (ws / "projects.json").read_bytes()
            self.assertFalse(raw_bytes.startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(b"\r\n", raw_bytes)
            cfg = json.loads(raw_bytes.decode("utf-8"))
            self.assertEqual([p["id"] for p in cfg["projects"]], ["repo-one", "repo-two"])
            self.assertTrue((ws / "tracking" / "projects" / "repo-two.md").is_file())

    def test_init_deploys_audits_code_and_agents_gitkeep_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "atelier"
            res = init_workspace.init_workspace(ws, name="Atelier Audit")

            self.assertIn("audits/code/README.md", res["created"])
            self.assertIn("audits/code/_TEMPLATE.md", res["created"])
            self.assertIn("audits/agents/.gitkeep", res["created"])

            readme_path = ws / "audits" / "code" / "README.md"
            tpl_path = ws / "audits" / "code" / "_TEMPLATE.md"
            gitkeep_path = ws / "audits" / "agents" / ".gitkeep"

            self.assertEqual(gitkeep_path.read_bytes(), b"")
            for fpath in (readme_path, tpl_path):
                raw = fpath.read_bytes()
                self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), str(fpath))
                self.assertNotIn(b"\r\n", raw, str(fpath))

            # Préservation sans --force
            readme_path.write_text("# Custom Journal\n", encoding="utf-8")
            tpl_path.write_text("# Custom Template\n", encoding="utf-8")
            res2 = init_workspace.init_workspace(ws, name="Atelier Audit 2")
            self.assertIn("audits/code/README.md", res2["skipped"])
            self.assertIn("audits/code/_TEMPLATE.md", res2["skipped"])
            self.assertIn("audits/agents/.gitkeep", res2["skipped"])
            self.assertEqual(readme_path.read_text(encoding="utf-8"), "# Custom Journal\n")
            self.assertEqual(tpl_path.read_text(encoding="utf-8"), "# Custom Template\n")

            # Écrasement avec --force
            res3 = init_workspace.init_workspace(ws, name="Atelier Audit Reset", force=True)
            self.assertIn("audits/code/README.md", res3["updated"])
            self.assertIn("audits/code/_TEMPLATE.md", res3["updated"])
            self.assertIn("audits/agents/.gitkeep", res3["updated"])
            self.assertIn("Journal des audits", readme_path.read_text(encoding="utf-8"))
            self.assertIn("CODE-XX-N", tpl_path.read_text(encoding="utf-8"))

    def test_product_repo_guard_deploy_file_and_template_principles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            # 1. _deploy_file retourne un statut littéral sans muter de listes
            sample = root / "sample.txt"
            self.assertEqual(init_workspace._deploy_file(sample, "a\n", force=False), "created")
            self.assertEqual(init_workspace._deploy_file(sample, "b\n", force=False), "skipped")
            self.assertEqual(sample.read_text(encoding="utf-8"), "a\n")
            self.assertEqual(init_workspace._deploy_file(sample, "b\n", force=True), "updated")
            self.assertEqual(sample.read_text(encoding="utf-8"), "b\n")

            # 2. Garde-fou dépôt produit : .git + manifeste sans projects.json -> refus
            prod_repo = root / "prod-app"
            _make_git_repo(prod_repo, branch="main")
            (prod_repo / "package.json").write_text('{"name": "prod-app"}\n', encoding="utf-8")

            err_buf = io.StringIO()
            with contextlib.redirect_stderr(err_buf):
                rc_refused = init_workspace.main(["--workspace", str(prod_repo)])
            self.assertNotEqual(rc_refused, 0)
            self.assertIn("package.json", err_buf.getvalue())
            self.assertFalse((prod_repo / "projects.json").exists())
            self.assertFalse((prod_repo / "ECOSYSTEM.md").exists())

            # Refus propre en --json
            json_buf = io.StringIO()
            with contextlib.redirect_stdout(json_buf):
                rc_json = init_workspace.main(["--workspace", str(prod_repo), "--json"])
            self.assertNotEqual(rc_json, 0)
            err_payload = json.loads(json_buf.getvalue())
            self.assertFalse(err_payload["ok"])
            self.assertIn("package.json", err_payload["error"])

            # --force outrepasse le garde-fou, puis l'atelier existant reste idempotent sans --force
            self.assertEqual(
                init_workspace.main(["--workspace", str(prod_repo), "--force"]), 0
            )
            self.assertTrue((prod_repo / "projects.json").is_file())
            self.assertEqual(init_workspace.main(["--workspace", str(prod_repo)]), 0)

            # 3. Dossier avec .git seul (sans manifeste code/plugin) -> autorisé
            git_only = root / "git-atelier"
            _make_git_repo(git_only, branch="main")
            self.assertEqual(init_workspace.main(["--workspace", str(git_only)]), 0)
            agents_txt = (git_only / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("KISS, YAGNI, DRY, SOLID, CUPID", agents_txt)

    def test_validate_d4_rules_budget_and_root_agents_hygiene(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_repo = Path(tmp) / "repo"
            plug = fake_repo / "plugin"
            shutil.copytree(
                PLUGIN_ROOT, plug, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
            )
            # Copie valide avec AGENTS.md racine <= 2500 o, rules/AGENTS.md <= 600 o et SKILL.md <= 6000 o
            (fake_repo / "AGENTS.md").write_text(
                "# Root Agents\n- OK\n", encoding="utf-8", newline="\n"
            )
            ok_rep = validate.Report()
            validate.validate_plugin(plug, ok_rep)
            self.assertTrue(ok_rep.ok(strict=True), f"{ok_rep.errors} | {ok_rep.warnings}")
            self.assertEqual(ok_rep.warnings, [])

            # rules/AGENTS.md entre 601 et 1000 o -> OK hors --strict, échoue en --strict (warn "600")
            (plug / "rules" / "AGENTS.md").write_text(
                "x" * 650 + "\n", encoding="utf-8", newline="\n"
            )
            warn_rep = validate.Report()
            validate.validate_plugin(plug, warn_rep)
            self.assertTrue(warn_rep.ok(strict=False), warn_rep.errors)
            self.assertFalse(warn_rep.ok(strict=True))
            self.assertTrue(any("600" in w for w in warn_rep.warnings), warn_rep.warnings)

            # rules/AGENTS.md > 1000 o -> erreur bloquante
            (plug / "rules" / "AGENTS.md").write_text(
                "x" * 1001 + "\n", encoding="utf-8", newline="\n"
            )
            over_rep = validate.Report()
            validate.validate_plugin(plug, over_rep)
            self.assertFalse(over_rep.ok(strict=False))
            self.assertFalse(over_rep.ok(strict=True))
            self.assertTrue(any("1000 octets" in e for e in over_rep.errors), over_rep.errors)

            # Restaure rules/AGENTS.md ; SKILL.md > 6000 o -> erreur bloquante
            shutil.copy2(PLUGIN_ROOT / "rules" / "AGENTS.md", plug / "rules" / "AGENTS.md")
            skill_path = plug / "skills" / "gravity-architect" / "SKILL.md"
            skill_path.write_text(
                "---\nname: gravity-architect\ndescription: ok\n---\n" + ("s" * 6000) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            skill_over_rep = validate.Report()
            validate.validate_plugin(plug, skill_over_rep)
            self.assertFalse(skill_over_rep.ok(strict=True))
            self.assertTrue(
                any("SKILL.md" in e and "6000 octets" in e for e in skill_over_rep.errors),
                skill_over_rep.errors,
            )

            # Restaure SKILL.md, casse SKILL.md (BOM+CRLF), templates/AGENTS.md (CRLF) et AGENTS.md racine (> 2500 o)
            skill_path.write_bytes(
                b"\xef\xbb\xbf---\r\nname: gravity-architect\r\ndescription: ok\r\n---\r\n"
            )
            (plug / "templates" / "AGENTS.md").write_bytes(b"# Tpl\r\n")
            (fake_repo / "AGENTS.md").write_bytes(b"# Root\n" + b"a" * 2500)
            hygiene_rep = validate.Report()
            validate.validate_plugin(plug, hygiene_rep)
            self.assertFalse(hygiene_rep.ok(strict=True))
            joined = " | ".join(hygiene_rep.errors)
            self.assertIn("SKILL.md", joined)
            self.assertIn("BOM", joined)
            self.assertIn("templates/AGENTS.md", joined)
            self.assertIn("AGENTS.md", joined)

            # Restaure SKILL.md, templates/AGENTS.md et AGENTS.md racine ; casse references/workflows-and-hygiene.md (CRLF + BOM) puis absent -> erreurs bloquantes
            shutil.copy2(PLUGIN_ROOT / "skills" / "gravity-architect" / "SKILL.md", skill_path)
            shutil.copy2(PLUGIN_ROOT / "templates" / "AGENTS.md", plug / "templates" / "AGENTS.md")
            (fake_repo / "AGENTS.md").write_text("# Root Agents\n- OK\n", encoding="utf-8", newline="\n")
            ref_path = plug / "skills" / "gravity-architect" / "references" / "workflows-and-hygiene.md"
            ref_path.write_bytes(b"\xef\xbb\xbf# Ref\r\n")
            ref_bad_rep = validate.Report()
            validate.validate_plugin(plug, ref_bad_rep)
            self.assertFalse(ref_bad_rep.ok(strict=True))
            ref_bad_joined = " | ".join(ref_bad_rep.errors)
            self.assertIn("workflows-and-hygiene.md", ref_bad_joined)
            self.assertIn("CRLF", ref_bad_joined)

            ref_path.unlink()
            ref_missing_rep = validate.Report()
            validate.validate_plugin(plug, ref_missing_rep)
            self.assertFalse(ref_missing_rep.ok(strict=True))
            self.assertTrue(
                any("workflows-and-hygiene.md introuvable" in e for e in ref_missing_rep.errors),
                ref_missing_rep.errors,
            )

    def test_skill_references_hygiene_budgets_and_critical_rules(self) -> None:
        skill_path = PLUGIN_ROOT / "skills" / "gravity-architect" / "SKILL.md"
        ref_path = PLUGIN_ROOT / "skills" / "gravity-architect" / "references" / "workflows-and-hygiene.md"
        rules_path = PLUGIN_ROOT / "rules" / "AGENTS.md"

        self.assertTrue(skill_path.is_file())
        self.assertTrue(ref_path.is_file())
        self.assertLessEqual(rules_path.stat().st_size, 513)

        skill_raw = skill_path.read_bytes()
        ref_raw = ref_path.read_bytes()
        for label, raw in (("SKILL.md", skill_raw), ("workflows-and-hygiene.md", ref_raw)):
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"BOM in {label}")
            self.assertNotIn(b"\r\n", raw, f"CRLF in {label}")

        self.assertLessEqual(len(skill_raw), 6000, f"SKILL.md exceeds 6000 B ({len(skill_raw)})")

        skill_txt = skill_raw.decode("utf-8")
        ref_txt = ref_raw.decode("utf-8")
        meta, _ = validator_core.parse_frontmatter(skill_txt)
        self.assertEqual(meta.get("name"), "gravity-architect")
        self.assertLessEqual(len(str(meta.get("description") or "")), 160)
        self.assertIn("references/workflows-and-hygiene.md", skill_txt)

        for label, rx in validate.PRIVATE_LEAK_RES:
            self.assertIsNone(rx.search(ref_txt), f"Leak ({label}) in workflows-and-hygiene.md")
        self.assertIsNone(validate.FORBIDDEN_MOD_RE.search(ref_txt))

        critical_tokens = (
            "drafted, not deployed",
            "--ack-editorial",
            "ecosystem_install.py",
            "wave_plan_v1",
            "--export-wave",
            "/swarm",
            "quick",
            "standard",
            "<= 5",
            "250k",
            "exit_plan_mode",
            "NO_EDITORIAL_CHANGES",
            "../",
            "/compact",
            "PreInvocation",
            "atelier_status.py",
            "RequestFeedback=True",
            "ask_question",
            "verify_commands",
            "opt-in",
        )
        for token in critical_tokens:
            self.assertIn(token, skill_txt, f"Missing rule in SKILL.md: {token}")
            self.assertIn(token, ref_txt, f"Missing rule in workflows-and-hygiene.md: {token}")

        self.assertIn("gravity-metrics", skill_txt)
        self.assertIn("references/workflows-and-hygiene.md) §3", skill_txt)
        for token in (
            "fail-closed",
            "git push origin dev",
            "merge dev -> main",
            "explicit human approval",
            "gravity-metrics/scripts/cli.py archive <conversation_id>",
            "--update-sealed",
            "--force",
            "silent no-op",
            "waiting",
            "fork",
            "@monitor",
            "3.8 Flash",
        ):
            self.assertIn(token, ref_txt, f"Missing closure/swarm rule in workflows-and-hygiene.md: {token}")

        idx_verifs = ref_txt.index("1. **Reviews & verification")
        idx_dev_push = ref_txt.index("2. **Auto-closure on `dev`")
        idx_archive = ref_txt.index("3. **Workshop archiving & `--ack-editorial`")
        idx_metrics = ref_txt.index("4. **Optional `gravity-metrics`")
        self.assertLess(idx_verifs, idx_dev_push)
        self.assertLess(idx_dev_push, idx_archive)
        self.assertLess(idx_archive, idx_metrics)

        plugin_readme_txt = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
        repo_readme_txt = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        plugin_json_txt = (PLUGIN_ROOT / "plugin.json").read_text(encoding="utf-8")
        for doc_label, doc_txt in (
            ("SKILL.md", skill_txt),
            ("workflows-and-hygiene.md", ref_txt),
            ("plugin/README.md", plugin_readme_txt),
            ("README.md", repo_readme_txt),
            ("plugin.json", plugin_json_txt),
        ):
            self.assertNotIn("handoffs/", doc_txt, f"Legacy handoffs/ drift in {doc_label}")
            self.assertNotIn("bridge", doc_txt.lower(), f"Bridge mention in {doc_label}")
            self.assertNotIn("gravity-" + "studio", doc_txt.lower(), f"Legacy studio ref in {doc_label}")
            self.assertNotIn("gravity_" + "studio", doc_txt.lower(), f"Legacy studio ref in {doc_label}")
            for forbidden in (
                "get_job",
                "manage_thread",
                "wave_runner.py",
                "caveman ultra",
                "last_verified.patch",
                "skip_separate_planner",
                "apply_on_pass",
            ):
                self.assertNotIn(forbidden, doc_txt, f"Internal workflow ref {forbidden!r} in {doc_label}")

        for doc_label, doc_txt in (
            ("SKILL.md", skill_txt),
            ("workflows-and-hygiene.md", ref_txt),
            ("plugin/README.md", plugin_readme_txt),
            ("README.md", repo_readme_txt),
        ):
            self.assertIn("opt-in", doc_txt, f"Missing opt-in mention in {doc_label}")
            self.assertIn("swarm", doc_txt.lower(), f"Missing swarm mention in {doc_label}")

    def test_validate_int01_03_06_and_fix_python_cmd_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_repo = root / "repo"
            plug = fake_repo / "plugin"
            shutil.copytree(PLUGIN_ROOT, plug, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            (fake_repo / "README.md").write_text("# Repo\n- [Plugin](plugin/README.md)\n", encoding="utf-8", newline="\n")

            ok_rep = validate.Report()
            validate.validate_plugin(plug, ok_rep)
            self.assertTrue(ok_rep.ok(strict=True), f"{ok_rep.errors} | {ok_rep.warnings}")

            # 1. Manifeste invalide (SemVer, suggestedPrompts, disabled, author)
            manifest_path = plug / "plugin.json"
            orig_manifest = manifest_path.read_text(encoding="utf-8")
            bad_manifest = json.loads(orig_manifest)
            bad_manifest["version"] = "not-semver"
            bad_manifest["disabled"] = "no"
            bad_manifest["author"] = {"name": ""}
            bad_manifest["suggestedPrompts"] = ["sans slash", "/cmd", "/ok — " + ("x" * 100)]
            manifest_path.write_text(json.dumps(bad_manifest), encoding="utf-8", newline="\n")
            man_rep = validate.Report()
            validate.validate_plugin(plug, man_rep)
            self.assertFalse(man_rep.ok(strict=True))
            man_err = " | ".join(man_rep.errors)
            self.assertIn("SemVer", man_err)
            self.assertIn("disabled", man_err)
            self.assertIn("author", man_err)
            self.assertIn("suggestedPrompts", man_err)
            manifest_path.write_text(orig_manifest, encoding="utf-8", newline="\n")

            # 2. hooks.json invalide (clé inconnue, script .py manquant, CRLF)
            hooks_path = plug / "hooks.json"
            orig_hooks = hooks_path.read_bytes()
            hooks_path.write_bytes(b'{"g": {"badKey": true, "PreInvocation": [{"type": "command", "command": "python3 hooks/missing.py"}]}}\r\n')
            hk_rep = validate.Report()
            validate.validate_plugin(plug, hk_rep)
            self.assertFalse(hk_rep.ok(strict=True))
            hk_err = " | ".join(hk_rep.errors)
            self.assertIn("clés inconnues", hk_err)
            self.assertIn("hooks/missing.py", hk_err)
            self.assertIn("CRLF", hk_err)
            hooks_path.write_bytes(orig_hooks)

            # 3. BOM sur .svg et liens cassés / file: sur README/SKILL/../README
            (plug / "assets" / "logo.svg").write_bytes(
                b"\xef\xbb\xbf" + (PLUGIN_ROOT / "assets" / "logo.svg").read_bytes()
            )
            (plug / "README.md").write_text("# Plug\n- [Bad](missing/file.md)\n- [File](file:///tmp/x)\n", encoding="utf-8", newline="\n")
            (fake_repo / "README.md").write_text("# Repo\n- [Broken](../nope.md)\n", encoding="utf-8", newline="\n")
            link_rep = validate.Report()
            validate.validate_plugin(plug, link_rep)
            self.assertFalse(link_rep.ok(strict=True))
            lk_err = " | ".join(link_rep.errors)
            self.assertIn("BOM UTF-8", lk_err)
            self.assertIn("Lien Markdown relatif cassé dans README.md", lk_err)
            self.assertIn("Lien 'file:' interdit dans README.md", lk_err)
            self.assertIn("Lien Markdown relatif cassé dans ../README.md", lk_err)

            # 4. install.py + fix_python_cmd sous Windows simulé (source intacte)
            src_hooks_before = (PLUGIN_ROOT / "hooks.json").read_text(encoding="utf-8")

            class _FakeWindowsOs:
                name = "nt"

                def __getattr__(self, attr: str):
                    return getattr(os, attr)

            target_win = root / "inst-win"
            with (
                mock.patch.object(installer_core, "os", _FakeWindowsOs()),
                mock.patch.object(installer_core, "has_real_python3", return_value=False),
            ):
                dry_buf = io.StringIO()
                with contextlib.redirect_stdout(dry_buf):
                    self.assertEqual(install.main(["--dry-run", "--target", str(target_win)]), 0)
                self.assertIn("--fix-python-cmd", dry_buf.getvalue())

                target_nofix = root / "inst-nofix"
                self.assertEqual(install.main(["--no-fix-python", "--target", str(target_nofix)]), 0)
                self.assertIn("python3 hooks/pre_invocation_architect.py", (target_nofix / "hooks.json").read_text(encoding="utf-8"))

                with (
                    mock.patch.object(validator_core, "has_real_python3", return_value=False),
                    mock.patch.object(validator_core, "_detect_portable_python_cmd", return_value="python"),
                ):
                    self.assertEqual(validate.main(["--plugin-root", str(target_nofix), "--fix-python-cmd"]), 0)
                adapted_hooks = json.loads((target_nofix / "hooks.json").read_text(encoding="utf-8"))
                self.assertEqual(
                    adapted_hooks["gravity-architect-command"]["PreInvocation"][0]["command"],
                    "python hooks/pre_invocation_architect.py",
                )
            self.assertEqual((PLUGIN_ROOT / "hooks.json").read_text(encoding="utf-8"), src_hooks_before)

    def test_installer_core_symlink_lock_fallback_and_sources_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_home = root / "home"
            fake_home.mkdir()
            gravity_home = root / "gravity-home"
            sources_path = gravity_home / "core" / "sources.json"
            sources_path.parent.mkdir(parents=True, exist_ok=True)
            existing_gravity_entry = {
                "plugin_name": "gravity",
                "repo_dir": str(root / "gravity"),
                "install_method": "copy",
                "installed_version": "0.3.0",
            }
            sources_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "updated_at": "2026-11-25T10:00:00Z",
                        "sources": {"gravity": existing_gravity_entry},
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )

            # 1. Symlink target rejection
            real_dir = root / "real-dir"
            real_dir.mkdir()
            sym_target = root / "sym-target"
            if hasattr(os, "symlink"):
                os.symlink(real_dir, sym_target)
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(install.main(["--target", str(sym_target)]), 1)

            # 2. --check / --dry-run do not modify sources.json
            with (
                mock.patch.object(Path, "home", return_value=fake_home),
                mock.patch.dict(os.environ, {"GRAVITY_HOME": str(gravity_home)}),
            ):
                self.assertEqual(install.main(["--check"]), 0)
                self.assertEqual(install.main(["--dry-run"]), 0)
                self.assertNotIn("gravity-architect", json.loads(sources_path.read_text(encoding="utf-8"))["sources"])

                # 3. Real global install records sources.json atomically and preserves gravity
                global_target = (fake_home / ".gemini" / "config" / "plugins" / "gravity-architect").resolve()
                self.assertEqual(install.main(["--scope", "global"]), 0)
                self.assertTrue(install.is_gravity_architect_plugin_dir(global_target))
                raw_bytes = sources_path.read_bytes()
                self.assertFalse(raw_bytes.startswith(b"\xef\xbb\xbf"))
                self.assertNotIn(b"\r\n", raw_bytes)
                payload = json.loads(raw_bytes.decode("utf-8"))
                self.assertEqual(payload["schema_version"], 1)
                self.assertEqual(payload["sources"]["gravity"], existing_gravity_entry)
                entry = payload["sources"]["gravity-architect"]
                self.assertEqual(entry["plugin_name"], "gravity-architect")
                self.assertEqual(Path(entry["repo_dir"]), REPO_ROOT.resolve())
                self.assertEqual(entry["install_method"], "copy")
                self.assertEqual(Path(entry["target_dir"]), global_target)
                self.assertTrue(entry["git_sha"])

                # 4. Failed reinstall & --uninstall do not rewrite sources.json
                before_fail = sources_path.read_text(encoding="utf-8")
                self.assertEqual(install.main([]), 1)
                self.assertEqual(sources_path.read_text(encoding="utf-8"), before_fail)

                # 5. is_lock_oserror in-place upgrade fallback on PermissionError
                lock_err = PermissionError(13, "locked")
                out_buf = io.StringIO()
                with (
                    mock.patch.object(installer_core.os, "rename", side_effect=lock_err),
                    contextlib.redirect_stdout(out_buf),
                ):
                    self.assertEqual(install.main(["--scope", "global", "--force"]), 0)
                self.assertIn("(in-place)", out_buf.getvalue())
                self.assertTrue(install.is_gravity_architect_plugin_dir(global_target))

                # 6. Uninstall cleanly
                self.assertEqual(install.main(["--uninstall"]), 0)
                self.assertFalse(global_target.exists())
                self.assertEqual(sources_path.read_text(encoding="utf-8"), before_fail)


if __name__ == "__main__":
    unittest.main()
