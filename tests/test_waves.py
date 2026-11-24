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
    dependencies: list[str] | None = None,
    target_files: list[str] | None = None,
    anchors: dict[str, list[str]] | None = None,
) -> dict:
    return {
        "id": tid,
        "filename": f"{tid}.md",
        "wave": wave,
        "target_project": target_project,
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


if __name__ == "__main__":
    unittest.main()
