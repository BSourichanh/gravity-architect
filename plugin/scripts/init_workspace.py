#!/usr/bin/env python3
"""Initialiseur idempotent, découverte et ajout incrémental Gravity Architect (façade)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent
TEMPLATES_DIR = PLUGIN_ROOT / "templates"

for _p in (str(SCRIPT_DIR), str(PLUGIN_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _shared.atomic_io import write_json_atomic, write_text_atomic  # noqa: E402
from _shared.file_lock import exclusive_file_lock  # noqa: E402
from _shared.path_safety import ensure_safe_dir, is_symlink_or_junction  # noqa: E402
from core.discovery import (  # noqa: E402
    PRODUCT_MANIFEST_FILES,
    PROJECT_ID_RE,
    TOML_DESC_RE,
    build_project_entry as _build_project_entry,
    compute_portable_path as _compute_portable_path,
    detect_git_branches as _detect_git_branches,
    detect_product_repo_manifests as _detect_product_repo_manifests,
    discover_repositories,
    extract_pyproject_description as _extract_pyproject_description,
    extract_readme_summary as _extract_readme_summary,
    extract_role as _extract_role,
    inspect_project_dir,
    is_git_repo as _is_git_repo,
    normalize_project_id as _normalize_project_id,
    parse_project_specs as _parse_project_specs,
    parse_target_spec as _parse_target_spec,
    render_project_card as _render_project_card,
    resolve_target_dir as _resolve_target_dir,
)
from core.io_utils import (  # noqa: E402
    configure_utf8_stdio as _configure_stdio,
    deploy_file as _deploy_file,
    humanize_id as _humanize_id,
    read_json_safe as _read_json_safe,
    truncate_text as _truncate_text,
    write_utf8 as _write_utf8,
)
from core.watches import (  # noqa: E402
    ANTIGRAVITY_CHANGELOG_URL,
    ANTIGRAVITY_IMPACT_BUDGET,
    ANTIGRAVITY_WATCH_SURFACES,
    DEFAULT_WATCH_KEYWORDS,
    build_antigravity_watch as _build_antigravity_watch,
    make_watch_url_entry as _make_watch_url_entry,
    parse_watch_urls as _parse_watch_urls,
)
from sync_tracking import (  # noqa: E402
    derive_validator_script,
    detect_plugin_manifest,
    detect_version_source,
    register_atelier,
    resolve_ateliers_registry_path,
    run_readonly_cmd,
    run_sync,
    workspace_lock_path,
)

DEFAULT_WORKSPACE_NAME = "Mon Atelier Projets"
GENERIC_WORKSPACE_DIR_NAMES = frozenset(
    {"", ".", "/", "tmp", "temp", "workspace", "projects", "repos", "github"}
)


def _derive_default_workspace_name(ws_root: Path) -> str:
    """Dérive un nom d'atelier lisible depuis `ws_root` hors noms génériques."""
    raw_name = ws_root.name.strip()
    if raw_name.lower() in GENERIC_WORKSPACE_DIR_NAMES:
        return DEFAULT_WORKSPACE_NAME
    return _humanize_id(raw_name) or DEFAULT_WORKSPACE_NAME


def _deploy_atomic(dst: Path, content: str, *, force: bool) -> str:
    if is_symlink_or_junction(dst):
        raise ValueError(f"Refus d'écriture sur symlink/junction : {dst}")
    if dst.exists():
        if not force:
            return "skipped"
        write_text_atomic(dst, content)
        return "updated"
    write_text_atomic(dst, content)
    return "created"


