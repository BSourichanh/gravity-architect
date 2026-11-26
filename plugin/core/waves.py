"""Validation fail-closed des vagues d'exécution (`tasks/`), DAG, traçabilité Spec et ancres hybrides."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from core.io_utils import (  # noqa: E402
    HYBRID_ANCHOR_RE,
    configure_utf8_stdio,
    load_config,
    normalize_target_file,
    resolve_workspace_root,
    scan_md_dir,
    write_utf8,
)

MAX_CODE_FILES_PER_TASK = 5
WAVE_PLAN_SCHEMA_VERSION = "wave_plan_v1"
ALLOWED_WORKFLOW_PROFILES = frozenset({"quick", "standard", "deep"})
BLOCKED_EXPORT_STATUSES = frozenset({"draft", "done", "archived", "cancelled"})


def is_non_code_file(path_str: str) -> bool:
    """Retourne True pour les docs (`.md/.rst/.txt/docs/`) et tests (`tests//test_/_test./.test./.spec.`)."""
    p = normalize_target_file(path_str).lower()
    if not p:
        return False
    name = p.rsplit("/", 1)[-1]
    if p.endswith((".md", ".rst", ".txt")) or p.startswith("docs/") or "/docs/" in p:
        return True
    return (
        p.startswith("tests/")
        or "/tests/" in p
        or name.startswith("test_")
        or "_test." in name
        or ".test." in name
        or ".spec." in name
    )


def _extract_project_specs(
    projects_cfg: dict | list | set | tuple | None, *, base_dir: Path | None = None
) -> dict[str, dict] | None:
    """Indexe `repo_id -> {id, path, repo_root, default_dev_branch}` depuis `projects.json` (incl. atelier)."""
    if projects_cfg is None:
        return None
    items = projects_cfg.get("projects") or [] if isinstance(projects_cfg, dict) else projects_cfg
    specs: dict[str, dict] = {}
    for item in items:
        if isinstance(item, dict):
            if pid := str(item.get("id") or "").strip():
                raw_path = str(item.get("path") or "").strip()
                repo_root: Path | None = None
                if raw_path:
                    p = Path(raw_path).expanduser()
                    repo_root = p.resolve() if p.is_absolute() else ((base_dir / p).resolve() if base_dir is not None else p.resolve())
                dev_branch = str(item.get("default_dev_branch") or "dev").strip() or "dev"
                specs[pid] = {"id": pid, "path": raw_path, "repo_root": repo_root, "default_dev_branch": dev_branch}
        elif isinstance(item, str) and item.strip():
            pid = item.strip()
            specs[pid] = {"id": pid, "path": "", "repo_root": None, "default_dev_branch": "dev"}

    if isinstance(projects_cfg, dict):
        dev_default = str(projects_cfg.get("refonte_branch") or "dev").strip() or "dev"
        self_ids: list[str] = []
        if aid := str(projects_cfg.get("atelier_id") or "").strip():
            self_ids.append(aid)
        if base_dir is not None and base_dir.name and base_dir.name not in self_ids:
            self_ids.append(base_dir.name)
        for sid in self_ids:
            if sid not in specs:
                specs[sid] = {
                    "id": sid,
                    "path": ".",
                    "repo_root": base_dir.resolve() if base_dir is not None else None,
                    "default_dev_branch": dev_default,
                }
    return specs


def _extract_known_project_ids(
    projects_cfg: dict | list | set | tuple | None, *, workspace_root: Path | None = None
) -> set[str] | None:
    base_dir = workspace_root.expanduser().resolve() if workspace_root is not None else None
    specs = _extract_project_specs(projects_cfg, base_dir=base_dir)
    return set(specs.keys()) if specs is not None else None


def _task_id(task: dict, idx: int) -> str:
    raw = task.get("id") or task.get("filename") or f"task#{idx}"
    s = str(raw).strip()
    return s[:-3] if s.endswith(".md") else s


def _normalize_task_anchors(raw_anchors: dict | None) -> dict[str, list[str]]:
    norm_anchors: dict[str, list[str]] = {}
    if not isinstance(raw_anchors, dict):
        return norm_anchors
    for raw_k, vals in raw_anchors.items():
        nk = normalize_target_file(str(raw_k))
        if not nk:
            continue
        bucket = norm_anchors.setdefault(nk, [])
        if isinstance(vals, list):
            for v in vals:
                if isinstance(v, str) and v.strip() and v not in bucket:
                    bucket.append(v)
    return norm_anchors


def _is_archived_spec_path(norm_path: str) -> bool:
    low = norm_path.lower().lstrip("/")
    return (
        low.startswith("specs/archive/")
        or low.startswith("archive/")
        or "/specs/archive/" in f"/{low}"
    )


def _load_spec_index(
    workspace_root: Path | None,
    specs_dir: Path | None,
    spec_map: dict[str, dict] | None,
    require_spec: bool | None,
) -> tuple[bool, Path | None, Path | None, Path | None, dict[str, dict], dict[str, dict]]:
    ws_resolved = workspace_root.expanduser().resolve() if workspace_root is not None else None
    resolved_specs_dir = (
        specs_dir.expanduser().resolve()
        if specs_dir is not None
        else ((ws_resolved / "specs") if ws_resolved is not None else None)
    )
    active = (
        require_spec
        if require_spec is not None
        else (
            spec_map is not None
            or specs_dir is not None
            or (resolved_specs_dir is not None and resolved_specs_dir.is_dir())
        )
    )
    active_by_key: dict[str, dict] = {}
    archived_by_key: dict[str, dict] = {}
    scan_root: Path | None = None

    if not active:
        return False, ws_resolved, resolved_specs_dir, scan_root, active_by_key, archived_by_key

    if spec_map is not None:
        for raw_key, sp in spec_map.items():
            if not isinstance(sp, dict):
                continue
            nk = normalize_target_file(str(raw_key))
            if _is_archived_spec_path(nk):
                archived_by_key[nk] = sp
                continue
            if nk:
                active_by_key[nk] = sp
            if rel := normalize_target_file(str(sp.get("rel_path") or "")):
                if _is_archived_spec_path(rel):
                    archived_by_key[rel] = sp
                else:
                    active_by_key.setdefault(rel, sp)
            if fname := str(sp.get("filename") or "").strip():
                active_by_key.setdefault(f"specs/{fname}", sp)
        return True, ws_resolved, resolved_specs_dir, scan_root, active_by_key, archived_by_key

    if resolved_specs_dir is not None and resolved_specs_dir.is_dir():
        scan_root = (
            ws_resolved
            if (ws_resolved is not None and resolved_specs_dir.is_relative_to(ws_resolved))
            else resolved_specs_dir.parent
        )
        for sp in scan_md_dir(resolved_specs_dir, scan_root):
            if rel := normalize_target_file(str(sp.get("rel_path") or "")):
                active_by_key[rel] = sp
            if fname := str(sp.get("filename") or "").strip():
                active_by_key.setdefault(f"specs/{fname}", sp)
        for sp in scan_md_dir(resolved_specs_dir / "archive", scan_root):
            if rel := normalize_target_file(str(sp.get("rel_path") or "")):
                archived_by_key[rel] = sp
            if fname := str(sp.get("filename") or "").strip():
                archived_by_key.setdefault(f"specs/archive/{fname}", sp)

    return True, ws_resolved, resolved_specs_dir, scan_root, active_by_key, archived_by_key


def _resolve_spec_for_task(
    raw_source: str,
    *,
    ws_resolved: Path | None,
    resolved_specs_dir: Path | None,
    scan_root: Path | None,
    active_by_key: dict[str, dict],
    archived_by_key: dict[str, dict],
) -> tuple[str, dict | None]:
    norm = normalize_target_file(raw_source)
    if not norm:
        return "missing", None
    if _is_archived_spec_path(norm) or norm in archived_by_key:
        return "archived", archived_by_key.get(norm)
    if norm.startswith("../"):
        if ws_resolved is not None and resolved_specs_dir is not None and scan_root is not None:
            cand = (ws_resolved / "tasks" / norm).resolve()
            archive_dir = (resolved_specs_dir / "archive").resolve()
            if cand.is_relative_to(archive_dir):
                return "archived", None
            if cand.is_relative_to(resolved_specs_dir) and cand.is_file():
                rel_key = normalize_target_file(cand.relative_to(scan_root).as_posix())
                if rel_key in active_by_key:
                    return "active", active_by_key[rel_key]
            return "missing", None
        trimmed = norm
        while trimmed.startswith("../"):
            trimmed = trimmed[3:]
        if _is_archived_spec_path(trimmed) or trimmed in archived_by_key:
            return "archived", archived_by_key.get(trimmed)
        if trimmed in active_by_key:
            return "active", active_by_key[trimmed]
        return "missing", None
    if norm in active_by_key:
        return "active", active_by_key[norm]
    return "missing", None


def validate_waves(
    tasks: list[dict],
    projects_cfg: dict | list | set | tuple | None = None,
    *,
    workspace_root: Path | None = None,
    specs_dir: Path | None = None,
    spec_map: dict[str, dict] | None = None,
    require_spec: bool | None = None,
) -> dict:
    """Valide un lot de tasks selon les règles fail-closed (vagues, fichiers, DAG, ancres, <= 5 code, Spec)."""
    errors: list[str] = []
    warnings: list[str] = []
    spec_active, ws_resolved, resolved_specs_dir, scan_root, active_specs, archived_specs = _load_spec_index(
        workspace_root, specs_dir, spec_map, require_spec
    )
    known_ids = _extract_known_project_ids(projects_cfg, workspace_root=ws_resolved)

    task_map: dict[str, dict] = {}
    wave_map: dict[str, int] = {}
    deps_map: dict[str, list[str]] = {}
    waves_grouped: dict[int, list[str]] = {}
    wave_project_owner: dict[tuple[int, str], str] = {}
    wave_file_owner: dict[tuple[int, str, str], str] = {}

    for idx, task in enumerate(tasks):
        if not isinstance(task, dict):
            errors.append(f"Task #{idx} invalide : objet dict attendu.")
            continue
        tid = _task_id(task, idx)
        if tid in task_map:
            errors.append(f"Identifiant de task dupliqué : `{tid}`.")
            continue
        task_map[tid] = task

        raw_wave = task.get("wave")
        valid_wave = isinstance(raw_wave, int) and not isinstance(raw_wave, bool) and raw_wave >= 1
        if not valid_wave:
            detail = task.get("wave_raw") if task.get("wave_raw") is not None else raw_wave
            errors.append(f"Task `{tid}` : vague invalide ({detail!r}, entier >= 1 requis).")
        else:
            wave_map[tid] = raw_wave
            waves_grouped.setdefault(raw_wave, []).append(tid)

        target_proj = str(task.get("target_project") or "").strip()
        if not target_proj:
            errors.append(f"Task `{tid}` : `target_project` manquant ou vide.")
        elif known_ids is not None and target_proj not in known_ids:
            errors.append(f"Task `{tid}` : dépôt cible `{target_proj}` inconnu dans `projects.json`.")
        elif valid_wave:
            wp_key = (raw_wave, target_proj)
            if wp_key in wave_project_owner:
                errors.append(
                    f"Vague {raw_wave} : collision sur le dépôt `{target_proj}` "
                    f"entre `{wave_project_owner[wp_key]}` et `{tid}` (max 1 task/dépôt/vague)."
                )
            else:
                wave_project_owner[wp_key] = tid

        norm_files: list[str] = []
        for raw_f in task.get("target_files") or []:
            nf = normalize_target_file(str(raw_f))
            if nf and nf not in norm_files:
                norm_files.append(nf)

        if valid_wave:
            for nf in norm_files:
                wf_key = (raw_wave, target_proj, nf)
                if wf_key in wave_file_owner:
                    errors.append(
                        f"Vague {raw_wave} (`{target_proj}`) : fichier cible `{nf}` partagé entre "
                        f"`{wave_file_owner[wf_key]}` et `{tid}`."
                    )
                else:
                    wave_file_owner[wf_key] = tid

        norm_anchors = _normalize_task_anchors(task.get("anchors"))
        code_files = [nf for nf in norm_files if not is_non_code_file(nf)]
        if len(code_files) > MAX_CODE_FILES_PER_TASK:
            errors.append(
                f"Task `{tid}` : {len(code_files)} fichiers code cibles > plafond {MAX_CODE_FILES_PER_TASK} (hors tests/docs)."
            )
        for cf in code_files:
            file_anchors = norm_anchors.get(cf) or []
            if not any(HYBRID_ANCHOR_RE.search(a) for a in file_anchors):
                errors.append(f"Task `{tid}` : ancre hybride (`::` ou `~L`) manquante pour le fichier code `{cf}`.")

        deps = [
            str(d).strip()[:-3] if str(d).strip().endswith(".md") else str(d).strip()
            for d in (task.get("dependencies") or [])
            if str(d).strip()
        ]
        deps_map[tid] = deps

        raw_profile = task.get("workflow_profile")
        if raw_profile is None:
            raw_profile = task.get("profile")
        profile_str = str(raw_profile or "").strip()
        if profile_str and profile_str.lower() not in ALLOWED_WORKFLOW_PROFILES:
            errors.append(
                f"Task `{tid}` : `workflow_profile` invalide ({profile_str!r}, attendu : quick | standard | deep)."
            )

        if spec_active:
            task_spec_id = str(task.get("spec_id") or "").strip()
            if not task_spec_id:
                errors.append(f"Task `{tid}` : `Spec ID` manquant.")
            task_spec_src = str(task.get("spec_source") or "").strip()
            if not task_spec_src:
                errors.append(f"Task `{tid}` : `Spec source` manquant.")
            else:
                kind, spec_obj = _resolve_spec_for_task(
                    task_spec_src,
                    ws_resolved=ws_resolved,
                    resolved_specs_dir=resolved_specs_dir,
                    scan_root=scan_root,
                    active_by_key=active_specs,
                    archived_by_key=archived_specs,
                )
                if kind != "active" or spec_obj is None:
                    errors.append(f"Task `{tid}` : `Spec source` introuvable ou archivée (`{task_spec_src}`).")
                else:
                    spec_status = str(spec_obj.get("status") or "unknown").strip()
                    if spec_status.lower() != "validated":
                        errors.append(
                            f"Task `{tid}` : spec `{task_spec_src}` non validée (statut=`{spec_status}`, attendu: `validated`)."
                        )
                    spec_spec_id = str(spec_obj.get("spec_id") or "").strip()
                    if task_spec_id and spec_spec_id and task_spec_id != spec_spec_id:
                        errors.append(
                            f"Task `{tid}` : incohérence `Spec ID` (`{task_spec_id}` != `{spec_spec_id}`)."
                        )
            ac_raw = task.get("acceptance_criteria")
            if not isinstance(ac_raw, list) or not any(str(x).strip() for x in ac_raw):
                errors.append(f"Task `{tid}` : `Acceptance Criteria Covered` manquant ou vide.")

    for tid, deps in deps_map.items():
        for dep in deps:
            if dep == tid:
                errors.append(f"Task `{tid}` : auto-dépendance interdite (`{dep}`).")
            elif dep not in task_map:
                errors.append(f"Task `{tid}` : dépendance introuvable (`{dep}`).")
            elif tid in wave_map and dep in wave_map and wave_map[dep] >= wave_map[tid]:
                errors.append(
                    f"Task `{tid}` (vague {wave_map[tid]}) dépend de `{dep}` (vague {wave_map[dep]}) : "
                    "wave(dep) doit être < wave(task)."
                )

    white, gray, black = 0, 1, 2
    color: dict[str, int] = {tid: white for tid in task_map}
    stack: list[str] = []
    seen_cycles: set[tuple[str, ...]] = set()

    def _dfs(node: str) -> None:
        color[node] = gray
        stack.append(node)
        for dep in deps_map.get(node, []):
            if dep == node or dep not in task_map:
                continue
            st = color[dep]
            if st == gray:
                cycle = stack[stack.index(dep) :] + [dep]
                sig = tuple(sorted(cycle[:-1]))
                if sig not in seen_cycles:
                    seen_cycles.add(sig)
                    errors.append(f"Cycle de dépendances détecté : {' -> '.join(cycle)}.")
            elif st == white:
                _dfs(dep)
        stack.pop()
        color[node] = black

    for tid in task_map:
        if color[tid] == white:
            _dfs(tid)

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "task_count": len(tasks),
        "waves": {w: sorted(tids) for w, tids in sorted(waves_grouped.items())},
    }


def _resolve_task_plan_file(task: dict, tid: str, *, workspace_root: Path, tasks_dir: Path | None = None) -> str:
    if raw_plan := str(task.get("plan_file") or "").strip():
        return str(Path(raw_plan).expanduser().resolve())
    if filename := str(task.get("filename") or "").strip():
        if tasks_dir is not None:
            cand = (tasks_dir / filename).resolve()
            if cand.is_file():
                return str(cand)
    if rel_path := str(task.get("rel_path") or "").strip():
        cand = (workspace_root / rel_path).resolve()
        if cand.is_file() or tasks_dir is None:
            return str(cand)
    base_tasks = tasks_dir.resolve() if tasks_dir is not None else (workspace_root / "tasks").resolve()
    name = str(task.get("filename") or f"{tid}.md").strip()
    return str((base_tasks / name).resolve())


def export_wave(
    tasks: list[dict],
    wave: int,
    *,
    workspace_root: Path,
    projects_cfg: dict | list | None = None,
    tasks_dir: Path | None = None,
    specs_dir: Path | None = None,
    spec_map: dict[str, dict] | None = None,
    require_spec: bool | None = None,
) -> dict:
    """Compile une vague validée en manifeste JSON `wave_plan_v1` (fail-closed)."""
    if not isinstance(wave, int) or isinstance(wave, bool) or wave < 1:
        raise ValueError(f"Numéro de vague invalide ({wave!r}, entier >= 1 requis).")

    ws_resolved = workspace_root.expanduser().resolve()
    project_specs = _extract_project_specs(projects_cfg, base_dir=ws_resolved)
    if project_specs is None:
        raise ValueError("Configuration `projects.json` manquante pour résoudre `repo_root`.")

    validation = validate_waves(
        tasks,
        projects_cfg=projects_cfg,
        workspace_root=ws_resolved,
        specs_dir=specs_dir,
        spec_map=spec_map,
        require_spec=require_spec,
    )
    if not validation["ok"]:
        raise ValueError("Validation des vagues échouée : " + " ; ".join(validation["errors"]))

    selected: list[tuple[str, dict]] = [
        (_task_id(task, idx), task) for idx, task in enumerate(tasks) if task.get("wave") == wave
    ]
    if not selected:
        raise ValueError(f"Vague {wave} vide : aucune task trouvée.")

    selected.sort(key=lambda item: item[0])
    exported_tasks: list[dict] = []
    wave_names: list[str] = []
    for tid, task in selected:
        status_raw = str(task.get("status") or "").strip()
        if status_raw.lower() in BLOCKED_EXPORT_STATUSES:
            raise ValueError(f"Task `{tid}` : statut `{status_raw}` bloqué pour export.")

        repo_id = str(task.get("target_project") or "").strip()
        spec = project_specs.get(repo_id)
        if spec is None:
            raise ValueError(f"Task `{tid}` : dépôt cible `{repo_id}` introuvable dans `projects.json`.")
        repo_root = spec.get("repo_root")
        if not isinstance(repo_root, Path) or not repo_root.is_dir():
            raise ValueError(f"Task `{tid}` : `repo_root` absent ou introuvable pour `{repo_id}` ({repo_root}).")

        task_branch = str(task.get("expected_branch") or "").strip()
        expected_branch = task_branch or str(spec.get("default_dev_branch") or "dev")

        raw_profile = task.get("workflow_profile")
        if raw_profile is None:
            raw_profile = task.get("profile")
        profile = str(raw_profile or "").strip().lower() or "standard"

        norm_files: list[str] = []
        for raw_f in task.get("target_files") or []:
            nf = normalize_target_file(str(raw_f))
            if nf and nf not in norm_files:
                norm_files.append(nf)

        item_out: dict = {
            "id": tid,
            "title": str(task.get("title") or tid).strip() or tid,
            "repo_id": repo_id,
            "repo_root": str(repo_root),
            "expected_branch": expected_branch,
            "profile": profile,
            "plan_file": _resolve_task_plan_file(task, tid, workspace_root=ws_resolved, tasks_dir=tasks_dir),
            "target_files": norm_files,
            "status": status_raw or "unknown",
        }
        if t_wname := str(task.get("wave_name") or "").strip():
            item_out["wave_name"] = t_wname
            if t_wname not in wave_names:
                wave_names.append(t_wname)
        exported_tasks.append(item_out)

    plan_out: dict = {
        "schema_version": WAVE_PLAN_SCHEMA_VERSION,
        "workspace": str(ws_resolved),
        "wave": wave,
        "tasks": exported_tasks,
    }
    if wave_names:
        plan_out["wave_name"] = wave_names[0]
    return plan_out


def build_parser() -> argparse.ArgumentParser:
    """Construit le parseur CLI de validation et d'export des vagues."""
    parser = argparse.ArgumentParser(description="Valide le DAG, les vagues et les ancres des tasks Gravity Architect.")
    parser.add_argument("--check-waves", action="store_true", help="Exécute la validation fail-closed des vagues (actif par défaut).")
    parser.add_argument("--export-wave", type=int, default=None, help="Exporte la vague <N> au format JSON wave_plan_v1 (fail-closed).")
    parser.add_argument("--out", type=Path, default=None, help="Chemin de sortie optionnel pour --export-wave.")
    parser.add_argument("--workspace", type=Path, default=None, help="Racine de l'atelier contenant projects.json et tasks/.")
    parser.add_argument("--tasks-dir", type=Path, default=None, help="Répertoire tasks/ explicite à valider.")
    parser.add_argument("--config", type=Path, default=None, help="Chemin explicite vers projects.json.")
    parser.add_argument("--json", action="store_true", help="Sortie JSON structurée.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Point d'entrée CLI pour `core/waves.py`."""
    configure_utf8_stdio()
    args = build_parser().parse_args(argv)
    try:
        if args.out is not None and args.export_wave is None:
            raise ValueError("--out requiert --export-wave <N>.")

        if args.tasks_dir is not None:
            tasks_dir = args.tasks_dir.expanduser().resolve()
            concept_root = args.workspace.expanduser().resolve() if args.workspace is not None else tasks_dir.parent
            cfg_path = args.config.expanduser().resolve() if args.config is not None else (concept_root / "projects.json")
            projects_cfg = load_config(cfg_path) if cfg_path.is_file() else None
        else:
            concept_root, cfg_path = resolve_workspace_root(config_arg=args.config, workspace_arg=args.workspace)
            tasks_dir = concept_root / "tasks"
            projects_cfg = load_config(cfg_path) if cfg_path.is_file() else None

        scan_root = concept_root if tasks_dir.is_relative_to(concept_root) else tasks_dir.parent
        tasks = scan_md_dir(tasks_dir, scan_root)

        if args.export_wave is not None:
            payload = export_wave(
                tasks,
                args.export_wave,
                workspace_root=concept_root,
                projects_cfg=projects_cfg,
                tasks_dir=tasks_dir,
            )
            serialized = json.dumps(payload, indent=2, ensure_ascii=False)
            if args.out is not None:
                out_path = args.out.expanduser().resolve()
                write_utf8(out_path, serialized + "\n")
                if args.json:
                    print(serialized)
                else:
                    print(f"[PASS] Vague {args.export_wave} exportée vers {out_path} ({len(payload['tasks'])} task(s)).")
            else:
                print(serialized)
            return 0

        result = validate_waves(tasks, projects_cfg=projects_cfg, workspace_root=concept_root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "errors": [str(exc)], "warnings": [], "task_count": 0, "waves": {}}, ensure_ascii=False))
        else:
            label = "Export de la vague" if args.export_wave is not None else "Validation des vagues"
            print(f"[erreur] {label} impossible : {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif result["ok"]:
        print(f"[PASS] Validation des vagues réussie ({result['task_count']} task(s), {len(result['waves'])} vague(s)).")
    else:
        print(f"[FAIL] Validation des vagues échouée ({len(result['errors'])} erreur(s)) :", file=sys.stderr)
        for err in result["errors"]:
            print(f"  - {err}", file=sys.stderr)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
