#!/usr/bin/env python3
"""Tests isolés pour atelier_status.py et le hook PreInvocation pre_invocation_architect.py."""

from __future__ import annotations

import contextlib
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
HOOK_SCRIPT = PLUGIN_ROOT / "hooks" / "pre_invocation_architect.py"
sys.path.insert(0, str(PLUGIN_ROOT))
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

import atelier_status  # noqa: E402
import init_workspace  # noqa: E402


def _run_hook(
    stdin_text: str,
    *,
    cwd: Path,
    fake_home: Path,
    arch_home: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["HOME"] = str(fake_home)
    env["USERPROFILE"] = str(fake_home)
    env["GRAVITY_HOME"] = str(fake_home / ".gemini" / "gravity")
    env["GRAVITY_ARCHITECT_HOME"] = str(arch_home)
    env.pop("GRAVITY_ARCHITECT_WORKSPACE", None)
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        [sys.executable, "-B", str(HOOK_SCRIPT)],
        input=stdin_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd),
        env=env,
        timeout=15,
        check=False,
    )


class TestAtelierStatusAndHook(unittest.TestCase):
    def test_atelier_status_uninitialized_zero_writes(self) -> None:
        self.assertFalse(hasattr(atelier_status, "resolve_bridge_db_path"))
        self.assertFalse(hasattr(atelier_status, "probe_bridge_ro"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            empty_ws = root / "empty-dir"
            empty_ws.mkdir()
            fake_home = root / "home"
            fake_home.mkdir()

            payload = atelier_status.collect_atelier_status(
                workspace_arg=empty_ws,
                cwd=empty_ws,
                env={},
                home_dir=fake_home,
            )
            self.assertFalse(payload["initialized"])
            self.assertNotIn("bridge", payload)
            self.assertFalse((fake_home / ".gemini").exists())
            self.assertEqual(list(empty_ws.iterdir()), [])
            cmds = [a["command"] for a in payload["suggested_actions"]]
            self.assertIn("/gravity-architect init", cmds)

            md = atelier_status.format_status_markdown(payload)
            self.assertIn("non initialisé", md)
            self.assertIn("/gravity-architect init", md)
            self.assertNotIn("bridge", md.lower())

    def test_atelier_status_initialized_specs_tasks_and_hygiene(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = root / "atelier"
            arch_home = root / "arch-home"

            with mock.patch.dict(os.environ, {"GRAVITY_ARCHITECT_HOME": str(arch_home), "GRAVITY_ARCHITECT_SKIP_REGISTRY": "1"}):
                init_workspace.init_workspace(ws, name="Atelier Test", preset="generic")

            # Retire ateliers.json s'il existait et vérifie qu'atelier_status n'écrit rien
            reg_file = arch_home / "ateliers.json"
            self.assertFalse(reg_file.exists())

            # Atelier vierge sans specs/tasks -> pas d'action 'reprendre' ni alerte si snapshot présent
            snap_dir = ws / "tracking" / "snapshots"
            snap_dir.mkdir(parents=True, exist_ok=True)
            (snap_dir / "ecosystem_snapshot.md").write_text("# Snapshot\n", encoding="utf-8")
            clean_payload = atelier_status.collect_atelier_status(
                workspace_arg=ws,
                env={},
                home_dir=root / "fake-home",
            )
            self.assertTrue(clean_payload["initialized"])
            self.assertNotIn("bridge", clean_payload)
            self.assertNotIn("reprendre", [a["action"] for a in clean_payload["suggested_actions"]])
            clean_md = atelier_status.format_status_markdown(clean_payload)
            self.assertIn("**Hygiène :** aucune alerte", clean_md)
            self.assertNotIn("bridge", clean_md.lower())

            (ws / "specs" / "2026-11-24-demo-spec.md").write_text(
                "# Spec Demo\n- **Statut :** `validated`\n- **Projets impactés :** `alpha`\n",
                encoding="utf-8",
            )
            (ws / "tasks" / "2026-11-24-alpha-lot1.md").write_text(
                "# Lot 1\n- **Vague :** `1`\n- **Dépôt cible :** `alpha`\n- **Date / Statut :** `2026-11-24` — `ready`\n",
                encoding="utf-8",
            )
            (ws / "tasks" / "2026-11-24-beta-lot2.md").write_text(
                "# Lot 2\n- **Vague :** `2`\n- **Dépôt cible :** `beta`\n- **Date / Statut :** `2026-11-24` — `in_progress`\n",
                encoding="utf-8",
            )
            (ws / "tasks" / "2026-11-24-alpha-nowave.md").write_text(
                "# Lot 0\n- **Dépôt cible :** `alpha`\n- **Date / Statut :** `2026-11-24` — `draft`\n",
                encoding="utf-8",
            )
            # Déclenche une dérive template et un lien cassé
            (ws / "specs" / "_TEMPLATE.md").write_text("# Template modifié\n", encoding="utf-8")
            (ws / "ECOSYSTEM.md").write_text(
                (ws / "ECOSYSTEM.md").read_text(encoding="utf-8") + "\n- [Lien cassé](missing/doc.md)\n",
                encoding="utf-8",
            )

            payload = atelier_status.collect_atelier_status(
                workspace_arg=ws,
                env={},
                home_dir=root / "fake-home",
            )
            self.assertTrue(payload["initialized"])
            self.assertEqual(payload["workspace_name"], "Atelier Test")
            self.assertEqual(len(payload["specs"]), 1)
            self.assertEqual(len(payload["pending_tasks"]), 3)
            self.assertEqual(payload["tasks_by_wave"]["Vague 1"], {"ready": 1})
            self.assertEqual(payload["tasks_by_wave"]["Vague 2"], {"in_progress": 1})
            self.assertEqual(payload["tasks_by_wave"]["Sans vague"], {"draft": 1})
            self.assertNotIn("bridge", payload)
            self.assertNotIn("bridge", json.dumps(payload, ensure_ascii=False).lower())
            self.assertFalse(reg_file.exists())

            joined_alerts = "\n".join(payload["hygiene_alerts"])
            self.assertIn("specs/_TEMPLATE.md", joined_alerts)
            self.assertIn("missing/doc.md", joined_alerts)

            actions = [a["action"] for a in payload["suggested_actions"]]
            self.assertIn("reprendre", actions)
            self.assertIn("sync", actions)

            md = atelier_status.format_status_markdown(payload)
            self.assertIn("Atelier Test", md)
            self.assertIn("**Vague 1**", md)
            self.assertIn("## Alertes hygiène", md)
            self.assertNotIn("bridge", md.lower())

            out_buf = io.StringIO()
            with contextlib.redirect_stdout(out_buf):
                rc = atelier_status.main(["--workspace", str(ws), "--json"])
            self.assertEqual(rc, 0)
            cli_data = json.loads(out_buf.getvalue())
            self.assertNotIn("bridge", cli_data)
            self.assertEqual(cli_data["tasks_by_wave"]["Vague 1"], {"ready": 1})

            # projects.json corrompu -> initialized=False sans clé bridge
            (ws / "projects.json").write_text("{invalid-json", encoding="utf-8")
            bad_payload = atelier_status.collect_atelier_status(
                workspace_arg=ws,
                env={},
                home_dir=root / "fake-home",
            )
            self.assertFalse(bad_payload["initialized"])
            self.assertNotIn("bridge", bad_payload)
            self.assertIn("JSON invalide", "\n".join(bad_payload["hygiene_alerts"]))

    def test_pre_invocation_architect_hook_bare_vs_passthrough(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = root / "atelier"
            fake_home = root / "home"
            fake_home.mkdir()
            arch_home = root / "arch-home"

            with mock.patch.dict(os.environ, {"GRAVITY_ARCHITECT_HOME": str(arch_home), "GRAVITY_ARCHITECT_SKIP_REGISTRY": "1"}):
                init_workspace.init_workspace(ws, name="Atelier Hook")

            reg_path = arch_home / "ateliers.json"
            self.assertFalse(reg_path.exists())

            bare_cases = [
                {"lastUserInput": "/gravity-architect"},
                {"lastUserInput": "/gravity-architect:gravity-architect", "invocationNum": 0},
                {
                    "userInput": (
                        "<USER_REQUEST>\n/GRAVITY-ARCHITECT\n</USER_REQUEST>\n"
                        "<ADDITIONAL_METADATA>time=now</ADDITIONAL_METADATA>\n"
                        "<USER_SETTINGS_CHANGE>off</USER_SETTINGS_CHANGE>"
                    ),
                    "invocationNum": None,
                },
                {"prompt": "  /gravity-architect:gravity-architect  "},
            ]
            for payload in bare_cases:
                proc = _run_hook(
                    json.dumps(payload),
                    cwd=ws,
                    fake_home=fake_home,
                    arch_home=arch_home,
                )
                self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
                self.assertTrue(proc.stdout.isascii(), msg=f"Output must be ASCII-safe: {proc.stdout!r}")
                out = json.loads(proc.stdout.strip())
                self.assertEqual(out.get("terminationBehavior"), "terminate")
                steps = out.get("injectSteps") or []
                self.assertEqual(len(steps), 1)
                md = (steps[0].get("systemMessage") or {}).get("metadata", {}).get("user_markdown") or ""
                self.assertIn("Atelier Hook", md)
                self.assertIn("Specs actives", md)
                self.assertIn("Tasks actives", md)
                self.assertNotIn("bridge", md.lower())
                self.assertFalse(reg_path.exists())

            passthrough_inputs = [
                "",
                "{not-json",
                "[]",
                json.dumps({"lastUserInput": "/gravity-architect", "invocationNum": 1}),
                json.dumps({"lastUserInput": "/gravity-architect", "invocationNum": True}),
                json.dumps({"lastUserInput": "/gravity-architect", "invocationNum": False}),
                json.dumps({"lastUserInput": "/gravity-architect sync"}),
                json.dumps({"lastUserInput": "/gravity-architect init"}),
                json.dumps({"lastUserInput": "/gravity-architect cadrer nouvelle feature"}),
                json.dumps({"lastUserInput": "/gravity"}),
                json.dumps({"lastUserInput": "Bonjour Architect"}),
            ]
            for raw in passthrough_inputs:
                proc = _run_hook(
                    raw,
                    cwd=ws,
                    fake_home=fake_home,
                    arch_home=arch_home,
                )
                self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
                self.assertEqual(json.loads(proc.stdout.strip()), {})
                self.assertFalse(reg_path.exists())


if __name__ == "__main__":
    unittest.main()
