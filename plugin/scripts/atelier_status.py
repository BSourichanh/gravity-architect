#!/usr/bin/env python3
"""Synthèse lecture seule zéro-écriture d'un atelier Gravity Architect (100 % stdlib Python 3.10+)."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from core.delta import collect_atelier_hygiene_alerts, evaluate_hot_budgets  # noqa: E402
from core.io_utils import (  # noqa: E402
    collect_concept_artifacts,
    configure_utf8_stdio,
    read_json_safe,
    resolve_workspace_root,
)

ACTIVE_JOB_STATUSES: tuple[str, ...] = ("queued", "claimed", "dispatched")


def resolve_bridge_db_path(
    *,
    env: dict[str, str] | None = None,
    home_dir: Path | None = None,
    bridge_db: Path | None = None,
) -> Path:
    """Résout le chemin brut vers `bridge.db` (`$GRAVITY_BRIDGE_HOME` > `$GRAVITY_HOME/bridge` > `~/.gemini/gravity/bridge`)."""
    if bridge_db is not None:
        return bridge_db.expanduser()
    env_map = env if env is not None else os.environ
    raw_bridge_home = str(env_map.get("GRAVITY_BRIDGE_HOME") or "").strip()
    if raw_bridge_home:
        return Path(raw_bridge_home).expanduser() / "bridge.db"
    raw_gravity_home = str(env_map.get("GRAVITY_HOME") or "").strip()
    if raw_gravity_home:
        return Path(raw_gravity_home).expanduser() / "bridge" / "bridge.db"
    base_home = (home_dir if home_dir is not None else Path.home()).expanduser()
    return base_home / ".gemini" / "gravity" / "bridge" / "bridge.db"


def _has_symlink_component(path: Path) -> bool:
    """Retourne True si `path` ou l'un de ses parents directs bridge/home est un lien symbolique."""
    for cand in (path, path.parent):
        try:
            if cand.is_symlink():
                return True
        except OSError:
            return True
    return False


def probe_bridge_ro(
    *,
    env: dict[str, str] | None = None,
    home_dir: Path | None = None,
    bridge_db: Path | None = None,
) -> dict[str, Any]:
    """Sonde strictement en lecture seule (`?mode=ro` + `PRAGMA query_only = ON`) sans créer `bridge.db`."""
    raw_db = resolve_bridge_db_path(env=env, home_dir=home_dir, bridge_db=bridge_db)
    base: dict[str, Any] = {
        "available": False,
        "db_path": str(raw_db),
        "open_threads": 0,
        "active_jobs": 0,
        "error": None,
    }
    if _has_symlink_component(raw_db):
        base["error"] = "Lien symbolique refusé pour bridge.db."
        return base
    if not raw_db.is_file():
        return base

    resolved_db = raw_db.resolve()
    base["db_path"] = str(resolved_db)
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(f"{resolved_db.as_uri()}?mode=ro", uri=True, timeout=1.0)
        conn.execute("PRAGMA query_only = ON")
        row_t = conn.execute("SELECT COUNT(*) FROM threads WHERE status = 'open'").fetchone()
        row_j = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'claimed', 'dispatched')"
        ).fetchone()
        base["open_threads"] = int(row_t[0] or 0) if row_t else 0
        base["active_jobs"] = int(row_j[0] or 0) if row_j else 0
        base["available"] = True
    except (sqlite3.Error, OSError) as exc:
        base["error"] = str(exc)
    finally:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass
    return base


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
    bridge: dict[str, Any],
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
    if specs or pending_tasks or bridge.get("active_jobs", 0) > 0 or bridge.get("open_threads", 0) > 0:
        actions.append(
            {
                "action": "reprendre",
                "command": "/gravity-architect <instruction>",
                "reason": "Reprendre les specs/tasks actives ou le suivi Bridge en cours.",
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


def collect_atelier_status(
    *,
    workspace_arg: Path | None = None,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    home_dir: Path | None = None,
    bridge_db: Path | None = None,
    templates_dir: Path | None = None,
) -> dict[str, Any]:
    """Collecte en lecture seule l'état complet d'un atelier (0 écriture, 0 capture metrics)."""
    bridge = probe_bridge_ro(env=env, home_dir=home_dir, bridge_db=bridge_db)

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
            "error": resolve_error or "projects.json absent.",
            "specs": [],
            "pending_tasks": [],
            "archived_specs_count": 0,
            "archived_tasks_count": 0,
            "tasks_by_wave": {},
            "tasks_by_status": {},
            "bridge": bridge,
            "hot_budgets": {},
            "hygiene_alerts": [],
            "suggested_actions": _build_suggested_actions(
                initialized=False, specs=[], pending_tasks=[], bridge=bridge
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
            "error": f"{cfg_path.name} invalide ou illisible.",
            "specs": [],
            "pending_tasks": [],
            "archived_specs_count": 0,
            "archived_tasks_count": 0,
            "tasks_by_wave": {},
            "tasks_by_status": {},
            "bridge": bridge,
            "hot_budgets": {},
            "hygiene_alerts": [f"`{cfg_path.name}` : JSON invalide ou illisible."],
            "suggested_actions": _build_suggested_actions(
                initialized=False, specs=[], pending_tasks=[], bridge=bridge
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
    ws_name = str(cfg.get("workspace_name") or "").strip() or ws_root.name

    return {
        "initialized": True,
        "workspace": str(ws_root),
        "config_path": str(cfg_path),
        "workspace_name": ws_name,
        "projects_count": len(projects_cfg),
        "error": None,
        "specs": specs,
        "pending_tasks": pending_tasks,
        "archived_specs_count": archived_specs_count,
        "archived_tasks_count": archived_tasks_count,
        "tasks_by_wave": tasks_by_wave,
        "tasks_by_status": tasks_by_status,
        "bridge": bridge,
        "hot_budgets": hot_budgets,
        "hygiene_alerts": hygiene_alerts,
        "suggested_actions": _build_suggested_actions(
            initialized=True, specs=specs, pending_tasks=pending_tasks, bridge=bridge
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

    bridge = payload.get("bridge") or {}
    if bridge.get("available"):
        lines.append(
            f"- **Bridge :** `{bridge.get('open_threads', 0)}` thread(s) ouvert(s), "
            f"`{bridge.get('active_jobs', 0)}` job(s) actif(s)"
        )
    elif bridge.get("error"):
        lines.append(f"- **Bridge :** indisponible ({bridge['error']})")
    else:
        lines.append("- **Bridge :** aucune base `bridge.db` active")

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
