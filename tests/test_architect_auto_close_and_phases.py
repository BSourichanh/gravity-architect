#!/usr/bin/env python3
"""Tests unitaires pour l'auto-clôture gravity-metrics et cycle_phases RO (100 % stdlib)."""

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
sys.path.insert(0, str(PLUGIN_ROOT))
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

import dashboard_provider as dp  # noqa: E402
import init_workspace  # noqa: E402
import sync_tracking  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", check=True)
    return proc.stdout


def _make_clean_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("# Demo\n", encoding="utf-8", newline="\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init")
    _git(repo, "checkout", "-b", "dev")


def _install_metrics_stub(gemini_home: Path, log_path: Path, *, rc: int = 0) -> Path:
    cli = gemini_home / "config" / "plugins" / "gravity-metrics" / "scripts" / "cli.py"
    cli.parent.mkdir(parents=True, exist_ok=True)
    cli.write_text(
        f"import json, sys\nfrom pathlib import Path\n"
        f"Path({str(log_path)!r}).write_text(json.dumps({{'argv': sys.argv[1:]}}), encoding='utf-8')\n"
        f"if {rc} != 0:\n    sys.stderr.write('stub failure\\n')\n"
        f"raise SystemExit({rc})\n",
        encoding="utf-8",
        newline="\n",
    )
    return cli


