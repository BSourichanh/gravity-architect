"""Validation fail-closed des vagues d'exécution (`tasks/`), DAG et ancres hybrides."""

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
)

MAX_CODE_FILES_PER_TASK = 5


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


def _extract_known_project_ids(projects_cfg: dict | list | set | tuple | None) -> set[str] | None:
    if projects_cfg is None:
        return None
    items = projects_cfg.get("projects") or [] if isinstance(projects_cfg, dict) else projects_cfg
    ids: set[str] = set()
    for item in items:
        if isinstance(item, dict):
            if pid := str(item.get("id") or "").strip():
                ids.add(pid)
        elif isinstance(item, str) and item.strip():
            ids.add(item.strip())
    return ids


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


def validate_waves(tasks: list[dict], projects_cfg: dict | list | set | tuple | None = None) -> dict:
    """Valide un lot de tasks selon les 5 règles fail-closed (vagues, fichiers, DAG, ancres, <= 5 code)."""
    errors: list[str] = []
    warnings: list[str] = []
    known_ids = _extract_known_project_ids(projects_cfg)

    task_map: dict[str, dict] = {}
    wave_map: dict[str, int] = {}
    deps_map: dict[str, list[str]] = {}
    waves_grouped: dict[int, list[str]] = {}
    wave_project_owner: dict[tuple[int, str], str] = {}
    wave_file_owner: dict[tuple[int, str], str] = {}

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
                wf_key = (raw_wave, nf)
                if wf_key in wave_file_owner:
                    errors.append(
                        f"Vague {raw_wave} : fichier cible `{nf}` partagé entre "
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

        deps = [str(d).strip()[:-3] if str(d).strip().endswith(".md") else str(d).strip() for d in (task.get("dependencies") or []) if str(d).strip()]
        deps_map[tid] = deps

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


def build_parser() -> argparse.ArgumentParser:
    """Construit le parseur CLI de validation des vagues."""
    parser = argparse.ArgumentParser(description="Valide le DAG, les vagues et les ancres des tasks Gravity Architect.")
    parser.add_argument("--check-waves", action="store_true", help="Exécute la validation fail-closed des vagues (actif par défaut).")
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
        result = validate_waves(tasks, projects_cfg=projects_cfg)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "errors": [str(exc)], "warnings": [], "task_count": 0, "waves": {}}, ensure_ascii=False))
        else:
            print(f"[erreur] Validation des vagues impossible : {exc}", file=sys.stderr)
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
