#!/usr/bin/env python3
"""Tests unitaires pour plugin/core/waves.py et parse_artifact_file (100 % stdlib)."""

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

from core import io_utils, waves  # noqa: E402


def _make_task(
    tid: str,
    *,
    task_id: str | None = None,
    wave: int | str | bool | None = 1,
    target_project: str = "alpha",
    expected_branch: str = "",
    workflow_profile: str = "",
    status: str = "ready",
    dependencies: list[str] | None = None,
    target_files: list[str] | None = None,
    anchors: dict[str, list[str]] | None = None,
    spec_id: str = "",
    spec_source: str = "",
    acceptance_criteria: list[str] | None = None,
    wave_name: str = "",
) -> dict:
    out: dict = {
        "id": tid,
        "task_id": tid if task_id is None else task_id,
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
    if spec_id:
        out["spec_id"] = spec_id
    if spec_source:
        out["spec_source"] = spec_source
    if acceptance_criteria is not None:
        out["acceptance_criteria"] = acceptance_criteria
    if wave_name:
        out["wave_name"] = wave_name
    return out


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
                target_project="alpha",
                target_files=["src\\shared.py (~L50-L70)"],
                anchors={"src/shared.py": ["src/shared.py (~L50-L70)"]},
            ),
        ]
        res = waves.validate_waves(tasks)
        self.assertFalse(res["ok"])
        self.assertTrue(any("fichier cible `src/shared.py` partagé" in e for e in res["errors"]), res["errors"])

    def test_multi_repo_same_wave_allows_shared_changelog_without_consuming_code_quota(self) -> None:
        tasks = [
            _make_task(
                "t-alpha",
                wave=1,
                target_project="alpha",
                target_files=[f"src/a{i}.py" for i in range(1, 6)] + ["CHANGELOG.md"],
                anchors={f"src/a{i}.py": [f"src/a{i}.py::fn_{i}"] for i in range(1, 6)},
            ),
            _make_task(
                "t-beta",
                wave=1,
                target_project="beta",
                target_files=[f"lib/b{i}.py" for i in range(1, 6)] + ["CHANGELOG.md"],
                anchors={f"lib/b{i}.py": [f"lib/b{i}.py::fn_{i}"] for i in range(1, 6)},
            ),
        ]
        cfg = {"projects": [{"id": "alpha"}, {"id": "beta"}]}
        res = waves.validate_waves(tasks, projects_cfg=cfg)
        self.assertTrue(res["ok"], res["errors"])
        self.assertEqual(res["errors"], [])
        self.assertEqual(res["waves"], {1: ["t-alpha", "t-beta"]})

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

            buf_out = io.StringIO()
            with contextlib.redirect_stdout(buf_out):
                rc = waves.main(["--export-wave", "1", "--workspace", str(ws)])
            self.assertEqual(rc, 0)
            plan = json.loads(buf_out.getvalue())
            self.assertEqual(plan["schema_version"], "wave_plan_v1")
            self.assertEqual(plan["workspace"], str(ws.resolve()))
            self.assertEqual(plan["wave"], 1)
            self.assertEqual(plan["wave_name"], "")
            self.assertEqual(len(plan["tasks"]), 2)

            alpha_item, beta_item = plan["tasks"][0], plan["tasks"][1]
            self.assertEqual(alpha_item["id"], "2026-11-25-w1-alpha")
            self.assertEqual(alpha_item["spec_id"], "")
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

            out_file = root / "out" / "wave1.json"
            buf_file = io.StringIO()
            with contextlib.redirect_stdout(buf_file):
                rc_file = waves.main(["--export-wave", "1", "--workspace", str(ws), "--out", str(out_file)])
            self.assertEqual(rc_file, 0)
            self.assertTrue(out_file.is_file())
            self.assertEqual(json.loads(out_file.read_text(encoding="utf-8")), plan)

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

            buf_empty = io.StringIO()
            with contextlib.redirect_stderr(buf_empty):
                rc_empty = waves.main(["--export-wave", "9", "--workspace", str(ws)])
            self.assertEqual(rc_empty, 1)
            self.assertIn("vide", buf_empty.getvalue())

            repo_beta.rmdir()
            buf_missing = io.StringIO()
            with contextlib.redirect_stderr(buf_missing):
                rc_missing = waves.main(["--export-wave", "1", "--workspace", str(ws)])
            self.assertEqual(rc_missing, 1)
            self.assertIn("repo_root", buf_missing.getvalue())
            repo_beta.mkdir()

            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(waves.main(["--workspace", str(ws), "--out", str(out_file)]), 1)

            t1_path.write_text(
                "# Alpha Lot 1\n- **Vague :** `1`\n- **Dépôt cible :** `alpha`\n- **Profil workflow :** `invalid`\n- **Date / Statut :** `2026-11-25` — `ready`\n## Ancres exactes\n- `plugin/core.py::run (~L10)`\n",
                encoding="utf-8",
            )
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(waves.main(["--export-wave", "1", "--workspace", str(ws)]), 1)

    def test_bilingual_en_aliases_and_spec_field_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ws"
            tasks_dir = ws / "tasks"
            tasks_dir.mkdir(parents=True)
            tpath = tasks_dir / "2026-11-26-en-task.md"
            tpath.write_text(
                "# English Task\n"
                "- **Task ID :** `TASK-EN-01`\n"
                "- **Spec ID:** `SPEC-EN-01`\n"
                "- **Spec source**: [SPEC-EN-01](..\\specs\\2026-11-26-spec-en.md)\n"
                "- **Acceptance Criteria Covered:** `AC-1`, `AC-3` *(core)*\n"
                "- **Status:** `ready`\n"
                "- **Wave:** `2`\n"
                "- **Wave name:** `English Wave`\n"
                "- **Target project:** `alpha`\n"
                "- **Expected branch:** `refonte/socle`\n"
                "- **Dependencies:** `2026-11-26-dep-a.md`, `2026-11-26-dep-b`\n"
                "- **Workflow profile:** `deep`\n\n"
                "## Exact anchors\n"
                "- `src/app.py::run (~L10-L25)`\n",
                encoding="utf-8",
            )
            parsed = io_utils.parse_artifact_file(tpath, ws)
            self.assertEqual(parsed["id"], "2026-11-26-en-task")
            self.assertEqual(parsed["task_id"], "TASK-EN-01")
            self.assertEqual(parsed["spec_id"], "SPEC-EN-01")
            self.assertEqual(parsed["spec_source"], "../specs/2026-11-26-spec-en.md")
            self.assertEqual(parsed["acceptance_criteria"], ["AC-1", "AC-3"])
            self.assertEqual(parsed["status"], "ready")
            self.assertEqual(parsed["wave"], 2)
            self.assertEqual(parsed["wave_name"], "English Wave")
            self.assertEqual(parsed["target_project"], "alpha")
            self.assertEqual(parsed["expected_branch"], "refonte/socle")
            self.assertEqual(parsed["dependencies"], ["2026-11-26-dep-a", "2026-11-26-dep-b"])
            self.assertEqual(parsed["workflow_profile"], "deep")
            self.assertEqual(parsed["target_files"], ["src/app.py"])
            self.assertIn("src/app.py", parsed["anchors"])

    def test_fail_closed_spec_traceability_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "atelier"
            (ws / "specs" / "archive").mkdir(parents=True)
            (ws / "tasks").mkdir(parents=True)
            (ws / "projects.json").write_text(
                json.dumps({"schema_version": 6, "projects": [{"id": "alpha", "path": "../alpha"}]}),
                encoding="utf-8",
            )
            (ws / "specs" / "2026-11-26-valid.md").write_text(
                "# Valid Spec\n- **Spec ID :** `SPEC-VAL-01`\n- **Statut :** `validated`\n",
                encoding="utf-8",
            )
            (ws / "specs" / "2026-11-26-draft.md").write_text(
                "# Draft Spec\n- **Spec ID :** `SPEC-DRF-01`\n- **Statut :** `draft`\n",
                encoding="utf-8",
            )
            (ws / "specs" / "archive" / "2026-11-26-old.md").write_text(
                "# Old Spec\n- **Spec ID :** `SPEC-OLD-01`\n- **Statut :** `validated`\n",
                encoding="utf-8",
            )

            valid_task = _make_task(
                "t-valid",
                wave=1,
                target_project="alpha",
                spec_id="SPEC-VAL-01",
                spec_source="../specs/2026-11-26-valid.md",
                acceptance_criteria=["AC-1"],
            )
            ok_res = waves.validate_waves([valid_task], workspace_root=ws)
            self.assertTrue(ok_res["ok"], ok_res["errors"])

            bad_cases = [
                ("missing Task ID", _make_task("b0", task_id="", spec_id="SPEC-VAL-01", spec_source="specs/2026-11-26-valid.md", acceptance_criteria=["AC-1"]), "`Task ID` manquant"),
                ("missing Spec ID", _make_task("b1", spec_source="specs/2026-11-26-valid.md", acceptance_criteria=["AC-1"]), "`Spec ID` manquant"),
                ("missing Spec source", _make_task("b2", spec_id="SPEC-VAL-01", acceptance_criteria=["AC-1"]), "`Spec source` manquant"),
                ("non-existent spec", _make_task("b3", spec_id="SPEC-VAL-01", spec_source="specs/nope.md", acceptance_criteria=["AC-1"]), "introuvable ou archivée"),
                ("archived spec", _make_task("b4", spec_id="SPEC-OLD-01", spec_source="specs/archive/2026-11-26-old.md", acceptance_criteria=["AC-1"]), "introuvable ou archivée"),
                ("archived relative spec", _make_task("b5", spec_id="SPEC-OLD-01", spec_source="../specs/archive/2026-11-26-old.md", acceptance_criteria=["AC-1"]), "introuvable ou archivée"),
                ("draft spec", _make_task("b6", spec_id="SPEC-DRF-01", spec_source="specs/2026-11-26-draft.md", acceptance_criteria=["AC-1"]), "non validée"),
                ("Spec ID mismatch", _make_task("b7", spec_id="SPEC-WRONG", spec_source="specs/2026-11-26-valid.md", acceptance_criteria=["AC-1"]), "incohérence `Spec ID`"),
                ("empty AC", _make_task("b8", spec_id="SPEC-VAL-01", spec_source="specs/2026-11-26-valid.md", acceptance_criteria=[]), "`Acceptance Criteria Covered` manquant ou vide"),
            ]
            for label, bad_task, expected_msg in bad_cases:
                res = waves.validate_waves([bad_task], workspace_root=ws)
                self.assertFalse(res["ok"], f"{label} should fail")
                self.assertTrue(any(expected_msg in e for e in res["errors"]), f"{label}: {res['errors']}")

            dup_tasks = [
                _make_task("dup1", task_id="TASK-DUP", wave=1, target_project="alpha", spec_id="SPEC-VAL-01", spec_source="specs/2026-11-26-valid.md", acceptance_criteria=["AC-1"]),
                _make_task("dup2", task_id="TASK-DUP", wave=2, target_project="alpha", spec_id="SPEC-VAL-01", spec_source="specs/2026-11-26-valid.md", acceptance_criteria=["AC-2"]),
            ]
            res_dup = waves.validate_waves(dup_tasks, workspace_root=ws)
            self.assertFalse(res_dup["ok"])
            self.assertTrue(any("`Task ID` dupliqué" in e and "TASK-DUP" in e for e in res_dup["errors"]), res_dup["errors"])

            # Explicit require_spec=True fails even without specs_dir
            res_forced = waves.validate_waves([_make_task("b9")], require_spec=True)
            self.assertFalse(res_forced["ok"])

    def test_self_workspace_atelier_id_and_wave_name_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = root / "gravity-workshop"
            (ws / "specs").mkdir(parents=True)
            (ws / "tasks").mkdir(parents=True)
            (ws / "projects.json").write_text(
                json.dumps({
                    "schema_version": 6,
                    "atelier_id": "my-atelier-id",
                    "refonte_branch": "refonte/socle",
                    "projects": [{"id": "alpha", "path": "../alpha"}],
                }),
                encoding="utf-8",
            )
            (ws / "specs" / "2026-11-26-spec-ws.md").write_text(
                "# Spec WS\n- **Spec ID :** `SPEC-WS-01`\n- **Statut :** `validated`\n",
                encoding="utf-8",
            )
            t1 = ws / "tasks" / "2026-11-26-w1-ws.md"
            t1.write_text(
                "# WS Self Task\n"
                "- **Task ID :** `TASK-WS-01`\n"
                "- **Spec ID :** `SPEC-WS-01`\n"
                "- **Spec source :** `specs/2026-11-26-spec-ws.md`\n"
                "- **Acceptance Criteria Covered :** `AC-1`\n"
                "- **Date / Statut :** `2026-11-26` — `ready`\n"
                "- **Vague :** `1`\n"
                "- **Nom de vague :** `Self Atelier Wave`\n"
                "- **Dépôt cible :** `my-atelier-id`\n"
                "- **Profil workflow :** `standard`\n\n"
                "## Ancres exactes\n"
                "- `projects.json::projects (~L10-L20)`\n",
                encoding="utf-8",
            )
            t2 = ws / "tasks" / "2026-11-26-w2-ws-dir.md"
            t2.write_text(
                "# WS Dir Name Task\n"
                "- **Task ID :** `TASK-WS-02`\n"
                "- **Spec ID :** `SPEC-WS-01`\n"
                "- **Spec source :** `specs/2026-11-26-spec-ws.md`\n"
                "- **Acceptance Criteria Covered :** `AC-2`\n"
                "- **Date / Statut :** `2026-11-26` — `ready`\n"
                "- **Vague :** `2`\n"
                "- **Dépôt cible :** `gravity-workshop`\n"
                "- **Dépendances :** `2026-11-26-w1-ws`\n\n"
                "## Ancres exactes\n"
                "- `ECOSYSTEM.md` — *non-code*\n",
                encoding="utf-8",
            )

            buf_chk = io.StringIO()
            with contextlib.redirect_stdout(buf_chk):
                rc_chk = waves.main(["--check-waves", "--workspace", str(ws), "--json"])
            self.assertEqual(rc_chk, 0)
            chk_data = json.loads(buf_chk.getvalue())
            self.assertTrue(chk_data["ok"], chk_data["errors"])

            buf_exp = io.StringIO()
            with contextlib.redirect_stdout(buf_exp):
                rc_exp = waves.main(["--export-wave", "1", "--workspace", str(ws)])
            self.assertEqual(rc_exp, 0)
            plan = json.loads(buf_exp.getvalue())
            self.assertEqual(plan["wave_name"], "Self Atelier Wave")
            self.assertEqual(plan["tasks"][0]["spec_id"], "SPEC-WS-01")
            self.assertEqual(plan["tasks"][0]["repo_id"], "my-atelier-id")
            self.assertEqual(plan["tasks"][0]["repo_root"], str(ws.resolve()))
            self.assertEqual(plan["tasks"][0]["expected_branch"], "refonte/socle")
            self.assertEqual(plan["tasks"][0]["wave_name"], "Self Atelier Wave")

            buf_exp2 = io.StringIO()
            with contextlib.redirect_stdout(buf_exp2):
                rc_exp2 = waves.main(["--export-wave", "2", "--workspace", str(ws)])
            self.assertEqual(rc_exp2, 0)
            plan2 = json.loads(buf_exp2.getvalue())
            self.assertEqual(plan2["wave_name"], "")
            self.assertEqual(plan2["tasks"][0]["repo_id"], "gravity-workshop")
            self.assertEqual(plan2["tasks"][0]["spec_id"], "SPEC-WS-01")

    def test_export_wave_aggregates_distinct_wave_names_and_guards_symlink_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = root / "atelier"
            (ws / "specs").mkdir(parents=True)
            (ws / "tasks").mkdir(parents=True)
            for name in ("alpha", "beta", "gamma"):
                (root / name).mkdir()
            (ws / "projects.json").write_text(
                json.dumps({
                    "schema_version": 6,
                    "projects": [
                        {"id": "alpha", "path": "../alpha"},
                        {"id": "beta", "path": "../beta"},
                        {"id": "gamma", "path": "../gamma"},
                    ],
                }),
                encoding="utf-8",
            )
            (ws / "specs" / "2026-11-26-spec-multi.md").write_text(
                "# Spec Multi\n- **Spec ID :** `SPEC-MULTI-01`\n- **Statut :** `validated`\n",
                encoding="utf-8",
            )
            for fname, tid, repo, wname in (
                ("2026-11-26-w1-a.md", "TASK-A", "alpha", "M4 Alpha — Core"),
                ("2026-11-26-w1-b.md", "TASK-B", "beta", "M4 Beta — CLI"),
                ("2026-11-26-w1-c.md", "TASK-C", "gamma", "M4 Alpha — Core"),
            ):
                (ws / "tasks" / fname).write_text(
                    f"# {tid}\n"
                    f"- **Task ID :** `{tid}`\n"
                    "- **Spec ID :** `SPEC-MULTI-01`\n"
                    "- **Spec source :** `specs/2026-11-26-spec-multi.md`\n"
                    "- **Acceptance Criteria Covered :** `AC-1`\n"
                    "- **Date / Statut :** `2026-11-26` — `ready`\n"
                    "- **Vague :** `1`\n"
                    f"- **Nom de vague :** `{wname}`\n"
                    f"- **Dépôt cible :** `{repo}`\n\n"
                    "## Ancres exactes\n"
                    "- `src/mod.py::run (~L1-L5)`\n",
                    encoding="utf-8",
                )

            out_json = root / "exports" / "w1.json"
            with contextlib.redirect_stdout(io.StringIO()):
                rc = waves.main(["--export-wave", "1", "--workspace", str(ws), "--out", str(out_json)])
            self.assertEqual(rc, 0)
            raw = out_json.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(b"\r\n", raw)
            self.assertEqual([p for p in out_json.parent.iterdir() if p.name.endswith(".tmp")], [])
            plan = json.loads(raw.decode("utf-8"))
            self.assertEqual(plan["wave_name"], "M4 Alpha — Core | M4 Beta — CLI")
            self.assertEqual([t["spec_id"] for t in plan["tasks"]], ["SPEC-MULTI-01"] * 3)

            real_target = root / "real.json"
            real_target.write_text('{"keep": true}\n', encoding="utf-8")
            sym_out = root / "sym-out.json"
            sym_out.symlink_to(real_target)
            err_buf = io.StringIO()
            with contextlib.redirect_stderr(err_buf):
                rc_sym = waves.main(["--export-wave", "1", "--workspace", str(ws), "--out", str(sym_out)])
            self.assertEqual(rc_sym, 1)
            self.assertIn("symlink", err_buf.getvalue().lower())
            self.assertEqual(real_target.read_text(encoding="utf-8"), '{"keep": true}\n')


if __name__ == "__main__":
    unittest.main()