def init_workspace(
    workspace: Path,
    *,
    name: str | None = None,
    preset: str | None = None,
    projects: list[tuple[str, str] | tuple[str, str, Path] | str] | None = None,
    watches: list[str] | None = None,
    watch_urls: list[tuple[str, str]] | None = None,
    public_mode: bool = False,
    force: bool = False,
    templates_dir: Path = TEMPLATES_DIR,
) -> dict:
    """Initialise un atelier de conception isolé dans `workspace`."""
    raw_ws = workspace.expanduser()
    if is_symlink_or_junction(raw_ws):
        raise ValueError(f"Dossier atelier symlink/junction interdit : {raw_ws}")
    ws_root = raw_ws.resolve()

    if not force:
        detected_manifests = _detect_product_repo_manifests(ws_root)
        if detected_manifests:
            raise ValueError(
                f"Dépôt produit détecté dans {ws_root} "
                f"(.git + {', '.join(detected_manifests)}) sans projects.json : "
                "initialisation refusée. Utilisez un dossier dédié via --workspace <chemin> "
                "(ou --force pour outrepasser)."
            )

    selected_watches = list(dict.fromkeys(w.strip().lower() for w in (watches or []) if w.strip()))
    cfg_watches: list[dict] = []
    seen_watch_ids: set[str] = set()
    deploy_antigravity_impact = False

    for wname in selected_watches:
        if wname != "antigravity":
            raise ValueError(f"Preset veille inconnu : {wname!r}")
        if "antigravity" not in seen_watch_ids:
            cfg_watches.append(_build_antigravity_watch())
            seen_watch_ids.add("antigravity")
            deploy_antigravity_impact = True

    for wid, url in watch_urls or []:
        if wid in seen_watch_ids:
            raise ValueError(f"Identifiant veille en conflit : {wid}")
        seen_watch_ids.add(wid)
        cfg_watches.append(_make_watch_url_entry(wid, url))

    normalized_specs: list[tuple[str, str, Path]] = []
    seen_ids: set[str] = set()
    for item in projects or []:
        if isinstance(item, str):
            pid, ppath, resolved = _parse_target_spec(item, ws_root)
        elif len(item) == 2:
            pid = str(item[0]).strip().lower()
            ppath = str(item[1]).strip()
            if not PROJECT_ID_RE.match(pid):
                raise ValueError(f"Identifiant projet invalide ({pid!r}) : uniquement [a-z0-9_-].")
            if not ppath:
                raise ValueError(f"Chemin vide pour {pid}")
            resolved = _resolve_target_dir(ppath, ws_root)
        else:
            pid, ppath, resolved = item[0], item[1], item[2]
        if pid in seen_ids:
            raise ValueError(f"Projet dupliqué : {pid}")
        seen_ids.add(pid)
        normalized_specs.append((pid, ppath, resolved))

    ensure_safe_dir(ws_root)
    created: list[str] = []
    updated: list[str] = []
    skipped: list[str] = []

    explicit_name = name is not None and bool(str(name).strip())
    resolved_name = str(name).strip() if explicit_name else _derive_default_workspace_name(ws_root)

    agents_tpl = (templates_dir / "AGENTS.md").read_text(encoding="utf-8")
    eco_tpl = (templates_dir / "ECOSYSTEM.md").read_text(encoding="utf-8").replace("{{WORKSPACE_NAME}}", resolved_name)
    spec_tpl = (templates_dir / "spec-template.md").read_text(encoding="utf-8")
    task_tpl = (templates_dir / "task-template.md").read_text(encoding="utf-8")
    card_tpl = (templates_dir / "project-card-template.md").read_text(encoding="utf-8")
    impact_tpl = (templates_dir / "impact-template.md").read_text(encoding="utf-8")
    audit_code_readme = (templates_dir / "audit-code-readme.md").read_text(encoding="utf-8")
    audit_code_tpl = (templates_dir / "audit-code-template.md").read_text(encoding="utf-8")

    cfg = json.loads((templates_dir / "projects.json").read_text(encoding="utf-8"))
    cfg["workspace_name"] = resolved_name
    if public_mode:
        cfg["privacy"] = {"public_mode": True}

    cfg_projects = [
        _build_project_entry(pid, ppath, resolved, ws_root, preset_override=preset)
        for pid, ppath, resolved in normalized_specs
    ]
    cfg["projects"] = cfg_projects

    if preset is not None:
        cfg["default_preset"] = preset
    elif cfg_projects and all(p["preset"] == "antigravity-plugin" for p in cfg_projects):
        cfg["default_preset"] = "antigravity-plugin"
    else:
        cfg["default_preset"] = "generic"

    if deploy_antigravity_impact:
        cfg.setdefault("hot_budgets", {})["tracking/antigravity/IMPACT.md"] = ANTIGRAVITY_IMPACT_BUDGET
    cfg["watches"] = cfg_watches

    targets: list[tuple[Path, str]] = [
        (ws_root / "AGENTS.md", agents_tpl),
        (ws_root / "ECOSYSTEM.md", eco_tpl),
        (ws_root / "projects.json", json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"),
        (ws_root / "specs" / "_TEMPLATE.md", spec_tpl),
        (ws_root / "specs" / "archive" / ".gitkeep", ""),
        (ws_root / "tasks" / "_TEMPLATE.md", task_tpl),
        (ws_root / "tasks" / "archive" / ".gitkeep", ""),
        (ws_root / "tracking" / "projects" / "_TEMPLATE.md", card_tpl),
        (ws_root / "tracking" / "snapshots" / ".gitkeep", ""),
        (ws_root / "audits" / "code" / "README.md", audit_code_readme),
        (ws_root / "audits" / "code" / "_TEMPLATE.md", audit_code_tpl),
        (ws_root / "audits" / "agents" / ".gitkeep", ""),
    ]
    if deploy_antigravity_impact:
        targets.append((ws_root / "tracking" / "antigravity" / "IMPACT.md", impact_tpl))
    for entry in cfg_projects:
        targets.append((ws_root / "tracking" / "projects" / f"{entry['id']}.md", _render_project_card(card_tpl, entry)))

    buckets = {"created": created, "updated": updated, "skipped": skipped}
    with exclusive_file_lock(workspace_lock_path(ws_root), timeout_s=5.0):
        for dst, content in targets:
            buckets[_deploy_atomic(dst, content, force=force)].append(dst.relative_to(ws_root).as_posix())

    registry_name = "" if ("projects.json" in skipped and not explicit_name) else resolved_name
    register_atelier(ws_root, workspace_name=registry_name)
    return {"workspace": str(ws_root), "created": created, "updated": updated, "skipped": skipped}


def add_projects_to_workspace(
    workspace: Path,
    raw_targets: list[str],
    *,
    preset: str | None = None,
    templates_dir: Path = TEMPLATES_DIR,
    timeout_s: float = 5.0,
) -> dict:
    """Ajoute de façon atomique, verrouillée et fail-closed des projets à un atelier existant."""
    raw_ws = workspace.expanduser()
    if is_symlink_or_junction(raw_ws):
        raise ValueError(f"Dossier atelier symlink/junction interdit : {raw_ws}")
    ws_root = raw_ws.resolve()
    cfg_path = ws_root / "projects.json"
    if is_symlink_or_junction(cfg_path):
        raise ValueError(f"Fichier projects.json symlink/junction interdit : {cfg_path}")
    if not cfg_path.is_file():
        raise ValueError(f"Atelier non initialisé : {cfg_path} introuvable. Exécutez d'abord init_workspace.py.")

    with exclusive_file_lock(workspace_lock_path(ws_root), timeout_s=timeout_s):
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Impossible de lire {cfg_path} : {exc}") from exc
        if not isinstance(cfg, dict):
            raise ValueError(f"{cfg_path} doit contenir un objet JSON.")

        existing_projects = cfg.get("projects")
        if existing_projects is None:
            existing_projects = []
        if not isinstance(existing_projects, list):
            raise ValueError(f"Champ 'projects' invalide dans {cfg_path}.")

        existing_ids: set[str] = set()
        existing_paths: set[Path] = set()
        for item in existing_projects:
            if not isinstance(item, dict):
                continue
            eid = str(item.get("id") or "").strip().lower()
            if eid:
                existing_ids.add(eid)
            raw_p = str(item.get("path") or "").strip()
            if raw_p:
                p_obj = Path(raw_p).expanduser()
                existing_paths.add((p_obj if p_obj.is_absolute() else (ws_root / p_obj)).resolve())

        pending_entries: list[dict] = []
        pending_ids: set[str] = set()
        pending_paths: set[Path] = set()
        for raw in raw_targets:
            pid, ppath, resolved = _parse_target_spec(raw, ws_root)
            if pid in existing_ids or pid in pending_ids:
                raise ValueError(f"Doublon d'identifiant projet détecté : {pid}")
            if resolved in existing_paths or resolved in pending_paths:
                raise ValueError(f"Doublon de chemin projet détecté : {resolved}")
            pending_ids.add(pid)
            pending_paths.add(resolved)
            pending_entries.append(_build_project_entry(pid, ppath, resolved, ws_root, preset_override=preset))

        if not pending_entries:
            raise ValueError("Aucun projet spécifié pour --add.")

        card_tpl = (templates_dir / "project-card-template.md").read_text(encoding="utf-8")
        cfg["projects"] = list(existing_projects) + pending_entries
        write_json_atomic(cfg_path, cfg, indent=2, ensure_ascii=False)

        cards_created: list[str] = []
        cards_skipped: list[str] = []
        for entry in pending_entries:
            card_path = ws_root / "tracking" / "projects" / f"{entry['id']}.md"
            rel = card_path.relative_to(ws_root).as_posix()
            if is_symlink_or_junction(card_path):
                raise ValueError(f"Fiche projet symlink/junction interdite : {card_path}")
            if card_path.exists():
                cards_skipped.append(rel)
            else:
                write_text_atomic(card_path, _render_project_card(card_tpl, entry))
                cards_created.append(rel)

    register_atelier(ws_root, workspace_name=str(cfg.get("workspace_name") or ""))
    return {
        "workspace": str(ws_root),
        "added": [entry["id"] for entry in pending_entries],
        "cards_created": cards_created,
        "cards_skipped": cards_skipped,
    }


def build_parser() -> argparse.ArgumentParser:
    """Construit le parseur CLI pour `init_workspace.py`."""
    parser = argparse.ArgumentParser(description="Initialise un atelier Gravity Architect (Hot/Cold + suivi multi-projets).")
    parser.add_argument("--workspace", type=Path, default=Path("."), help="Dossier cible de l'atelier (défaut : répertoire courant)")
    parser.add_argument("--discover", action="store_true", help="Découvre les dépôts Git en profondeur 1 (lecture seule, sans modification)")
    parser.add_argument("--scan-dir", type=Path, default=None, help="Dossier parent à scanner pour --discover (défaut : --workspace)")
    parser.add_argument("--json", action="store_true", help="Sortie JSON structurée (--discover, initialisation et erreurs)")
    parser.add_argument("--add", action="append", default=[], help="Ajoute un projet (<chemin> ou id=chemin) à un atelier existant (répétable)")
    parser.add_argument("--name", default=None, help=f"Nom affiché de l'atelier dans ECOSYSTEM.md et projects.json (défaut : dérivé du dossier ou {DEFAULT_WORKSPACE_NAME})")
    parser.add_argument("--preset", choices=("generic", "antigravity-plugin"), default=None, help="Surcharge explicite du preset des projets (sinon auto-détecté)")
    parser.add_argument("--project", action="append", default=[], help="Déclare un projet initial au format id=chemin ou <chemin> (répétable)")
    parser.add_argument("--watch", action="append", choices=("antigravity",), default=[], help="Active un preset de veille officiel (répétable : antigravity)")
    parser.add_argument("--watch-url", action="append", default=[], help="Ajoute une veille markdown-changelog au format id=url (répétable)")
    parser.add_argument("--public-mode", action="store_true", help="Active privacy.public_mode=true dans projects.json")
    parser.add_argument("--run-sync", action="store_true", help="Exécute sync_tracking.run_sync(...) après initialisation")
    parser.add_argument("--offline", action="store_true", help="Passe offline=True lors de --run-sync")
    parser.add_argument("--force", action="store_true", help="Écrase les fichiers existants avec les modèles du plugin")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Point d'entrée CLI."""
    _configure_stdio()
    args = build_parser().parse_args(argv)
    try:
        if args.discover and args.add:
            raise ValueError("Options --discover et --add incompatibles.")

        if args.discover:
            info = discover_repositories(args.workspace, scan_dir=args.scan_dir)
            if args.json:
                print(json.dumps(info, indent=2, ensure_ascii=False))
            else:
                print(
                    f"[OK] Découverte ({info['scan_dir']}) : {len(info['candidates'])} dépôt(s) Git détecté(s) "
                    f"(atelier initialisé : {'oui' if info['initialized'] else 'non'})."
                )
                for cand in info["candidates"]:
                    print(f"  - {cand['id']} [{cand['preset']}] -> {cand['path']} (main={cand['main_branch']}, dev={cand['default_dev_branch']})")
            return 0

        if args.add:
            add_res = add_projects_to_workspace(args.workspace, list(args.add), preset=args.preset)
            if args.run_sync:
                ws_root = Path(add_res["workspace"])
                run_sync(config_path=ws_root / "projects.json", offline=args.offline, concept_root=ws_root)
            if args.json:
                print(json.dumps({"ok": True, **add_res}, indent=2, ensure_ascii=False))
            else:
                print(
                    f"[OK] Projets ajoutés à {add_res['workspace']} : {', '.join(add_res['added'])} "
                    f"(fiches créées: {len(add_res['cards_created'])}, préservées: {len(add_res['cards_skipped'])})."
                )
            return 0

        ws_root = args.workspace.expanduser().resolve()
        parsed_projects = _parse_project_specs(list(args.project or []), ws_root=ws_root)
        parsed_watch_urls = _parse_watch_urls(list(args.watch_url or []))
        result = init_workspace(
            args.workspace,
            name=args.name,
            preset=args.preset,
            projects=parsed_projects,
            watches=list(args.watch or []),
            watch_urls=parsed_watch_urls,
            public_mode=args.public_mode,
            force=args.force,
        )
        if args.run_sync:
            ws_resolved = Path(result["workspace"])
            run_sync(config_path=ws_resolved / "projects.json", offline=args.offline, concept_root=ws_resolved)
    except (OSError, ValueError, TimeoutError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc), "workspace": str(args.workspace.expanduser().resolve())}, ensure_ascii=False))
        else:
            print(f"[erreur] Initialisation impossible : {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"ok": True, **result}, indent=2, ensure_ascii=False))
    else:
        print(f"[OK] Atelier initialisé : {result['workspace']}")
        print(f"     Créés: {len(result['created'])}, mis à jour: {len(result['updated'])}, préservés: {len(result['skipped'])}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
