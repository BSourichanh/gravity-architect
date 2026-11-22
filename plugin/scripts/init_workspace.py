#!/usr/bin/env python3
"""Initialiseur idempotent d'atelier Gravity Architect (100 % stdlib Python 3)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent
TEMPLATES_DIR = PLUGIN_ROOT / "templates"

PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,48}$")


def _configure_stdio() -> None:
    """Force stdout/stderr en UTF-8 pour éviter les erreurs cp1252 sous Windows."""
    for stream in (sys.stdout, sys.stderr):
        reconf = getattr(stream, "reconfigure", None)
        if callable(reconf):
            try:
                reconf(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _write_utf8(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _deploy_file(
    dst: Path,
    content: str,
    *,
    force: bool,
    created: list[str],
    updated: list[str],
    skipped: list[str],
    workspace_root: Path,
) -> None:
    rel = dst.relative_to(workspace_root).as_posix()
    if dst.exists():
        if not force:
            skipped.append(rel)
            return
        _write_utf8(dst, content)
        updated.append(rel)
        return
    _write_utf8(dst, content)
    created.append(rel)


def _parse_project_specs(raw_specs: list[str]) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    seen_ids: set[str] = set()
    for raw in raw_specs:
        if "=" not in raw:
            raise ValueError(f"Format --project invalide ({raw!r}) : attendu id=chemin.")
        pid, ppath = raw.split("=", 1)
        pid = pid.strip().lower()
        ppath = ppath.strip()
        if not PROJECT_ID_RE.match(pid):
            raise ValueError(
                f"Identifiant projet invalide ({pid!r}) : uniquement [a-z0-9_-]."
            )
        if not ppath:
            raise ValueError(f"Chemin vide pour --project {pid}=...")
        if pid in seen_ids:
            raise ValueError(f"Projet dupliqué dans --project : {pid}")
        seen_ids.add(pid)
        parsed.append((pid, ppath))
    return parsed


def init_workspace(
    workspace: Path,
    *,
    name: str = "Mon Atelier Projets",
    preset: str = "generic",
    projects: list[tuple[str, str]] | None = None,
    force: bool = False,
    templates_dir: Path = TEMPLATES_DIR,
) -> dict:
    """Initialise un atelier de conception isolé dans `workspace`."""
    ws_root = workspace.expanduser().resolve()
    ws_root.mkdir(parents=True, exist_ok=True)

    created: list[str] = []
    updated: list[str] = []
    skipped: list[str] = []

    agents_tpl = (templates_dir / "AGENTS.md").read_text(encoding="utf-8")
    eco_tpl = (templates_dir / "ECOSYSTEM.md").read_text(encoding="utf-8").replace(
        "{{WORKSPACE_NAME}}", name
    )
    spec_tpl = (templates_dir / "spec-template.md").read_text(encoding="utf-8")
    handoff_tpl = (templates_dir / "handoff-template.md").read_text(encoding="utf-8")
    card_tpl = (templates_dir / "project-card-template.md").read_text(encoding="utf-8")
    archives_readme = (templates_dir / "archives-readme.md").read_text(encoding="utf-8")

    cfg = json.loads((templates_dir / "projects.json").read_text(encoding="utf-8"))
    cfg["workspace_name"] = name
    cfg["default_preset"] = preset

    project_entries = projects or []
    cfg_projects: list[dict] = []
    for pid, ppath in project_entries:
        entry: dict = {
            "id": pid,
            "name": pid.replace("-", " ").title(),
            "path": ppath,
            "preset": preset,
            "changelog": "CHANGELOG.md",
            "agents_file": "AGENTS.md",
            "main_branch": "main",
            "default_dev_branch": "dev",
            "runtime_ignore_paths": [".agents/", ".agents"],
            "role": f"Projet suivi ({pid})",
        }
        if preset == "antigravity-plugin":
            entry["plugin_manifest"] = "plugin/plugin.json"
            entry["validator_script"] = "plugin/scripts/validate.py"
        cfg_projects.append(entry)
    cfg["projects"] = cfg_projects

    targets: list[tuple[Path, str]] = [
        (ws_root / "AGENTS.md", agents_tpl),
        (ws_root / "ECOSYSTEM.md", eco_tpl),
        (ws_root / "projects.json", json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"),
        (ws_root / "specs" / "_TEMPLATE.md", spec_tpl),
        (ws_root / "specs" / "archive" / ".gitkeep", ""),
        (ws_root / "handoffs" / "_TEMPLATE.md", handoff_tpl),
        (ws_root / "handoffs" / "archive" / ".gitkeep", ""),
        (ws_root / "tracking" / "projects" / "_TEMPLATE.md", card_tpl),
        (ws_root / "tracking" / "snapshots" / ".gitkeep", ""),
        (ws_root / "archives" / "README.md", archives_readme),
        (ws_root / "archives" / "changelogs" / ".gitkeep", ""),
    ]

    for pid, ppath in project_entries:
        card_body = (
            card_tpl.replace("<Nom>", pid.replace("-", " ").title())
            .replace("<id>", pid)
            .replace("<chemin>", ppath)
            .replace("<rôle court>", f"Projet suivi ({pid})")
        )
        targets.append((ws_root / "tracking" / "projects" / f"{pid}.md", card_body))

    for dst, content in targets:
        _deploy_file(
            dst,
            content,
            force=force,
            created=created,
            updated=updated,
            skipped=skipped,
            workspace_root=ws_root,
        )

    return {
        "workspace": str(ws_root),
        "created": created,
        "updated": updated,
        "skipped": skipped,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Initialise un atelier Gravity Architect (Hot/Cold + suivi multi-projets)."
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Dossier cible de l'atelier (défaut : répertoire courant)",
    )
    parser.add_argument(
        "--name",
        default="Mon Atelier Projets",
        help="Nom affiché de l'atelier dans ECOSYSTEM.md et projects.json",
    )
    parser.add_argument(
        "--preset",
        choices=("generic", "antigravity-plugin"),
        default="generic",
        help="Preset par défaut des projets suivis (défaut : generic)",
    )
    parser.add_argument(
        "--project",
        action="append",
        default=[],
        help="Déclare un projet initial au format id=chemin (répétable)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Écrase les fichiers existants avec les modèles du plugin",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        parsed_projects = _parse_project_specs(list(args.project or []))
        result = init_workspace(
            args.workspace,
            name=args.name,
            preset=args.preset,
            projects=parsed_projects,
            force=args.force,
        )
    except (OSError, ValueError) as exc:
        print(f"[erreur] Initialisation impossible : {exc}", file=sys.stderr)
        return 1

    print(f"[OK] Atelier initialisé : {result['workspace']}")
    print(
        f"     Créés: {len(result['created'])}, "
        f"mis à jour: {len(result['updated'])}, "
        f"préservés: {len(result['skipped'])}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
