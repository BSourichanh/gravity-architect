#!/usr/bin/env python3
"""Synthèse lecture seule zéro-écriture d'un atelier Gravity Architect (100 % stdlib Python 3.10+)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from core.delta import collect_atelier_hygiene_alerts, evaluate_hot_budgets  # noqa: E402
from core.io_utils import (  # noqa: E402
    ARTIFACT_FILE_SECTIONS,
    _clean_bullet_item,
    _looks_like_file_path,
    collect_concept_artifacts,
    configure_utf8_stdio,
    normalize_target_file,
    read_json_safe,
    resolve_workspace_root,
)

STALE_SPEC_STATUSES = frozenset({"superseded", "archived", "done", "cancelled"})
_NEW_FILE_MARKER_RE = re.compile(r"\b(?:new\s+file|nouveau\s+fichier)\b", re.IGNORECASE)


def _summarize_tasks(pending_tasks: list[dict[str, Any]]) -> tuple[dict[str, dict[str, int]], dict[str, int]]:
    by_wave: dict[str, dict[str, int]] = {}
    by_status: dict[str, int] = {}

    def _sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
        w = item.get("wave")
        if isinstance(w, int) and not isinstance(w, bool) and w >= 1:
            return (0, w, str(item.get("filename") or ""))
        return (1, 0, str(item.get("filename") or ""))

    for task in sorted(pending_tasks, key=_sort_key):
        w = task.get("wave")
        wave_label = f"Vague {w}" if isinstance(w, int) and not isinstance(w, bool) and w >= 1 else "Sans vague"
        st = str(task.get("status") or "unknown").strip() or "unknown"
        wave_bucket = by_wave.setdefault(wave_label, {})
        wave_bucket[st] = wave_bucket.get(st, 0) + 1
        by_status[st] = by_status.get(st, 0) + 1
    return by_wave, by_status


def _build_suggested_actions(
    *,
    initialized: bool,
    specs: list[dict[str, Any]],
    pending_tasks: list[dict[str, Any]],
) -> list[dict[str, str]]:
    if not initialized:
        return [
            {
                "action": "init",
                "command": "/gravity-architect init",
                "reason": "Initialiser un atelier Hot/Cold dans le dossier courant.",
            },
            {
                "action": "instruction",
                "command": "/gravity-architect <instruction>",
                "reason": "Cadrer un nouveau besoin après initialisation.",
            },
        ]

    actions: list[dict[str, str]] = []
    if specs or pending_tasks:
        actions.append(
            {
                "action": "reprendre",
                "command": "/gravity-architect <instruction>",
                "reason": "Reprendre les specs/tasks actives en cours.",
            }
        )
    actions.append(
        {
            "action": "instruction",
            "command": "/gravity-architect <instruction>",
            "reason": "Lancer ou poursuivre un cycle 4 phases (Conception → Planification → Production → Validation).",
        }
    )
    actions.append(
        {
            "action": "sync",
            "command": "/gravity-architect sync",
            "reason": "Synchroniser les dépôts suivis et mettre à jour le micro-delta.",
        }
    )
    return actions


def _extract_new_file_targets(task: dict[str, Any], ws_root: Path) -> list[str]:
    preset = task.get("new_file_targets")
    if isinstance(preset, list):
        return [nf for raw in preset if (nf := normalize_target_file(str(raw)))]
    rel_path = str(task.get("rel_path") or "").strip()
    if not rel_path:
        return []
    task_file = ws_root / rel_path
    if not task_file.is_file():
        return []
    try:
        text = task_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    in_section = False
    out: list[str] = []
    for line in text.splitlines():
        if hm := re.match(r"^#{1,2}\s+(.+?)\s*$", line):
            in_section = line.startswith("## ") and hm.group(1).strip().lower() in ARTIFACT_FILE_SECTIONS
            continue
        if not in_section or not _NEW_FILE_MARKER_RE.search(line):
            continue
        if bm := re.match(r"^\s*[-*+]\s+(.+?)\s*$", line):
            item = _clean_bullet_item(bm.group(1))
            nf = normalize_target_file(item)
            if _looks_like_file_path(nf) and nf not in out:
                out.append(nf)
    return out


def _detect_stale_ready_tasks(
    ws_root: Path, cfg: dict[str, Any], artifacts: dict[str, Any]
) -> list[str]:
    """Détecte de façon déterministe (`AUD-05-09`) les tasks `ready` périmées ou déjà livrées (RO strict)."""
    specs = artifacts.get("specs") or []
    archived_specs = artifacts.get("archived_specs") or []
    pending_tasks = artifacts.get("pending_tasks") or []

    active_by_key: dict[str, dict[str, Any]] = {}
    active_by_id: dict[str, dict[str, Any]] = {}
    for sp in specs:
        if not isinstance(sp, dict):
            continue
        if rel := normalize_target_file(str(sp.get("rel_path") or "")):
            active_by_key[rel] = sp
        if fname := str(sp.get("filename") or "").strip():
            active_by_key.setdefault(f"specs/{fname}", sp)
            active_by_key.setdefault(fname, sp)
        if sid := str(sp.get("spec_id") or "").strip():
            active_by_id[sid] = sp

    archived_by_key: dict[str, dict[str, Any]] = {}
    archived_by_id: dict[str, dict[str, Any]] = {}
    for sp in archived_specs:
        if not isinstance(sp, dict):
            continue
        if rel := normalize_target_file(str(sp.get("rel_path") or "")):
            archived_by_key[rel] = sp
        if fname := str(sp.get("filename") or "").strip():
            archived_by_key.setdefault(f"specs/archive/{fname}", sp)
            archived_by_key.setdefault(fname, sp)
        if sid := str(sp.get("spec_id") or "").strip():
            archived_by_id[sid] = sp

    repo_roots: dict[str, Path] = {}
    if aid := str(cfg.get("atelier_id") or "").strip():
        repo_roots[aid] = ws_root
    repo_roots.setdefault(ws_root.name, ws_root)
    for item in cfg.get("projects") or []:
        if isinstance(item, dict) and (pid := str(item.get("id") or "").strip()):
            if raw_path := str(item.get("path") or "").strip():
                p = Path(raw_path).expanduser()
                repo_roots[pid] = p.resolve() if p.is_absolute() else (ws_root / p).resolve()

    changelog_cache: dict[Path, str] = {}
    alerts: list[str] = []
    for task in pending_tasks:
        if not isinstance(task, dict):
            continue
        if str(task.get("status") or "").strip().lower() != "ready":
            continue
        raw_tid = str(task.get("id") or task.get("filename") or "").strip()
        tid = raw_tid[:-3] if raw_tid.endswith(".md") else raw_tid
        spec_src = str(task.get("spec_source") or "").strip()
        spec_id = str(task.get("spec_id") or "").strip()

        if spec_src:
            norm_src = normalize_target_file(spec_src)
            while norm_src.startswith("../"):
                norm_src = norm_src[3:]
            if norm_src.startswith("specs/archive/") or norm_src.startswith("archive/") or norm_src in archived_by_key:
                alerts.append(f"AUD-05-09: task `{tid}` (ready) pointe sur une spec archivée (`{spec_src}`).")
            else:
                sp = active_by_key.get(norm_src)
                if sp is None:
                    alerts.append(f"AUD-05-09: task `{tid}` (ready) pointe sur une spec introuvable (`{spec_src}`).")
                else:
                    sp_status = str(sp.get("status") or "").strip().lower()
                    if sp_status in STALE_SPEC_STATUSES:
                        alerts.append(
                            f"AUD-05-09: task `{tid}` (ready) pointe sur une spec {sp_status} (`{spec_src}`)."
                        )
        elif spec_id:
            if spec_id in archived_by_id:
                alerts.append(f"AUD-05-09: task `{tid}` (ready) liée à une spec archivée (`{spec_id}`).")
            elif (sp := active_by_id.get(spec_id)) is not None:
                sp_status = str(sp.get("status") or "").strip().lower()
                if sp_status in STALE_SPEC_STATUSES:
                    alerts.append(f"AUD-05-09: task `{tid}` (ready) liée à une spec {sp_status} (`{spec_id}`).")

        target_proj = str(task.get("target_project") or "").strip()
        repo_root = repo_roots.get(target_proj)
        task_id = str(task.get("task_id") or "").strip()
        if task_id and repo_root is not None:
            chg_path = repo_root / "CHANGELOG.md"
            if chg_path.is_file():
                if chg_path not in changelog_cache:
                    try:
                        changelog_cache[chg_path] = chg_path.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        changelog_cache[chg_path] = ""
                if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(task_id)}(?![A-Za-z0-9_-])", changelog_cache[chg_path]):
                    alerts.append(
                        f"AUD-05-09: task `{tid}` (`{task_id}`, ready) déjà livrée dans `{target_proj}/CHANGELOG.md`."
                    )

        if repo_root is not None and repo_root.is_dir():
            new_files = _extract_new_file_targets(task, ws_root)
            if new_files and all((repo_root / nf).is_file() for nf in new_files):
                alerts.append(
                    f"AUD-05-09: task `{tid}` (ready) a des ancres nouveau fichier déjà présentes dans `{target_proj}`."
                )

    return alerts


def collect_atelier_status(
    *,
    workspace_arg: Path | None = None,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    home_dir: Path | None = None,
    templates_dir: Path | None = None,
) -> dict[str, Any]:
    """Collecte en lecture seule l'état complet d'un atelier (0 écriture, 0 capture metrics)."""
    ws_root: Path | None = None
    cfg_path: Path | None = None
    resolve_error: str | None = None
    try:
        ws_root, cfg_path = resolve_workspace_root(
            workspace_arg=workspace_arg, cwd=cwd, env=env, home_dir=home_dir
        )
    except (FileNotFoundError, ValueError, OSError) as exc:
        resolve_error = str(exc)

    if ws_root is None or cfg_path is None or not cfg_path.is_file():
        return {
            "initialized": False,
            "workspace": str(ws_root) if ws_root is not None else None,
            "config_path": str(cfg_path) if cfg_path is not None else None,
            "workspace_name": None,
            "projects_count": 0,
            "projects": [],
            "error": resolve_error or "projects.json absent.",
            "specs": [],
            "pending_tasks": [],
            "archived_specs_count": 0,
            "archived_tasks_count": 0,
            "tasks_by_wave": {},
            "tasks_by_status": {},
            "hot_budgets": {},
            "hygiene_alerts": [],
            "suggested_actions": _build_suggested_actions(
                initialized=False, specs=[], pending_tasks=[]
            ),
        }

    cfg = read_json_safe(cfg_path)
    if cfg is None:
        return {
            "initialized": False,
            "workspace": str(ws_root),
            "config_path": str(cfg_path),
            "workspace_name": ws_root.name,
            "projects_count": 0,
            "projects": [],
            "error": f"{cfg_path.name} invalide ou illisible.",
            "specs": [],
            "pending_tasks": [],
            "archived_specs_count": 0,
            "archived_tasks_count": 0,
            "tasks_by_wave": {},
            "tasks_by_status": {},
            "hot_budgets": {},
            "hygiene_alerts": [f"`{cfg_path.name}` : JSON invalide ou illisible."],
            "suggested_actions": _build_suggested_actions(
                initialized=False, specs=[], pending_tasks=[]
            ),
        }

    artifacts = collect_concept_artifacts(ws_root)
    specs = artifacts.get("specs") or []
    pending_tasks = artifacts.get("pending_tasks") or []
    archived_specs_count = len(artifacts.get("archived_specs") or [])
    archived_tasks_count = len(artifacts.get("archived_tasks") or [])
    tasks_by_wave, tasks_by_status = _summarize_tasks(pending_tasks)

    projects_cfg = [p for p in (cfg.get("projects") or []) if isinstance(p, dict)]
    project_ids = [str(p["id"]) for p in projects_cfg if p.get("id")]
    watch_impacts = [
        str(w["impact_file"])
        for w in (cfg.get("watches") or [])
        if isinstance(w, dict) and w.get("impact_file")
    ]
    hot_budgets = evaluate_hot_budgets(
        ws_root, cfg.get("hot_budgets"), project_ids, watch_impact_files=watch_impacts
    )
    hygiene_alerts = collect_atelier_hygiene_alerts(
        ws_root, templates_dir=templates_dir, hot_budgets=hot_budgets
    )
    hygiene_alerts.extend(_detect_stale_ready_tasks(ws_root, cfg, artifacts))
    ws_name = str(cfg.get("workspace_name") or "").strip() or ws_root.name

    return {
        "initialized": True,
        "workspace": str(ws_root),
        "config_path": str(cfg_path),
        "workspace_name": ws_name,
        "projects_count": len(projects_cfg),
        "projects": [str(p.get("id") or "") for p in projects_cfg if isinstance(p, dict) and p.get("id")],
        "error": None,
        "specs": specs,
        "pending_tasks": pending_tasks,
        "archived_specs_count": archived_specs_count,
        "archived_tasks_count": archived_tasks_count,
        "tasks_by_wave": tasks_by_wave,
        "tasks_by_status": tasks_by_status,
        "hot_budgets": hot_budgets,
        "hygiene_alerts": hygiene_alerts,
        "suggested_actions": _build_suggested_actions(
            initialized=True, specs=specs, pending_tasks=pending_tasks
        ),
    }


def format_status_markdown(payload: dict[str, Any]) -> str:
    """Formate l'état consultatif de l'atelier en Markdown concis (zéro écriture)."""
    lines: list[str] = ["# Gravity Architect — État de l'atelier *(lecture seule)*", ""]
    if not payload.get("initialized"):
        lines.append("- **Atelier :** non initialisé (`projects.json` absent)")
        if payload.get("error"):
            lines.append(f"- **Détail :** {payload['error']}")
    else:
        lines.append(
            f"- **Atelier :** `{payload.get('workspace_name') or 'Atelier'}` "
            f"(`{payload.get('projects_count', 0)}` projet(s) suivi(s))"
        )
        lines.append(f"- **Chemin :** `{payload.get('workspace')}`")
        projects = [str(p) for p in (payload.get("projects") or []) if str(p).strip()]
        if projects:
            shown_projects = ", ".join(f"`{pid}`" for pid in projects[:10])
            extra = f" *(+{len(projects) - 10} autre(s))*" if len(projects) > 10 else ""
            lines.append(f"- **Projets suivis ({len(projects)}) :** {shown_projects}{extra}")

        specs = payload.get("specs") or []
        if specs:
            lines.append(f"- **Specs actives ({len(specs)}) :**")
            for sp in specs[:10]:
                lines.append(
                    f"  - `{sp.get('filename') or sp.get('id')}` "
                    f"(`{sp.get('status', 'unknown')}`, cible : `{sp.get('target_project') or 'n/a'}`)"
                )
        else:
            lines.append("- **Specs actives :** aucune")

        pending = payload.get("pending_tasks") or []
        tasks_by_wave = payload.get("tasks_by_wave") or {}
        if pending:
            lines.append(f"- **Tasks actives ({len(pending)}) :**")
            for wave_label, statuses in tasks_by_wave.items():
                summary = ", ".join(f"`{st}`: {cnt}" for st, cnt in sorted(statuses.items()))
                lines.append(f"  - **{wave_label}** : {summary}")
        else:
            lines.append("- **Tasks actives :** aucune")

    alerts = payload.get("hygiene_alerts") or []
    if alerts:
        lines.extend(["", "## Alertes hygiène", *(f"- {a}" for a in alerts[:10])])
        if len(alerts) > 10:
            lines.append(f"- *(+{len(alerts) - 10} autre(s) alerte(s))*")
    elif payload.get("initialized"):
        lines.append("- **Hygiène :** aucune alerte")

    actions = payload.get("suggested_actions") or []
    if actions:
        lines.extend(["", "## Actions suggérées"])
        for act in actions:
            lines.append(f"- `{act['command']}` — {act['reason']}")

    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    """Construit le parseur CLI pour `atelier_status.py`."""
    parser = argparse.ArgumentParser(description="Inspecte en lecture seule l'état courant d'un atelier Gravity Architect.")
    parser.add_argument("--workspace", type=Path, default=None, help="Chemin explicite vers l'atelier.")
    parser.add_argument("--json", action="store_true", help="Émet la sortie au format JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Point d'entrée CLI lecture seule."""
    configure_utf8_stdio()
    args = build_parser().parse_args(argv)
    payload = collect_atelier_status(workspace_arg=args.workspace)
    if args.json:
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(format_status_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
