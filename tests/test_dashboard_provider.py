#!/usr/bin/env python3
"""Unit tests for plugin/scripts/dashboard_provider.py (SPI-1) and plugin/config/module.json (SPI-1/2)."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = REPO_ROOT / "plugin"
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from _shared import validator_core  # noqa: E402
from scripts import dashboard_provider as dp  # noqa: E402
from scripts import validate as architect_validate  # noqa: E402


def _clean_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in ("GRAVITY_HOME", "GRAVITY_CORE_HOME", "GRAVITY_ARCHITECT_HOME", "GRAVITY_ARCHITECT_WORKSPACE"):
        env.pop(key, None)
    return env


def _write_atelier(
    root: Path,
    *,
    name: str = "Atelier Test",
    english: bool = False,
    with_code_audits: bool = True,
) -> None:
    for sub in ("specs/archive", "tasks/archive", "tracking/projects", "tracking/snapshots", "audits/code/nested", "audits/agents"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / "projects.json").write_text(json.dumps({
        "schema_version": 5,
        "workspace_name": name,
        "privacy": {"public_mode": False},
        "hot_budgets": {"ECOSYSTEM.md": 6000, "project_card_max_bytes": 3500},
        "watches": [{"id": "antigravity"}],
        "projects": [
            {"id": "gravity", "name": "Gravity Core", "path": "../gravity", "role": "Core plugin", "main_branch": "main", "default_dev_branch": "dev-next"},
            {"id": "gravity-metrics", "name": "Gravity Metrics", "path": "../gravity-metrics", "role": "Metrics", "main_branch": "main", "default_dev_branch": "dev"},
        ],
    }), encoding="utf-8", newline="\n")
    (root / "tracking/projects/gravity.md").write_text("# Gravity Core\n", encoding="utf-8", newline="\n")

    if english:
        (root / "ECOSYSTEM.md").write_text(
            "# Ecosystem\n\n<!-- AUTO:START:ecosystem-projects -->\n"
            "| Project | Main | Dev | Installed | WIP | Card |\n|---|---|---|---|---|---|\n"
            "| **Gravity** (`../gravity`) | `v0.3.0` | `0.3.0 (+2)` | `0.3.0` | `Clean` | [`gravity.md`](tracking/projects/gravity.md) |\n"
            "<!-- AUTO:END:ecosystem-projects -->\n\n### Hygiene alerts\n- No hygiene alerts.\n- `gravity` : WIP detected.\n",
            encoding="utf-8", newline="\n",
        )
        (root / "tracking/snapshots/delta.md").write_text(
            "# Delta\n\n- **Synced at:** `2026-11-26T10:00:00Z`\n- **Editorial status:** `NO_EDITORIAL_CHANGES`\n"
            "- **Watches:** `ok`\n- **LLM editorial targets:** `gravity, gravity-metrics`\n\n## Hygiene alerts\n- EN hygiene alert.\n",
            encoding="utf-8", newline="\n",
        )
        (root / "specs/2026-11-25-spec-en.md").write_text(
            "# Spec EN\n\n- **Date / Status:** `2026-11-25` — `validated`\n- **Target project:** `gravity`\n",
            encoding="utf-8", newline="\n",
        )
        (root / "tasks/2026-11-25-task-en.md").write_text(
            "# Task EN\n\n- **Status:** `in-progress`\n- **Target repository:** `gravity`\n- **Wave:** `3`\n"
            "- **Dependencies:** `2026-11-24-dep`\n- **Workflow profile:** `deep`\n"
            "- **Spec source:** `specs/2026-11-25-spec-en.md`\n- **Expected branch:** `refonte/socle`\n",
            encoding="utf-8", newline="\n",
        )
    else:
        (root / "ECOSYSTEM.md").write_text(
            "# Écosystème\n\n<!-- AUTO:START:ecosystem-projects -->\n"
            "| Projet | Base `main` | `dev` | Installé | WIP | Fiche |\n|---|---|---|---|---|---|\n"
            "| **Gravity** (`../gravity`) | `v0.3.0 (abc123)` | `0.3.0 (+2 vs main)` | `0.3.0 (aligné)` | `Propre` | [`gravity.md`](tracking/projects/gravity.md) |\n"
            "| **Metrics** (`../gravity-metrics`) | `v0.5.1` | `clean` | `0.5.1` | `Propre` | [`gravity-metrics.md`](tracking/projects/gravity-metrics.md) |\n"
            "<!-- AUTO:END:ecosystem-projects -->\n\n<!-- AUTO:START:ecosystem-hygiene -->\n"
            "- Aucune alerte d'hygiène.\n- `gravity` : WIP local détecté.\n<!-- AUTO:END:ecosystem-hygiene -->\n",
            encoding="utf-8", newline="\n",
        )
        (root / "tracking/snapshots/delta.md").write_text(
            "# Delta\n\n- **Date :** `2026-11-24T09:30:00Z`\n- **Statut éditorial :** `EDITORIAL_UPDATE_REQUIRED`\n"
            "- **Veilles :** `skipped`\n- **Cibles éditoriales LLM :** `gravity`\n\n## Alertes hygiène\n- Alerte delta FR.\n",
            encoding="utf-8", newline="\n",
        )
        (root / "specs/2026-11-23-dashboard.md").write_text(
            "# Dashboard Spec\n\n- **Date / Statut :** `2026-11-23` — `validated`\n- **Dépôt cible :** `gravity`\n",
            encoding="utf-8", newline="\n",
        )
        (root / "tasks/2026-11-23-lot2.md").write_text(
            "# Lot 2\n\n- **Date / Statut :** `2026-11-23` — `ready`\n- **Dépôt cible :** `gravity`\n- **Vague :** `2`\n"
            "- **Dépendances :** [`2026-11-23-lot1`](2026-11-23-lot1.md)\n- **Profil workflow :** `standard`\n"
            "- **Spec source :** [`specs/2026-11-23-dashboard.md`](../specs/2026-11-23-dashboard.md)\n- **Branche attendue :** `dev`\n",
            encoding="utf-8", newline="\n",
        )

    (root / "specs/archive/2026-11-01-old-spec.md").write_text("# Old Spec\n", encoding="utf-8", newline="\n")
    (root / "tasks/archive/2026-11-01-old-task.md").write_text("# Old Task\n", encoding="utf-8", newline="\n")
    (root / "audits/agents/2026-11-24-agent-secret.md").write_text("# Agent Secret\n\n- **Verdict :** `BLOQUANT`\n", encoding="utf-8", newline="\n")

    if with_code_audits:
        (root / "audits/code/README.md").write_text("# Code Audits Index\n\nIndex of technical code audits.\n", encoding="utf-8", newline="\n")
        (root / "audits/code/_TEMPLATE.md").write_text("# Template\n", encoding="utf-8", newline="\n")
        (root / "audits/code/2026-11-24-code-pass.md").write_text(
            "# Code Pass\n\n- **Cible :** `gravity`\n- **Verdict :** `PASS`\n\nAll invariants verified clean.\n",
            encoding="utf-8", newline="\n",
        )
        (root / "audits/code/nested/2026-11-22-code-warn.md").write_text(
            "# Code Warn\n\n- **Target :** `gravity`\n- **Conclusion :** `PARTIEL`\n\nMinor warning details found here.\n",
            encoding="utf-8", newline="\n",
        )


class TestDashboardProvider(unittest.TestCase):
    def test_absent_atelier_returns_unavailable_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            g_home = Path(tmp) / "gravity-home"
            res = dp.get_architect_view(gravity_home=g_home)
            self.assertFalse(res["available"])
            self.assertEqual(res["discovery_source"], "module_home")
            self.assertFalse(g_home.exists())

    def test_cli_json_since_signature_stdin_and_action_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            ws = Path(tmp) / "atelier"
            _write_atelier(ws)
            script = PLUGIN_ROOT / "scripts" / "dashboard_provider.py"
            proc = subprocess.run(
                [sys.executable, "-I", "-B", str(script), "--view", "architect", "--ws", str(ws), "--json"],
                input=json.dumps({"params": {}, "context": {}}),
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["available"])
            self.assertEqual(payload["discovery_source"], "ws_hint")
            sig = payload["signature"]

            proc_fast = subprocess.run(
                [sys.executable, "-I", "-B", str(script), "--view", "architect", "--ws", str(ws), "--since-signature", sig, "--json"],
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(proc_fast.returncode, 0)
            self.assertEqual(json.loads(proc_fast.stdout), {"changed": False, "unchanged": True, "signature": sig})

            # Verify stdin SPI-1 forwarding works in main()
            buf = io.StringIO()
            with mock.patch.object(sys, "stdin", io.StringIO(json.dumps({"params": {"ws": str(ws), "since_signature": sig}, "context": {}}))), mock.patch.object(sys, "stdout", buf):
                rc_stdin = dp.main(["--view", "architect", "--json"])
            self.assertEqual(rc_stdin, 0)
            self.assertEqual(json.loads(buf.getvalue()), {"changed": False, "unchanged": True, "signature": sig})

            # Verify unsupported --action fails closed with rc=1 and JSON error
            proc_act = subprocess.run(
                [sys.executable, "-I", "-B", str(script), "--action", "sync", "--json"],
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(proc_act.returncode, 1)
            act_json = json.loads(proc_act.stdout)
            self.assertFalse(act_json["ok"])
            self.assertIn("Unsupported action", act_json["error"])

    def test_discovery_precedence_and_blocked_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "g_home"
            arch_home = g_home / "architect"
            arch_home.mkdir(parents=True)
            a_arg, a_sel, a_env_ws, a_home_dir, a_env_home, a_ws, a_reg = [
                tmp_path / f"a_{k}" for k in ("arg", "sel", "env_ws", "home", "env_home", "ws", "reg")
            ]
            for d in (a_arg, a_sel, a_env_ws, a_home_dir, a_env_home, a_ws, a_reg):
                _write_atelier(d, name=d.name, with_code_audits=False)
            (arch_home / "ateliers.json").write_text(
                json.dumps({"schema_version": 1, "ateliers": [{"workspace_path": str(a_reg), "updated_at": "2026-11-24T10:00:00Z"}]}),
                encoding="utf-8",
            )

            self.assertEqual(dp.get_architect_view(architect_workspace=a_arg, atelier=str(a_sel), ws=str(a_ws), gravity_home=g_home)["discovery_source"], "arg_workspace")
            self.assertEqual(dp.get_architect_view(atelier=str(a_sel), ws=str(a_ws), gravity_home=g_home)["discovery_source"], "selected_atelier")
            with mock.patch.dict(os.environ, {"GRAVITY_ARCHITECT_WORKSPACE": str(a_env_ws)}):
                self.assertEqual(dp.get_architect_view(ws=str(a_ws), architect_home=a_home_dir, gravity_home=g_home)["discovery_source"], "env_workspace")
            self.assertEqual(dp.get_architect_view(ws=str(a_ws), architect_home=a_home_dir, gravity_home=g_home)["discovery_source"], "architect_home")
            with mock.patch.dict(os.environ, {"GRAVITY_ARCHITECT_HOME": str(a_env_home)}):
                self.assertEqual(dp.get_architect_view(ws=str(a_ws), gravity_home=g_home)["discovery_source"], "env_architect_home")
            self.assertEqual(dp.get_architect_view(ws=str(a_ws), gravity_home=g_home)["discovery_source"], "ws_hint")
            self.assertEqual(dp.get_architect_view(gravity_home=g_home)["discovery_source"], "architect_registry")

            invalid = dp.get_architect_view(atelier=str(tmp_path / "missing-atelier"), ws=str(a_ws), gravity_home=g_home)
            self.assertFalse(invalid["available"])
            self.assertEqual(invalid["discovery_source"], "selected_atelier")
            self.assertTrue(invalid["warnings"])

            sym_atelier = tmp_path / "sym-atelier"
            try:
                sym_atelier.symlink_to(a_ws, target_is_directory=True)
            except (OSError, NotImplementedError):
                return
            blocked_sym = dp.get_architect_view(atelier=str(sym_atelier), ws=str(a_ws), gravity_home=g_home)
            self.assertFalse(blocked_sym["available"])
            self.assertEqual(blocked_sym["discovery_source"], "selected_atelier")

    def test_corrupt_and_symlink_registry_resilience(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "g_home"
            arch_home = g_home / "architect"
            arch_home.mkdir(parents=True)
            a_ws = tmp_path / "atelier-ws"
            _write_atelier(a_ws, with_code_audits=False)
            reg_path = arch_home / "ateliers.json"

            reg_path.write_text("{broken", encoding="utf-8")
            res1 = dp.get_architect_view(ws=str(a_ws), gravity_home=g_home)
            self.assertTrue(res1["available"])
            self.assertTrue(any("ateliers.json" in w for w in res1["warnings"]))

            reg_path.write_text(json.dumps({"ateliers": "not-a-list"}), encoding="utf-8")
            res2 = dp.get_architect_view(ws=str(a_ws), gravity_home=g_home)
            self.assertTrue(any("ateliers" in w for w in res2["warnings"]))

            reg_path.unlink()
            real_reg = tmp_path / "real.json"
            real_reg.write_text(json.dumps({"ateliers": [{"workspace_path": str(a_ws)}]}), encoding="utf-8")
            try:
                reg_path.symlink_to(real_reg)
            except (OSError, NotImplementedError):
                return
            res3 = dp.get_architect_view(gravity_home=g_home)
            self.assertFalse(res3["available"])
            self.assertTrue(any("symlink" in w.lower() for w in res3["warnings"]))

    def test_bilingual_fr_en_parsing_and_strict_ro(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "g_home"
            ws_fr, ws_en = tmp_path / "ws_fr", tmp_path / "ws_en"
            _write_atelier(ws_fr, name="Atelier FR", english=False)
            _write_atelier(ws_en, name="Atelier EN", english=True)

            before_mtimes = {p: p.stat().st_mtime_ns for p in ws_fr.rglob("*") if p.is_file()}
            res_fr = dp.get_architect_view(ws=str(ws_fr), gravity_home=g_home)
            after_mtimes = {p: p.stat().st_mtime_ns for p in ws_fr.rglob("*") if p.is_file()}
            self.assertEqual(before_mtimes, after_mtimes)
            self.assertFalse(g_home.exists())

            self.assertEqual(res_fr["ecosystem"]["alerts"], ["gravity : WIP local détecté."])
            self.assertEqual(res_fr["delta"]["editorial_status"], "EDITORIAL_UPDATE_REQUIRED")
            self.assertEqual(res_fr["delta"]["editorial_targets"], ["gravity"])
            self.assertEqual(res_fr["delta"]["hygiene_alerts"], ["Alerte delta FR."])
            self.assertEqual(res_fr["projects"][0]["specs_count"], 1)
            self.assertEqual(res_fr["projects"][0]["tasks_count"], 1)
            self.assertEqual(res_fr["projects"][0]["audits_count"], 2)
            self.assertEqual(res_fr["tasks"][0]["wave"], 2)
            self.assertEqual(res_fr["tasks"][0]["dependencies"], ["2026-11-23-lot1"])
            self.assertEqual(res_fr["tasks"][0]["workflow_profile"], "standard")
            self.assertEqual(res_fr["tasks"][0]["expected_branch"], "dev")
            self.assertEqual(res_fr["waves_summary"]["waves_count"], 1)
            self.assertEqual(res_fr["archived_specs_count"], 1)
            self.assertEqual(res_fr["archived_tasks_count"], 1)
            self.assertIsNotNone(res_fr["index_audit"])
            self.assertEqual([a["verdict"] for a in res_fr["audits"]], ["PASS", "PARTIEL"])
            self.assertEqual([a["verdict_tone"] for a in res_fr["audits"]], ["ok", "warn"])

            res_en = dp.get_architect_view(ws=str(ws_en), gravity_home=g_home)
            self.assertEqual(res_en["ecosystem"]["alerts"], ["gravity : WIP detected."])
            self.assertEqual(res_en["delta"]["date"], "2026-11-26T10:00:00Z")
            self.assertEqual(res_en["delta"]["editorial_status"], "NO_EDITORIAL_CHANGES")
            self.assertEqual(res_en["delta"]["watches_status"], "ok")
            self.assertEqual(res_en["delta"]["editorial_targets"], ["gravity", "gravity-metrics"])
            self.assertEqual(res_en["delta"]["hygiene_alerts"], ["EN hygiene alert."])
            self.assertEqual(res_en["specs"][0]["status_code"], "validated")
            self.assertEqual(res_en["tasks"][0]["status_code"], "in_progress")
            self.assertEqual(res_en["tasks"][0]["wave"], 3)
            self.assertEqual(res_en["tasks"][0]["workflow_profile"], "deep")
            self.assertEqual(res_en["tasks"][0]["expected_branch"], "refonte/socle")

    def test_audits_agents_and_symlink_junction_exclusion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            ws = tmp_path / "ws"
            _write_atelier(ws)
            nested_agents = ws / "audits/code/agents"
            nested_agents.mkdir(parents=True)
            (nested_agents / "2026-11-25-leaked.md").write_text("# Leaked\n\n- **Verdict :** `BLOQUANT`\n", encoding="utf-8")

            outside = tmp_path / "outside.md"
            outside.write_text("# Outside\n\n- **Verdict :** `BLOQUANT`\n", encoding="utf-8")
            try:
                (ws / "audits/code/2026-11-25-sym.md").symlink_to(outside)
            except (OSError, NotImplementedError):
                pass

            res = dp.get_architect_view(ws=str(ws), gravity_home=tmp_path / "gh")
            rels = [a["rel_path"] for a in res["audits"]]
            self.assertNotIn("agents/2026-11-25-leaked.md", rels)
            self.assertNotIn("2026-11-25-sym.md", rels)
            self.assertEqual(len(rels), 2)

            # Simulated Windows NTFS junction via path_safety guard
            with mock.patch.object(dp, "ensure_no_symlink_or_junction_under", side_effect=ValueError("Refusing junction")):
                res_junc = dp.get_architect_view(ws=str(ws), gravity_home=tmp_path / "gh")
                self.assertEqual(res_junc["audits"], [])

    def test_legacy_handoffs_fallback_and_tasks_priority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            ws = Path(tmp) / "legacy"
            (ws / "handoffs/archive").mkdir(parents=True)
            (ws / "ECOSYSTEM.md").write_text("# Legacy\n", encoding="utf-8")
            (ws / "projects.json").write_text(json.dumps({"schema_version": 5, "projects": []}), encoding="utf-8")
            (ws / "handoffs/2026-11-20-old.md").write_text("# Old\n\n- **Statut :** `ready`\n", encoding="utf-8")
            (ws / "handoffs/archive/2026-11-01-arch.md").write_text("# Arch\n", encoding="utf-8")

            res_leg = dp.get_architect_view(ws=str(ws), gravity_home=Path(tmp) / "gh")
            self.assertEqual([t["filename"] for t in res_leg["tasks"]], ["2026-11-20-old.md"])
            self.assertEqual(res_leg["archived_tasks_count"], 1)

            (ws / "tasks").mkdir()
            res_empty = dp.get_architect_view(ws=str(ws), gravity_home=Path(tmp) / "gh")
            self.assertEqual(res_empty["tasks"], [])
            self.assertEqual(res_empty["archived_tasks_count"], 0)

    def test_payload_budget_truncation(self) -> None:
        payload = {
            "truncated": False,
            "audits": [{"id": i, "body": "x" * 200} for i in range(40)],
            "tasks": [{"id": i, "body": "y" * 200} for i in range(40)],
            "specs": [], "projects": [], "ateliers": [],
        }
        bounded = dp._enforce_payload_budget(payload, ("audits", "tasks", "specs", "projects", "ateliers"), max_bytes=3000)
        self.assertTrue(bounded["truncated"])
        self.assertLess(len(json.dumps(bounded, ensure_ascii=False).encode("utf-8")), 3000)

    def test_structural_budgets_stdlib_and_module_contract(self) -> None:
        script = PLUGIN_ROOT / "scripts" / "dashboard_provider.py"
        raw = script.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r\n", raw)
        lines = raw.decode("utf-8").splitlines()
        self.assertLess(len(lines), 550, f"dashboard_provider.py must be < 550 lines (got {len(lines)})")
        if os.name != "nt":
            self.assertTrue(os.access(script, os.X_OK))

        rep = validator_core.Report()
        validator_core.check_stdlib_only(script, rep, allowed_local_modules=architect_validate.ARCHITECT_ALLOWED_MODULES)
        mod = validator_core.validate_module_contract(PLUGIN_ROOT, rep, expected_plugin_name="gravity-architect", expected_module_id="architect")
        self.assertTrue(rep.ok(strict=True), f"Errors: {rep.errors}, Warnings: {rep.warnings}")
        self.assertIsNotNone(mod)
        self.assertEqual(mod["dashboard"], {"provider_script": "scripts/dashboard_provider.py", "views": ["architect"], "actions": []})
        self.assertEqual(mod["capture_policy"], {
            "commands": ["/gravity-architect"],
            "exclude_subcommands": ["init", "add", "sync", "status", "archive", "audit"],
            "consultative_bypass": True,
            "label_prefix": "architect",
        })


if __name__ == "__main__":
    unittest.main()
