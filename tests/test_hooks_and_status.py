#!/usr/bin/env python3
"""Tests isolés pour atelier_status.py et le hook PreInvocation pre_invocation_architect.py."""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
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


def _create_bridge_db(db_path: Path, *, open_threads: int = 2, closed_threads: int = 1, active_jobs: int = 3, done_jobs: int = 2) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, status TEXT)")
        conn.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, status TEXT)")
        for i in range(open_threads):
            conn.execute("INSERT INTO threads (id, status) VALUES (?, 'open')", (f"t-open-{i}",))
        for i in range(closed_threads):
            conn.execute("INSERT INTO threads (id, status) VALUES (?, 'done')", (f"t-done-{i}",))
        statuses = ["queued", "claimed", "dispatched"]
        for i in range(active_jobs):
            conn.execute("INSERT INTO jobs (id, status) VALUES (?, ?)", (f"j-act-{i}", statuses[i % len(statuses)]))
        for i in range(done_jobs):
            conn.execute("INSERT INTO jobs (id, status) VALUES (?, 'completed')", (f"j-done-{i}",))
        conn.commit()
    finally:
        conn.close()


def _run_hook(
    stdin_text: str,
    *,
    cwd: Path,
    fake_home: Path,
    arch_home: Path,
    bridge_home: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["HOME"] = str(fake_home)
    env["USERPROFILE"] = str(fake_home)
    env["GRAVITY_HOME"] = str(fake_home / ".gemini" / "gravity")
    env["GRAVITY_ARCHITECT_HOME"] = str(arch_home)
    env["GRAVITY_BRIDGE_HOME"] = str(bridge_home)
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
    def test_atelier_status_uninitialized_and_no_bridge_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            empty_ws = root / "empty-dir"
            empty_ws.mkdir()
            fake_home = root / "home"
            fake_home.mkdir()
            missing_bridge = root / "bridge" / "bridge.db"

            payload = atelier_status.collect_atelier_status(
                workspace_arg=empty_ws,
                cwd=empty_ws,
                env={"GRAVITY_BRIDGE_HOME": str(missing_bridge.parent)},
                home_dir=fake_home,
            )
            self.assertFalse(payload["initialized"])
            self.assertFalse(payload["bridge"]["available"])
            self.assertEqual(payload["bridge"]["open_threads"], 0)
            self.assertEqual(payload["bridge"]["active_jobs"], 0)
            self.assertFalse(missing_bridge.exists())
            self.assertFalse((fake_home / ".gemini").exists())
            self.assertEqual(list(empty_ws.iterdir()), [])
            cmds = [a["command"] for a in payload["suggested_actions"]]
            self.assertIn("/gravity-architect init", cmds)

            md = atelier_status.format_status_markdown(payload)
            self.assertIn("non initialisé", md)
            self.assertIn("/gravity-architect init", md)

    def test_atelier_status_initialized_specs_tasks_bridge_ro_and_hygiene(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = root / "atelier"
            arch_home = root / "arch-home"
            bridge_dir = root / "bridge-home"
            bridge_db = bridge_dir / "bridge.db"
            _create_bridge_db(bridge_db, open_threads=2, closed_threads=1, active_jobs=3, done_jobs=4)

            with mock.patch.dict(os.environ, {"GRAVITY_ARCHITECT_HOME": str(arch_home), "GRAVITY_ARCHITECT_SKIP_REGISTRY": "1"}):
                init_workspace.init_workspace(ws, name="Atelier Test", preset="generic")

            # Retire ateliers.json s'il existait et vérifie qu'atelier_status n'écrit rien
            reg_file = arch_home / "ateliers.json"
            self.assertFalse(reg_file.exists())

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

            db_mtime_before = bridge_db.stat().st_mtime_ns
            payload = atelier_status.collect_atelier_status(
                workspace_arg=ws,
                env={"GRAVITY_BRIDGE_HOME": str(bridge_dir)},
                home_dir=root / "fake-home",
            )
            self.assertTrue(payload["initialized"])
            self.assertEqual(payload["workspace_name"], "Atelier Test")
            self.assertEqual(len(payload["specs"]), 1)
            self.assertEqual(len(payload["pending_tasks"]), 3)
            self.assertEqual(payload["tasks_by_wave"]["Vague 1"], {"ready": 1})
            self.assertEqual(payload["tasks_by_wave"]["Vague 2"], {"in_progress": 1})
            self.assertEqual(payload["tasks_by_wave"]["Sans vague"], {"draft": 1})
            self.assertTrue(payload["bridge"]["available"])
            self.assertEqual(payload["bridge"]["open_threads"], 2)
            self.assertEqual(payload["bridge"]["active_jobs"], 3)
            self.assertEqual(bridge_db.stat().st_mtime_ns, db_mtime_before)
            self.assertFalse(reg_file.exists())

            joined_alerts = "\n".join(payload["hygiene_alerts"])
            self.assertIn("specs/_TEMPLATE.md", joined_alerts)
            self.assertIn("missing/doc.md", joined_alerts)

            actions = [a["action"] for a in payload["suggested_actions"]]
            self.assertIn("reprendre", actions)
            self.assertIn("sync", actions)

            out_buf = io.StringIO()
            with mock.patch.dict(os.environ, {"GRAVITY_BRIDGE_HOME": str(bridge_dir)}), contextlib.redirect_stdout(out_buf):
                rc = atelier_status.main(["--workspace", str(ws), "--json"])
            self.assertEqual(rc, 0)
            cli_data = json.loads(out_buf.getvalue())
            self.assertEqual(cli_data["bridge"]["active_jobs"], 3)

            # Rejet symlink sur bridge.db
            sym_dir = root / "sym-bridge"
            sym_dir.mkdir()
            sym_db = sym_dir / "bridge.db"
            try:
                sym_db.symlink_to(bridge_db)
            except OSError:
                pass
            else:
                sym_probe = atelier_status.probe_bridge_ro(bridge_db=sym_db)
                self.assertFalse(sym_probe["available"])
                self.assertIn("symbolique", sym_probe["error"] or "")

    def test_pre_invocation_architect_hook_bare_vs_passthrough(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = root / "atelier"
            fake_home = root / "home"
            fake_home.mkdir()
            arch_home = root / "arch-home"
            bridge_home = root / "bridge-home"
            _create_bridge_db(bridge_home / "bridge.db", open_threads=1, active_jobs=2)

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
                    bridge_home=bridge_home,
                )
                self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
                self.assertTrue(proc.stdout.isascii(), msg=f"Output must be ASCII-safe: {proc.stdout!r}")
                out = json.loads(proc.stdout.strip())
                self.assertEqual(out.get("terminationBehavior"), "terminate")
                steps = out.get("injectSteps") or []
                self.assertEqual(len(steps), 1)
                md = (steps[0].get("systemMessage") or {}).get("metadata", {}).get("user_markdown") or ""
                self.assertIn("Atelier Hook", md)
                self.assertIn("1` thread(s) ouvert(s), `2` job(s) actif(s)", md)
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
                    bridge_home=bridge_home,
                )
                self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
                self.assertEqual(json.loads(proc.stdout.strip()), {})
                self.assertFalse(reg_path.exists())


if __name__ == "__main__":
    unittest.main()
