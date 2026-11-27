#!/usr/bin/env python3
"""Tests structurels du découpage `plugin/core/`, des façades et de l'installation (100 % stdlib)."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = REPO_ROOT / "plugin"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

import init_workspace  # noqa: E402
import install  # noqa: E402
import sync_tracking  # noqa: E402

CORE_MODULES = (
    "__init__.py",
    "io_utils.py",
    "discovery.py",
    "git_collector.py",
    "watches.py",
    "delta.py",
    "renderers.py",
    "waves.py",
)


class TestCoreStructureAndFacades(unittest.TestCase):
    def test_core_modules_line_budgets_and_lf_no_bom(self) -> None:
        core_dir = PLUGIN_ROOT / "core"
        self.assertTrue(core_dir.is_dir())
        for fname in CORE_MODULES:
            fpath = core_dir / fname
            self.assertTrue(fpath.is_file(), f"Module manquant : {fpath}")
            raw = fpath.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"BOM détecté dans {fname}")
            self.assertNotIn(b"\r\n", raw, f"CRLF détecté dans {fname}")
            line_count = len(raw.decode("utf-8").splitlines())
            self.assertLessEqual(line_count, 650, f"{fname} dépasse 650 lignes ({line_count})")

        sync_lines = len((PLUGIN_ROOT / "scripts" / "sync_tracking.py").read_text(encoding="utf-8").splitlines())
        init_lines = len((PLUGIN_ROOT / "scripts" / "init_workspace.py").read_text(encoding="utf-8").splitlines())
        self.assertLessEqual(sync_lines, 250, f"sync_tracking.py dépasse 250 lignes ({sync_lines})")
        self.assertLessEqual(init_lines, 450, f"init_workspace.py dépasse 450 lignes ({init_lines})")

        for script_path in (PLUGIN_ROOT / "scripts").glob("*.py"):
            raw = script_path.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"BOM détecté dans {script_path.name}")
            self.assertNotIn(b"\r\n", raw, f"CRLF détecté dans {script_path.name}")

        for rel in ("hooks.json", "hooks/pre_invocation_architect.py", "scripts/atelier_status.py"):
            fpath = PLUGIN_ROOT / rel
            self.assertTrue(fpath.is_file(), f"Fichier manquant : {fpath}")
            raw = fpath.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"BOM détecté dans {rel}")
            self.assertNotIn(b"\r\n", raw, f"CRLF détecté dans {rel}")

    def test_facades_reexport_backward_compatible_symbols(self) -> None:
        sync_expected = (
            "SCHEMA_VERSION", "DEFAULT_HOT_BUDGETS", "DEFAULT_WATCH_KEYWORDS", "MACHINE_ABS_PATH_RE",
            "default_architect_home", "resolve_workspace_root", "resolve_public_mode", "load_config",
            "run_readonly_cmd", "compare_plugin_dirs", "extract_latest_changelog_section",
            "parse_version_from_text", "detect_plugin_manifest", "derive_validator_script",
            "detect_version_source", "resolve_project_preset", "evaluate_project_compliance",
            "evaluate_hot_budgets", "collect_project_snapshot", "collect_local_antigravity_env",
            "collect_concept_artifacts", "extract_relevant_antigravity_bullets",
            "parse_antigravity_changelog", "parse_markdown_changelog_watch",
            "fetch_url_text", "fetch_antigravity_changelog", "render_surface_markdown",
            "render_ecosystem_snapshot_markdown", "compute_delta_with_state", "compute_delta",
            "render_delta_markdown", "format_delta_for_stdout", "replace_auto_block",
            "apply_auto_doc_updates", "run_sync", "build_parser", "main",
            "register_atelier", "resolve_ateliers_registry_path", "workspace_lock_path",
            "collect_atelier_hygiene_alerts", "_parse_semver_tuple", "_compare_cli_versions",
            "_build_ecosystem_blocks", "_format_project_tasks_block", "shutil", "datetime",
        )
        for name in sync_expected:
            self.assertTrue(hasattr(sync_tracking, name), f"sync_tracking.{name} manquant")

        init_expected = (
            "PROJECT_ID_RE", "PRODUCT_MANIFEST_FILES", "ANTIGRAVITY_CHANGELOG_URL",
            "ANTIGRAVITY_IMPACT_BUDGET", "ANTIGRAVITY_WATCH_SURFACES",
            "DEFAULT_WORKSPACE_NAME", "_derive_default_workspace_name",
            "inspect_project_dir", "discover_repositories", "init_workspace",
            "add_projects_to_workspace", "build_parser", "main", "register_atelier",
            "_deploy_file", "_compute_portable_path", "_parse_target_spec",
            "_parse_project_specs", "_parse_watch_urls", "_build_antigravity_watch",
            "run_sync",
        )
        for name in init_expected:
            self.assertTrue(hasattr(init_workspace, name), f"init_workspace.{name} manquant")

    def test_atomic_write_utf8_and_installer_copies_core(self) -> None:
        from core import io_utils
        from core.io_utils import write_utf8

        self.assertIn("scripts/dashboard_provider.py", install.EXEC_SCRIPTS)
        with mock.patch.object(io_utils, "write_text_atomic", wraps=io_utils.write_text_atomic) as spy_write, mock.patch.object(
            io_utils, "safe_home_dir", return_value=Path("/tmp/safe-home")
        ) as spy_home:
            self.assertEqual(io_utils.default_architect_home(env={}), (Path("/tmp/safe-home") / ".gemini" / "gravity" / "architect").resolve())
            spy_home.assert_called_once()
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                out_file = tmp_path / "nested" / "sample.md"
                write_utf8(out_file, "# Titre\r\nLigne 2\r\n")
                spy_write.assert_called_once_with(out_file, "# Titre\r\nLigne 2\r\n")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_file = tmp_path / "nested" / "sample.md"
            write_utf8(out_file, "# Titre\r\nLigne 2\r\n")
            raw = out_file.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(b"\r\n", raw)
            self.assertEqual(raw.decode("utf-8"), "# Titre\nLigne 2\n")
            leftovers = [p for p in out_file.parent.iterdir() if p.name.endswith(".tmp")]
            self.assertEqual(leftovers, [])

            sym_target = tmp_path / "sym.md"
            try:
                sym_target.symlink_to(out_file)
            except (OSError, NotImplementedError):
                pass
            else:
                with self.assertRaises(ValueError):
                    write_utf8(sym_target, "blocked\n")

            target = tmp_path / "installed-plugin"
            rc = install.main(["--target", str(target)])
            self.assertEqual(rc, 0)
            for fname in CORE_MODULES:
                self.assertTrue((target / "core" / fname).is_file(), f"core/{fname} non copié par install.py")
            for rel in (
                "skills/gravity-architect/references/workflows-and-hygiene.md",
                "hooks.json",
                "hooks/pre_invocation_architect.py",
                "scripts/atelier_status.py",
                "scripts/dashboard_provider.py",
                "_shared/atomic_io.py",
                "_shared/file_lock.py",
                "_shared/path_safety.py",
            ):
                self.assertTrue((target / rel).is_file(), f"{rel} non copié par install.py")

        manifest = json.loads((PLUGIN_ROOT / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "0.6.0")
        self.assertLessEqual((PLUGIN_ROOT / "rules" / "AGENTS.md").stat().st_size, 513)


if __name__ == "__main__":
    unittest.main()