class TestArchitectAutoCloseAndPhases(unittest.TestCase):
    def test_ack_editorial_clean_wip_triggers_metrics_and_update_sealed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws, repo, g_home = root / "atelier", root / "demo", root / ".gemini"
            arch_home = root / "arch-home"
            _make_clean_repo(repo)
            log_path = root / "metrics_call.json"
            _install_metrics_stub(g_home, log_path)

            with mock.patch.dict(os.environ, {"GRAVITY_ARCHITECT_HOME": str(arch_home), "GRAVITY_ARCHITECT_SKIP_REGISTRY": "1"}):
                init_workspace.init_workspace(ws, name="Atelier AutoClose", projects=[("demo", "../demo", repo)])

                # 1. Active ANTIGRAVITY_CONVERSATION_ID -> archive <cid> --workspace <ws> (no --update-sealed, no --force)
                with mock.patch.dict(os.environ, {"ANTIGRAVITY_CONVERSATION_ID": "conv-abc-123"}, clear=False):
                    sync_tracking.run_sync(config_path=ws / "projects.json", concept_root=ws, offline=True, ack_editorial=True, gemini_home=g_home)
                self.assertTrue(log_path.is_file())
                argv1 = json.loads(log_path.read_text(encoding="utf-8"))["argv"]
                self.assertEqual(argv1, ["archive", "conv-abc-123", "--workspace", str(ws.resolve())])
                self.assertNotIn("--force", argv1)
                self.assertNotIn("--update-sealed", argv1)

                # 2. Already sealed in history.jsonl -> passes --update-sealed, never --force
                log_path.unlink()
                metrics_store = g_home / "gravity" / "metrics"
                metrics_store.mkdir(parents=True, exist_ok=True)
                (metrics_store / "history.jsonl").write_text(
                    json.dumps({"conversation_id": "conv-abc-123", "status": "archived"}) + "\n",
                    encoding="utf-8",
                )
                with mock.patch.dict(os.environ, {"ANTIGRAVITY_CONVERSATION_ID": "conv-abc-123"}, clear=False):
                    sync_tracking.run_sync(config_path=ws / "projects.json", concept_root=ws, offline=True, ack_editorial=True, gemini_home=g_home)
                argv2 = json.loads(log_path.read_text(encoding="utf-8"))["argv"]
                self.assertEqual(argv2, ["archive", "conv-abc-123", "--workspace", str(ws.resolve()), "--update-sealed"])
                self.assertNotIn("--force", argv2)

                # 3. Fallback to active_captures.json when env var absent
                log_path.unlink()
                (metrics_store / "active_captures.json").write_text(
                    json.dumps({"schema_version": 1, "captures": {"cap-xyz-999": {"start_step": 2, "project": ws.name}}}),
                    encoding="utf-8",
                )
                env_no_cid = {k: v for k, v in os.environ.items() if k != "ANTIGRAVITY_CONVERSATION_ID"}
                with mock.patch.dict(os.environ, env_no_cid, clear=True):
                    sync_tracking.run_sync(config_path=ws / "projects.json", concept_root=ws, offline=True, ack_editorial=True, gemini_home=g_home)
                argv3 = json.loads(log_path.read_text(encoding="utf-8"))["argv"]
                self.assertEqual(argv3, ["archive", "cap-xyz-999", "--workspace", str(ws.resolve())])

    def test_dirty_wip_dry_run_no_ack_and_runtime_only_wip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws, repo, g_home = root / "atelier", root / "demo", root / ".gemini"
            arch_home = root / "arch-home"
            _make_clean_repo(repo)
            log_path = root / "metrics_call.json"
            _install_metrics_stub(g_home, log_path)

            with mock.patch.dict(os.environ, {
                "GRAVITY_ARCHITECT_HOME": str(arch_home),
                "GRAVITY_ARCHITECT_SKIP_REGISTRY": "1",
                "ANTIGRAVITY_CONVERSATION_ID": "conv-wip-test",
            }):
                init_workspace.init_workspace(ws, name="Atelier WIP", projects=[("demo", "../demo", repo)])

                # dry_run=True or ack_editorial=False -> never invoke metrics
                sync_tracking.run_sync(config_path=ws / "projects.json", concept_root=ws, offline=True, ack_editorial=True, dry_run=True, gemini_home=g_home)
                sync_tracking.run_sync(config_path=ws / "projects.json", concept_root=ws, offline=True, ack_editorial=False, gemini_home=g_home)
                self.assertFalse(log_path.exists())

                # Dirty code WIP -> never invoke metrics even with ack_editorial=True
                (repo / "dirty.py").write_text("x = 1\n", encoding="utf-8")
                sync_tracking.run_sync(config_path=ws / "projects.json", concept_root=ws, offline=True, ack_editorial=True, gemini_home=g_home)
                self.assertFalse(log_path.exists())

                # Runtime-only WIP (.agents/) -> treated as clean, triggers metrics
                (repo / "dirty.py").unlink()
                (repo / ".agents").mkdir(exist_ok=True)
                (repo / ".agents" / "state.json").write_text("{}\n", encoding="utf-8")
                sync_tracking.run_sync(config_path=ws / "projects.json", concept_root=ws, offline=True, ack_editorial=True, gemini_home=g_home)
                self.assertTrue(log_path.is_file())

    def test_missing_plugin_cid_or_cli_error_is_silent_best_effort(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws, repo, g_home = root / "atelier", root / "demo", root / ".gemini"
            arch_home = root / "arch-home"
            _make_clean_repo(repo)

            with mock.patch.dict(os.environ, {"GRAVITY_ARCHITECT_HOME": str(arch_home), "GRAVITY_ARCHITECT_SKIP_REGISTRY": "1"}):
                init_workspace.init_workspace(ws, name="Atelier Silent", projects=[("demo", "../demo", repo)])

                # 1. Plugin absent -> silent no-op
                err_buf, out_buf = io.StringIO(), io.StringIO()
                with contextlib.redirect_stderr(err_buf), contextlib.redirect_stdout(out_buf):
                    with mock.patch.dict(os.environ, {"ANTIGRAVITY_CONVERSATION_ID": "conv-missing"}):
                        sync_tracking.run_sync(config_path=ws / "projects.json", concept_root=ws, offline=True, ack_editorial=True, gemini_home=g_home)
                self.assertEqual(err_buf.getvalue(), "")
                self.assertEqual(out_buf.getvalue(), "")

                # 2. Plugin present, CLI fails (rc=1) -> silent non-blocking, shell=False
                log_path = root / "metrics_call.json"
                _install_metrics_stub(g_home, log_path, rc=1)
                with contextlib.redirect_stderr(err_buf), contextlib.redirect_stdout(out_buf):
                    with mock.patch.dict(os.environ, {"ANTIGRAVITY_CONVERSATION_ID": "conv-fail"}):
                        with mock.patch.object(sync_tracking.subprocess, "run", wraps=sync_tracking.subprocess.run) as spy_run:
                            sync_tracking.run_sync(config_path=ws / "projects.json", concept_root=ws, offline=True, ack_editorial=True, gemini_home=g_home)
                self.assertTrue(spy_run.called)
                self.assertIs(spy_run.call_args.kwargs.get("shell"), False)
                self.assertEqual(err_buf.getvalue(), "")
                self.assertEqual(out_buf.getvalue(), "")

                # 3. Subprocess timeout -> silent non-blocking
                with mock.patch.object(sync_tracking.subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="cli.py", timeout=10)):
                    with mock.patch.dict(os.environ, {"ANTIGRAVITY_CONVERSATION_ID": "conv-timeout"}):
                        sync_tracking.run_sync(config_path=ws / "projects.json", concept_root=ws, offline=True, ack_editorial=True, gemini_home=g_home)

    def test_dashboard_provider_cycle_phases_and_current_phase_ro(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws, g_home = root / "atelier", root / "g-home"
            for sub in ("specs/archive", "tasks/archive", "tracking/snapshots"):
                (ws / sub).mkdir(parents=True, exist_ok=True)
            (ws / "ECOSYSTEM.md").write_text("# Eco\n", encoding="utf-8", newline="\n")
            (ws / "projects.json").write_text(json.dumps({"schema_version": 5, "workspace_name": "Phases", "projects": []}), encoding="utf-8")

            # 1. Empty atelier -> all pending, current_phase = conception
            v0 = dp.get_architect_view(ws=str(ws), gravity_home=g_home)
            self.assertEqual(v0["current_phase"], "conception")
            self.assertEqual([p["id"] for p in v0["cycle_phases"]], ["conception", "planification", "production", "validation"])
            self.assertEqual([p["status"] for p in v0["cycle_phases"]], ["pending", "pending", "pending", "pending"])

            # 2. Draft spec -> conception active
            spec_p = ws / "specs" / "2026-11-27-demo.md"
            spec_p.write_text("# Demo Spec\n\n- **Statut :** `draft`\n", encoding="utf-8", newline="\n")
            v1 = dp.get_architect_view(ws=str(ws), gravity_home=g_home)
            self.assertEqual(v1["current_phase"], "conception")
            self.assertEqual([p["status"] for p in v1["cycle_phases"]], ["active", "pending", "pending", "pending"])

            # 3. Validated spec, no tasks -> planification active
            spec_p.write_text("# Demo Spec\n\n- **Statut :** `validated`\n", encoding="utf-8", newline="\n")
            v2 = dp.get_architect_view(ws=str(ws), gravity_home=g_home)
            self.assertEqual(v2["current_phase"], "planification")
            self.assertEqual([p["status"] for p in v2["cycle_phases"]], ["done", "active", "pending", "pending"])

            # 4. Ready task -> production active
            task_p = ws / "tasks" / "2026-11-27-w1-demo.md"
            task_p.write_text("# Demo Task\n\n- **Statut :** `ready`\n- **Vague :** `1`\n", encoding="utf-8", newline="\n")
            v3 = dp.get_architect_view(ws=str(ws), gravity_home=g_home)
            self.assertEqual(v3["current_phase"], "production")
            self.assertEqual([p["status"] for p in v3["cycle_phases"]], ["done", "done", "active", "pending"])

            # 5. Done task (not archived yet) -> validation active
            task_p.write_text("# Demo Task\n\n- **Statut :** `done`\n- **Vague :** `1`\n", encoding="utf-8", newline="\n")
            v4 = dp.get_architect_view(ws=str(ws), gravity_home=g_home)
            self.assertEqual(v4["current_phase"], "validation")
            self.assertEqual([p["status"] for p in v4["cycle_phases"]], ["done", "done", "done", "active"])

            # 6. Archived + clean delta.md -> all done, current_phase = validation
            spec_p.rename(ws / "specs" / "archive" / spec_p.name)
            task_p.rename(ws / "tasks" / "archive" / task_p.name)
            (ws / "tracking" / "snapshots" / "delta.md").write_text(
                "# Delta\n\n- **Statut éditorial :** `NO_EDITORIAL_CHANGES`\n",
                encoding="utf-8",
                newline="\n",
            )
            before_mtimes = {p: p.stat().st_mtime_ns for p in ws.rglob("*") if p.is_file()}
            proc = subprocess.run(
                [sys.executable, "-I", "-B", str(PLUGIN_ROOT / "scripts" / "dashboard_provider.py"), "--view", "architect", "--ws", str(ws), "--gravity-home", str(g_home), "--json"],
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            v5 = json.loads(proc.stdout)
            after_mtimes = {p: p.stat().st_mtime_ns for p in ws.rglob("*") if p.is_file()}
            self.assertEqual(before_mtimes, after_mtimes)
            self.assertFalse(g_home.exists())
            self.assertEqual(v5["current_phase"], "validation")
            self.assertEqual([p["status"] for p in v5["cycle_phases"]], ["done", "done", "done", "done"])


if __name__ == "__main__":
    unittest.main()
