#!/usr/bin/env python3
"""Tests unitaires pour plugin/core/waves.py (100 % stdlib)."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent / "plugin"
sys.path.insert(0, str(PLUGIN_ROOT))

from core import waves  # noqa: E402


def _make_task(
    tid: str,
    *,
    wave: int | str | bool | None = 1,
    target_project: str = "alpha",
    expected_branch: str = "",
    workflow_profile: str = "",
    status: str = "ready",
    dependencies: list[str] | None = None,
    target_files: list[str] | None = None,
    anchors: dict[str, list[str]] | None = None,
) -> dict:
    return {
        "id": tid,
        "filename": f"{tid}.md",
        "title": f"Task {tid}",
        "status": status,
        "wave": wave,
        "target_project": target_project,
        "expected_branch": expected_branch,
        "workflow_profile": workflow_profile,
        "dependencies": dependencies or [],
        "target_files": target_files or [],
        "anchors": anchors or {},
    }


class TestWavesValidation(unittest.TestCase):
    def test_valid_dag_across_multiple_waves(self) -> None:
        tasks = [
            _make_task(
                "2026-11-24-alpha-w1",
                wave=1,
                target_project="alpha",
                target_files=["src/core.py", "README.md", "tests/test_core.py"],
                anchors={"src/core.py": ["src/core.py::run (~L10-L30)"]},
            ),
            _make_task(
                "2026-11-24-beta-w1",
                wave=1,
                target_project="beta",
                target_files=["lib/api.py", "docs/guide.md"],
                anchors={"lib/api.py": ["lib/api.py (~L5-L20)"]},
            ),
            _make_task(
                "2026-11-24-alpha-w2",
                wave=2,
                target_project="alpha",
                dependencies=["2026-11-24-alpha-w1", "2026-11-24-beta-w1"],
                target_files=["src/core.py", "src/cli.py"],
                anchors={
                    "src/core.py": ["src/core.py::main"],
                    "src/cli.py": ["src/cli.py::parse_args (~L12)"],
                },
            ),
        ]
        cfg = {"projects": [{"id": "alpha"}, {"id": "beta"}]}
        res = waves.validate_waves(tasks, projects_cfg=cfg)
        self.assertTrue(res["ok"], res["errors"])
        self.assertEqual(res["errors"], [])
        self.assertEqual(res["task_count"], 3)
        self.assertEqual(
            res["waves"],
            {1: ["2026-11-24-alpha-w1", "2026-11-24-beta-w1"], 2: ["2026-11-24-alpha-w2"]},
        )

    def test_project_wave_collision_and_invalid_project_or_wave(self) -> None:
        tasks = [
            _make_task("t1", wave=1, target_project="alpha"),
            _make_task("t2", wave=1, target_project="alpha"),
            _make_task("t3", wave=0, target_project=""),
            _make_task("t4", wave=True, target_project="unknown"),
        ]
        res = waves.validate_waves(tasks, projects_cfg={"projects": [{"id": "alpha"}]})
        self.assertFalse(res["ok"])
        joined = " | ".join(res["errors"])
        self.assertIn("collision sur le dépôt `alpha`", joined)
        self.assertIn("vague invalide", joined)
        self.assertIn("`target_project` manquant ou vide", joined)
        self.assertIn("dépôt cible `unknown` inconnu", joined)

    def test_target_files_collision_normalizes_anchors_and_prefixes(self) -> None:
        tasks = [
            _make_task(
                "t1",
                wave=1,
                target_project="alpha",
                target_files=["./src/shared.py::fn_a (~L10)"],
                anchors={"./src/shared.py": ["src/shared.py::fn_a (~L10)"]},
            ),
            _make_task(
                "t2",
                wave=1,
                target_project="beta",
                target_files=["src\\shared.py (~L50-L70)"],
                anchors={"src/shared.py": ["src/shared.py (~L50-L70)"]},
            ),
        ]
        res = waves.validate_waves(tasks)
        self.assertFalse(res["ok"])
        self.assertTrue(any("fichier cible `src/shared.py` partagé" in e for e in res["errors"]), res["errors"])

    def test_dag_cycle_self_dep_missing_dep_and_wave_order(self) -> None:
        tasks = [
            _make_task("t1", wave=1, target_project="a", dependencies=["t2"]),
            _make_task("t2", wave=2, target_project="b", dependencies=["t1"]),
            _make_task("t3", wave=1, target_project="c", dependencies=["t3", "missing-id"]),
            _make_task("t4", wave=2, target_project="d", dependencies=["t2"]),
        ]
        res = waves.validate_waves(tasks)
        self.assertFalse(res["ok"])
        joined = " | ".join(res["errors"])
        self.assertIn("Cycle de dépendances", joined)
        self.assertIn("auto-dépendance interdite", joined)
        self.assertIn("dépendance introuvable (`missing-id`)", joined)
        self.assertIn("wave(dep) doit être < wave(task)", joined)

    def test_missing_hybrid_anchor_and_five_code_files_limit_excluding_tests_docs(self) -> None:
        # 5 fichiers code avec ancres + 4 fichiers docs/tests sans ancre -> OK
        ok_task = _make_task(
            "t-ok",
            wave=1,
            target_project="alpha",
            target_files=[
                "src/f1.py",
                "src/f2.py",
                "src/f3.py",
                "src/f4.py",
                "src/f5.py",
                "README.md",
                "docs/arch.rst",
                "notes.txt",
                "tests/test_f1.py",
                "pkg/foo_test.go",
                "ui/app.test.ts",
                "ui/app.spec.js",
                "test_root.py",
            ],
            anchors={
                "src/f1.py": ["src/f1.py::c1"],
                "src/f2.py": ["src/f2.py (~L10)"],
                "src/f3.py": ["src/f3.py::c3 (~L20-L30)"],
                "src/f4.py": ["src/f4.py::c4"],
                "src/f5.py": ["src/f5.py ~L99"],
            },
        )
        res_ok = waves.validate_waves([ok_task])
        self.assertTrue(res_ok["ok"], res_ok["errors"])

        # 6 fichiers code + 1 sans ancre hybride -> FAIL sur les deux règles
        bad_task = _make_task(
            "t-bad",
            wave=1,
            target_project="alpha",
            target_files=[f"src/f{i}.py" for i in range(1, 7)],
            anchors={f"src/f{i}.py": [f"src/f{i}.py::fn"] for i in range(1, 6)},
        )
        res_bad = waves.validate_waves([bad_task])
        self.assertFalse(res_bad["ok"])
        joined = " | ".join(res_bad["errors"])
        self.assertIn("6 fichiers code cibles > plafond 5", joined)
        self.assertIn("ancre hybride (`::` ou `~L`) manquante pour le fichier code `src/f6.py`", joined)

    def test_cli_check_waves_workspace_tasks_dir_config_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = root / "atelier"
            tasks_dir = ws / "tasks"
            (tasks_dir / "archive").mkdir(parents=True)
            (tasks_dir / "_TEMPLATE.md").write_text("# Tpl\n", encoding="utf-8")
            cfg_path = ws / "projects.json"
            cfg_path.write_text(
                json.dumps({"schema_version": 5, "projects": [{"id": "alpha"}, {"id": "beta"}]}),
                encoding="utf-8",
            )
            (tasks_dir / "2026-11-24-alpha-w1.md").write_text(
                "# Task 1\n"
                "- **Vague :** `1`\n"
                "- **Dépôt cible :** `alpha`\n"
                "- **Dépendances :** `aucune`\n"
                "- **Profil workflow :** `standard`\n\n"
                "## Ancres exactes\n"
                "- `src/a.py::run (~L10-L20)`\n",
                encoding="utf-8",
            )
            (tasks_dir / "2026-11-24-beta-w2.md").write_text(
                "# Task 2\n"
                "- **Vague :** `2`\n"
                "- **Dépôt cible :** `beta`\n"
                "- **Dépendances :** `2026-11-24-alpha-w1`\n"
                "- **Profil workflow :** `quick`\n\n"
                "## Ancres exactes\n"
                "- `src/b.py` (~L5)\n",
                encoding="utf-8",
            )

            buf_ok = io.StringIO()
            with contextlib.redirect_stdout(buf_ok):
                rc_ok = waves.main(["--check-waves", "--workspace", str(ws), "--json"])
            self.assertEqual(rc_ok, 0)
            payload_ok = json.loads(buf_ok.getvalue())
            self.assertTrue(payload_ok["ok"])
            self.assertEqual(payload_ok["task_count"], 2)
            self.assertEqual(payload_ok["waves"], {"1": ["2026-11-24-alpha-w1"], "2": ["2026-11-24-beta-w2"]})

            # Collision via --tasks-dir et --config explicite -> exit code 1
            (tasks_dir / "2026-11-24-alpha-w1b.md").write_text(
                "# Task 1b\n- **Vague :** `1`\n- **Dépôt cible :** `alpha`\n## Ancres exactes\n- `src/c.py::fn`\n",
                encoding="utf-8",
            )
            buf_fail = io.StringIO()
            with contextlib.redirect_stdout(buf_fail):
                rc_fail = waves.main(["--check-waves", "--tasks-dir", str(tasks_dir), "--config", str(cfg_path), "--json"])
            self.assertEqual(rc_fail, 1)
            payload_fail = json.loads(buf_fail.getvalue())
            self.assertFalse(payload_fail["ok"])
            self.assertTrue(any("collision" in e for e in payload_fail["errors"]))

    def test_workflow_profile_validation(self) -> None:
        tasks = [
            _make_task("t-quick", wave=1, target_project="alpha", workflow_profile="quick"),
            _make_task("t-std", wave=2, target_project="alpha", workflow_profile="standard"),
            _make_task("t-deep", wave=3, target_project="alpha", workflow_profile="deep"),
            _make_task("t-empty", wave=4, target_project="alpha", workflow_profile=""),
        ]
        res_ok = waves.validate_waves(tasks)
        self.assertTrue(res_ok["ok"], res_ok["errors"])

        res_bad = waves.validate_waves([_make_task("t-bad", wave=1, target_project="alpha", workflow_profile="ultra")])
        self.assertFalse(res_bad["ok"])
        self.assertTrue(any("workflow_profile" in e and "ultra" in e for e in res_bad["errors"]), res_bad["errors"])

    def test_export_wave_v1_contract_and_fail_closed_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = root / "atelier"
            tasks_dir = ws / "tasks"
            tasks_dir.mkdir(parents=True)
            repo_alpha = root / "alpha"
            repo_beta = root / "beta"
            repo_alpha.mkdir()
            repo_beta.mkdir()

            cfg_path = ws / "projects.json"
            cfg_path.write_text(
                json.dumps({
                    "schema_version": 5,
                    "projects": [
                        {"id": "alpha", "path": "../alpha", "default_dev_branch": "develop"},
                        {"id": "beta", "path": str(repo_beta)},
                    ],
                }),
                encoding="utf-8",
            )

            t1_path = tasks_dir / "2026-11-25-w1-alpha.md"
            t1_path.write_text(
                "# Alpha Lot 1\n"
                "- **Vague :** `1`\n"
                "- **Dépôt cible :** `alpha` (`../alpha`)\n"
                "- **Dépendances :** `aucune`\n"
                "- **Profil workflow :** `quick`\n"
                "- **Date / Statut :** `2026-11-25` — `ready`\n\n"
                "## Ancres exactes\n"
                "- `plugin/core.py::run (~L10-L20)`\n",
                encoding="utf-8",
            )
            t2_path = tasks_dir / "2026-11-25-w1-beta.md"
            t2_path.write_text(
                "# Beta Lot 1\n"
                "- **Vague :** `1`\n"
                "- **Dépôt cible :** `beta`\n"
                "- **Branche attendue :** `feat/dip-w1`\n"
                "- **Dépendances :** `aucune`\n"
                "- **Date / Statut :** `2026-11-25` — `ready`\n\n"
                "## Ancres exactes\n"
                "- `src/main.py::main (~L1-L10)`\n",
                encoding="utf-8",
            )
            t3_path = tasks_dir / "2026-11-25-w2-alpha.md"
            t3_path.write_text(
                "# Alpha Lot 2\n"
                "- **Vague :** `2`\n"
                "- **Dépôt cible :** `alpha`\n"
                "- **Dépendances :** `2026-11-25-w1-alpha`\n"
                "- **Date / Statut :** `2026-11-25` — `draft`\n\n"
                "## Ancres exactes\n"
                "- `plugin/cli.py::main (~L5)`\n",
                encoding="utf-8",
            )

            # 1. CLI --export-wave 1 -> stdout JSON wave_plan_v1
            buf_out = io.StringIO()
            with contextlib.redirect_stdout(buf_out):
                rc = waves.main(["--export-wave", "1", "--workspace", str(ws)])
            self.assertEqual(rc, 0)
            plan = json.loads(buf_out.getvalue())
            self.assertEqual(plan["schema_version"], "wave_plan_v1")
            self.assertEqual(plan["workspace"], str(ws.resolve()))
            self.assertEqual(plan["wave"], 1)
            self.assertEqual(len(plan["tasks"]), 2)

            alpha_item, beta_item = plan["tasks"][0], plan["tasks"][1]
            self.assertEqual(alpha_item["id"], "2026-11-25-w1-alpha")
            self.assertEqual(alpha_item["title"], "Alpha Lot 1")
            self.assertEqual(alpha_item["repo_id"], "alpha")
            self.assertEqual(alpha_item["repo_root"], str(repo_alpha.resolve()))
            self.assertEqual(alpha_item["expected_branch"], "develop")
            self.assertEqual(alpha_item["profile"], "quick")
            self.assertEqual(alpha_item["plan_file"], str(t1_path.resolve()))
            self.assertEqual(alpha_item["target_files"], ["plugin/core.py"])
            self.assertEqual(alpha_item["status"], "ready")

            self.assertEqual(beta_item["id"], "2026-11-25-w1-beta")
            self.assertEqual(beta_item["repo_root"], str(repo_beta.resolve()))
            self.assertEqual(beta_item["expected_branch"], "feat/dip-w1")
            self.assertEqual(beta_item["profile"], "standard")

            # 2. CLI --export-wave 1 --out <file>
            out_file = root / "out" / "wave1.json"
            buf_file = io.StringIO()
            with contextlib.redirect_stdout(buf_file):
                rc_file = waves.main(["--export-wave", "1", "--workspace", str(ws), "--out", str(out_file)])
            self.assertEqual(rc_file, 0)
            self.assertTrue(out_file.is_file())
            self.assertEqual(json.loads(out_file.read_text(encoding="utf-8")), plan)

            # 3. Fail-closed : statut bloqué (draft/done/archived/cancelled) sur vague 2 -> rc=1
            for blocked in ("draft", "done", "archived", "cancelled"):
                t3_path.write_text(
                    "# Alpha Lot 2\n"
                    "- **Vague :** `2`\n"
                    "- **Dépôt cible :** `alpha`\n"
                    "- **Dépendances :** `2026-11-25-w1-alpha`\n"
                    f"- **Date / Statut :** `2026-11-25` — `{blocked}`\n\n"
                    "## Ancres exactes\n"
                    "- `plugin/cli.py::main (~L5)`\n",
                    encoding="utf-8",
                )
                buf_err = io.StringIO()
                with contextlib.redirect_stderr(buf_err):
                    rc_blk = waves.main(["--export-wave", "2", "--workspace", str(ws)])
                self.assertEqual(rc_blk, 1)
                self.assertIn(blocked, buf_err.getvalue())

            # 4. Fail-closed : vague vide -> rc=1
            buf_empty = io.StringIO()
            with contextlib.redirect_stderr(buf_empty):
                rc_empty = waves.main(["--export-wave", "9", "--workspace", str(ws)])
            self.assertEqual(rc_empty, 1)
            self.assertIn("vide", buf_empty.getvalue())

            # 5. Fail-closed : repo_root absent -> rc=1
            repo_beta.rmdir()
            buf_missing = io.StringIO()
            with contextlib.redirect_stderr(buf_missing):
                rc_missing = waves.main(["--export-wave", "1", "--workspace", str(ws)])
            self.assertEqual(rc_missing, 1)
            self.assertIn("repo_root", buf_missing.getvalue())
            repo_beta.mkdir()

            # 6. Fail-closed : --out sans --export-wave -> rc=1
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(waves.main(["--workspace", str(ws), "--out", str(out_file)]), 1)

            # 7. Fail-closed : profil invalide dans task -> rc=1
            t1_path.write_text(
                "# Alpha Lot 1\n- **Vague :** `1`\n- **Dépôt cible :** `alpha`\n- **Profil workflow :** `invalid`\n- **Date / Statut :** `2026-11-25` — `ready`\n## Ancres exactes\n- `plugin/core.py::run (~L10)`\n",
                encoding="utf-8",
            )
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(waves.main(["--export-wave", "1", "--workspace", str(ws)]), 1)


if __name__ == "__main__":
    unittest.main()
