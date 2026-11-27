#!/usr/bin/env python3
"""Tests isolés pour atelier_status.py et détection AUD-05-09 (100 % stdlib)."""

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


class TestAtelierStatus(unittest.TestCase):
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
            self.assertEqual(payload["projects"], [])
            self.assertNotIn("bridge", payload)
            self.assertFalse((fake_home / ".gemini").exists())
            self.assertEqual(list(empty_ws.iterdir()), [])
            cmds = [a["command"] for a in payload["suggested_actions"]]
            self.assertIn("/gravity-architect init", cmds)

            md = atelier_status.format_status_markdown(payload)
            self.assertIn("non initialisé", md)
            self.assertNotIn("Projets suivis", md)
            self.assertIn("/gravity-architect init", md)
            self.assertNotIn("bridge", md.lower())

    def test_atelier_status_initialized_specs_tasks_and_hygiene(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = root / "atelier"
            arch_home = root / "arch-home"

            with mock.patch.dict(os.environ, {"GRAVITY_ARCHITECT_HOME": str(arch_home), "GRAVITY_ARCHITECT_SKIP_REGISTRY": "1"}):
                init_workspace.init_workspace(ws, name="Atelier Test", preset="generic")

            reg_file = arch_home / "ateliers.json"
            self.assertFalse(reg_file.exists())

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
            (ws / "tasks").mkdir(parents=True, exist_ok=True)
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
            self.assertNotIn("AUD-05-09", joined_alerts)

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

            (ws / "projects.json").write_text("{invalid-json", encoding="utf-8")
            bad_payload = atelier_status.collect_atelier_status(
                workspace_arg=ws,
                env={},
                home_dir=root / "fake-home",
            )
            self.assertFalse(bad_payload["initialized"])
            self.assertNotIn("bridge", bad_payload)
            self.assertIn("JSON invalide", "\n".join(bad_payload["hygiene_alerts"]))

    def test_aud_05_09_stale_ready_tasks_positive_and_zero_false_positives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = root / "atelier"
            repo_alpha = root / "alpha"
            (repo_alpha / "src").mkdir(parents=True)
            (repo_alpha / "CHANGELOG.md").write_text(
                "# Changelog\n\n## [Unreleased]\n- **[TASK-ALPHA-02]** Delivered feature.\n- **[TASK-ALPHA-010]** Other task.\n",
                encoding="utf-8",
            )
            (repo_alpha / "src" / "created_mod.py").write_text("def run():\n    pass\n", encoding="utf-8")
            (repo_alpha / "src" / "existing_mod.py").write_text("def edit():\n    pass\n", encoding="utf-8")

            for sub in ("specs", "specs/archive", "tasks", "tasks/archive", "tracking/snapshots"):
                (ws / sub).mkdir(parents=True, exist_ok=True)
            (ws / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
            (ws / "ECOSYSTEM.md").write_text("# Ecosystem\n", encoding="utf-8")
            (ws / "tracking" / "snapshots" / "ecosystem_snapshot.md").write_text("# Snap\n", encoding="utf-8")
            (ws / "projects.json").write_text(
                json.dumps({"schema_version": 6, "projects": [{"id": "alpha", "path": "../alpha"}]}),
                encoding="utf-8",
            )

            (ws / "specs" / "2026-11-26-spec-ok.md").write_text(
                "# Spec OK\n- **Spec ID :** `SPEC-OK`\n- **Statut :** `validated`\n",
                encoding="utf-8",
            )
            (ws / "specs" / "2026-11-26-spec-superseded.md").write_text(
                "# Spec Old\n- **Spec ID :** `SPEC-SUP`\n- **Statut :** `superseded`\n",
                encoding="utf-8",
            )
            (ws / "specs" / "archive" / "2026-11-26-spec-arch.md").write_text(
                "# Spec Arch\n- **Spec ID :** `SPEC-ARCH`\n- **Statut :** `validated`\n",
                encoding="utf-8",
            )

            # Positive 1: ready task pointing to archived spec
            (ws / "tasks" / "2026-11-26-t1-archived-spec.md").write_text(
                "# T1\n- **Task ID :** `TASK-ALPHA-01`\n- **Spec ID :** `SPEC-ARCH`\n"
                "- **Spec source :** `specs/archive/2026-11-26-spec-arch.md`\n"
                "- **Date / Statut :** `2026-11-26` — `ready`\n- **Vague :** `1`\n- **Dépôt cible :** `alpha`\n",
                encoding="utf-8",
            )
            # Positive 2: ready task already in CHANGELOG.md + superseded spec
            (ws / "tasks" / "2026-11-26-t2-delivered-changelog.md").write_text(
                "# T2\n- **Task ID :** `TASK-ALPHA-02`\n- **Spec ID :** `SPEC-SUP`\n"
                "- **Spec source :** `specs/2026-11-26-spec-superseded.md`\n"
                "- **Date / Statut :** `2026-11-26` — `ready`\n- **Vague :** `2`\n- **Dépôt cible :** `alpha`\n",
                encoding="utf-8",
            )
            # Positive 3: ready task with new file anchors already created on disk
            (ws / "tasks" / "2026-11-26-t3-newfile-exists.md").write_text(
                "# T3\n- **Task ID :** `TASK-ALPHA-03`\n- **Spec ID :** `SPEC-OK`\n"
                "- **Spec source :** `specs/2026-11-26-spec-ok.md`\n"
                "- **Date / Statut :** `2026-11-26` — `ready`\n- **Vague :** `3`\n- **Dépôt cible :** `alpha`\n\n"
                "## Ancres exactes\n- `src/created_mod.py::run (~L1-L5)` — *new file : créé*\n",
                encoding="utf-8",
            )
            # Negative 1 (zero FP): active ready task (TASK-ALPHA-01 not confused with TASK-ALPHA-010, new file not on disk)
            (ws / "tasks" / "2026-11-26-t4-clean-ready.md").write_text(
                "# T4\n- **Task ID :** `TASK-ALPHA-01`\n- **Spec ID :** `SPEC-OK`\n"
                "- **Spec source :** `specs/2026-11-26-spec-ok.md`\n"
                "- **Date / Statut :** `2026-11-26` — `ready`\n- **Vague :** `4`\n- **Dépôt cible :** `alpha`\n\n"
                "## Ancres exactes\n"
                "- `src/existing_mod.py::edit (~L1-L5)` — *modification*\n"
                "- `src/future_new_mod.py::create (~L1-L5)` — *new file : à créer*\n",
                encoding="utf-8",
            )
            # Negative 2 (zero FP): non-ready status (in_progress) with missing spec is ignored
            (ws / "tasks" / "2026-11-26-t5-in-progress.md").write_text(
                "# T5\n- **Task ID :** `TASK-ALPHA-02`\n- **Spec source :** `specs/missing.md`\n"
                "- **Date / Statut :** `2026-11-26` — `in_progress`\n- **Vague :** `5`\n- **Dépôt cible :** `alpha`\n",
                encoding="utf-8",
            )

            payload = atelier_status.collect_atelier_status(workspace_arg=ws, env={}, home_dir=root / "fh")
            aud_alerts = [a for a in payload["hygiene_alerts"] if a.startswith("AUD-05-09:")]
            joined = "\n".join(aud_alerts)

            self.assertIn("2026-11-26-t1-archived-spec", joined)
            self.assertIn("spec archivée", joined)
            self.assertIn("2026-11-26-t2-delivered-changelog", joined)
            self.assertIn("spec superseded", joined)
            self.assertIn("alpha/CHANGELOG.md", joined)
            self.assertIn("2026-11-26-t3-newfile-exists", joined)
            self.assertIn("ancres nouveau fichier déjà présentes", joined)

            self.assertNotIn("2026-11-26-t4-clean-ready", joined)
            self.assertNotIn("2026-11-26-t5-in-progress", joined)

    def test_templates_parity_zero_drift_alerts(self) -> None:
        from core.delta import collect_atelier_hygiene_alerts

        tpl_dir = PLUGIN_ROOT / "templates"
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ws"
            for rel, tpl_name in (
                ("specs/_TEMPLATE.md", "spec-template.md"),
                ("tasks/_TEMPLATE.md", "task-template.md"),
                ("audits/code/_TEMPLATE.md", "audit-code-template.md"),
                ("tracking/projects/_TEMPLATE.md", "project-card-template.md"),
            ):
                dst = ws / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes((tpl_dir / tpl_name).read_bytes())
            alerts = collect_atelier_hygiene_alerts(ws, templates_dir=tpl_dir)
            self.assertEqual(alerts, [])

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
                json.dumps({"lastUserInput": "/gravity-architect frame new feature"}),
                json.dumps({"lastUserInput": "/gravity"}),
                json.dumps({"lastUserInput": "Hello Architect"}),
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

    def test_atelier_status_projects_list_and_compact_pre_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = root / "atelier"
            r1 = root / "svc-one"
            r2 = root / "svc-two"
            r1.mkdir()
            r2.mkdir()
            fake_home = root / "home"
            fake_home.mkdir()
            arch_home = root / "arch-home"

            with mock.patch.dict(
                os.environ,
                {"GRAVITY_ARCHITECT_HOME": str(arch_home), "GRAVITY_ARCHITECT_SKIP_REGISTRY": "1"},
            ):
                init_workspace.init_workspace(
                    ws,
                    name="Atelier Projects",
                    projects=[("svc-one", "Service 1", r1), ("svc-two", "Service 2", r2)],
                )

            payload = atelier_status.collect_atelier_status(
                workspace_arg=ws,
                env={},
                home_dir=fake_home,
            )
            self.assertTrue(payload["initialized"])
            self.assertEqual(payload["projects_count"], 2)
            self.assertEqual(payload["projects"], ["svc-one", "svc-two"])

            md = atelier_status.format_status_markdown(payload)
            self.assertIn("- **Projets suivis (2) :** `svc-one`, `svc-two`", md)

            proc = _run_hook(
                json.dumps({"lastUserInput": "/gravity-architect"}),
                cwd=ws,
                fake_home=fake_home,
                arch_home=arch_home,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            self.assertTrue(proc.stdout.isascii())
            out = json.loads(proc.stdout.strip())
            self.assertEqual(out.get("terminationBehavior"), "terminate")
            hook_md = (out["injectSteps"][0].get("systemMessage") or {}).get("metadata", {}).get("user_markdown") or ""
            self.assertIn("svc-one", hook_md)
            self.assertIn("svc-two", hook_md)
            self.assertLessEqual(len(hook_md.splitlines()), 25)
            self.assertFalse((arch_home / "ateliers.json").exists())

            many_projects = [f"svc-{i:02d}" for i in range(12)]
            compact_md = atelier_status.format_status_markdown(
                {
                    "initialized": True,
                    "workspace_name": "Atelier Large",
                    "workspace": str(ws),
                    "projects_count": 12,
                    "projects": many_projects,
                    "specs": [],
                    "pending_tasks": [],
                    "tasks_by_wave": {},
                    "hygiene_alerts": [],
                    "suggested_actions": [],
                }
            )
            self.assertIn("- **Projets suivis (12) :**", compact_md)
            self.assertIn("`svc-00`", compact_md)
            self.assertIn("`svc-09`", compact_md)
            self.assertNotIn("`svc-10`", compact_md)
            self.assertIn("*(+2 autre(s))*", compact_md)


if __name__ == "__main__":
    unittest.main()
