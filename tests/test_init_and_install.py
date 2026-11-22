#!/usr/bin/env python3
"""Tests unitaires pour init_workspace.py, validate.py et install.py (100 % stdlib)."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = REPO_ROOT / "plugin"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

import init_workspace  # noqa: E402
import install  # noqa: E402
import validate  # noqa: E402


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
            self.assertTrue(any("Fuite spécifique" in e for e in bad_rep.errors), bad_rep.errors)

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


if __name__ == "__main__":
    unittest.main()
