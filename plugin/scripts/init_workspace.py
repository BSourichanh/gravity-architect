#!/usr/bin/env python3
"""Initialiseur idempotent, découverte et ajout incrémental Gravity Architect (100 % stdlib Python 3)."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover - fallback Python 3.10
    tomllib = None

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from sync_tracking import (  # noqa: E402
    DEFAULT_WATCH_KEYWORDS,
    derive_validator_script,
    detect_plugin_manifest,
    detect_version_source,
    run_readonly_cmd,
    run_sync,
)

PLUGIN_ROOT = SCRIPT_DIR.parent
TEMPLATES_DIR = PLUGIN_ROOT / "templates"

PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,48}$")
TOML_DESC_RE = re.compile(r'^\s*description\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)

ANTIGRAVITY_CHANGELOG_URL = "https://antigravity.google/docs/changelog.md"
ANTIGRAVITY_IMPACT_BUDGET = 6000
ANTIGRAVITY_WATCH_SURFACES = [
    {"heading": "Antigravity App", "slug": "app"},
    {"heading": "Antigravity CLI", "slug": "cli"},
    {"heading": "IDE Extensions", "slug": "ide-extensions"},
    {"heading": "Antigravity SDK", "slug": "sdk"},
    {"heading": "Antigravity IDE", "slug": "ide"},
]


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
        fh.write(text.replace("\r\n", "\n"))


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


def _normalize_project_id(raw_name: str) -> str:
    """Normalise un nom de dossier en identifiant projet conforme à PROJECT_ID_RE."""
    cleaned = re.sub(r"[^a-z0-9_-]+", "-", raw_name.strip().lower())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-_")
    if not cleaned or not cleaned[0].isalnum():
        cleaned = f"p-{cleaned}" if cleaned else "project"
    cleaned = cleaned[:49].rstrip("-_")
    return cleaned or "project"


def _humanize_id(pid: str) -> str:
    return pid.replace("-", " ").replace("_", " ").strip().title()


def _truncate_text(text: str, max_len: int = 160) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_len:
        return collapsed
    cut = collapsed[: max_len - 1]
    last_space = cut.rfind(" ")
    if last_space >= max_len // 2:
        cut = cut[:last_space]
    return cut.rstrip(" ,;:-") + "…"


def _is_git_repo(repo_dir: Path) -> bool:
    git_marker = repo_dir / ".git"
    return git_marker.is_dir() or git_marker.is_file()


def _compute_portable_path(repo_dir: Path, ws_root: Path) -> str:
    """Retourne un chemin relatif POSIX sur le même lecteur, sinon le chemin absolu résolu."""
    repo_resolved = repo_dir.expanduser().resolve()
    ws_resolved = ws_root.expanduser().resolve()
    try:
        rel = os.path.relpath(str(repo_resolved), str(ws_resolved))
        return rel.replace("\\", "/")
    except ValueError:
        return str(repo_resolved)


def _resolve_target_dir(raw_path: str, ws_root: Path) -> Path:
    """Résout un chemin relatif au workspace ou au CWD sans ambiguïté."""
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    ws_candidate = (ws_root / candidate).resolve()
    if ws_candidate.exists():
        return ws_candidate
    cwd_candidate = (Path.cwd() / candidate).resolve()
    if cwd_candidate.exists():
        return cwd_candidate
    return ws_candidate


def _detect_git_branches(repo_dir: Path) -> tuple[str, str]:
    """Détecte `(main_branch, default_dev_branch)` en lecture seule."""
    if not _is_git_repo(repo_dir):
        return ("main", "main")

    rc, out, _ = run_readonly_cmd(
        ["git", "-C", str(repo_dir), "for-each-ref", "--format=%(refname:short)", "refs/heads"]
    )
    local_branches = (
        {line.strip() for line in out.splitlines() if line.strip()} if rc == 0 else set()
    )

    rc_cur, out_cur, _ = run_readonly_cmd(
        ["git", "-C", str(repo_dir), "rev-parse", "--abbrev-ref", "HEAD"]
    )
    current = out_cur.strip() if rc_cur == 0 and out_cur.strip() != "HEAD" else ""
    if not current:
        rc_sym, out_sym, _ = run_readonly_cmd(
            ["git", "-C", str(repo_dir), "symbolic-ref", "--short", "HEAD"]
        )
        if rc_sym == 0 and out_sym.strip():
            current = out_sym.strip()

    if "main" in local_branches or (not local_branches and current == "main"):
        main_branch = "main"
    elif "master" in local_branches or (not local_branches and current == "master"):
        main_branch = "master"
    elif current:
        main_branch = current
    else:
        main_branch = "main"

    default_dev = "dev" if "dev" in local_branches else main_branch
    return (main_branch, default_dev)


def _read_json_safe(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _extract_pyproject_description(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    if tomllib is not None:
        try:
            data = tomllib.loads(raw)
        except Exception:
            data = None
        if isinstance(data, dict):
            project = data.get("project")
            if isinstance(project, dict) and isinstance(project.get("description"), str):
                desc = project["description"].strip()
                if desc:
                    return desc
            poetry = (data.get("tool") or {}).get("poetry") if isinstance(data.get("tool"), dict) else None
            if isinstance(poetry, dict) and isinstance(poetry.get("description"), str):
                desc = poetry["description"].strip()
                if desc:
                    return desc
    match = TOML_DESC_RE.search(raw)
    return match.group(1).strip() if match and match.group(1).strip() else None


def _extract_readme_summary(repo_dir: Path) -> str | None:
    readme_path: Path | None = None
    for candidate in ("README.md", "readme.md", "Readme.md"):
        p = repo_dir / candidate
        if p.is_file():
            readme_path = p
            break
    if readme_path is None:
        return None
    try:
        lines = readme_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return None

    in_fence = False
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("```") or line.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence or not line:
            continue
        if line.startswith("#"):
            continue
        if line in ("---", "***", "==="):
            continue
        if line.startswith(("![", "[![", "<", "<!--", "|")):
            continue
        if line.startswith(">"):
            line = line.lstrip(">").strip()
            if not line:
                continue
        sentence_match = re.match(r"^(.+?[.!?])(?:\s+|$)", line)
        snippet = sentence_match.group(1) if sentence_match else line
        return _truncate_text(snippet, 160)
    return None


def _extract_role(repo_dir: Path, pid: str, manifest_data: dict | None) -> str:
    if isinstance(manifest_data, dict):
        desc = manifest_data.get("description")
        if isinstance(desc, str) and desc.strip():
            return _truncate_text(desc)

    pkg_data = _read_json_safe(repo_dir / "package.json")
    if isinstance(pkg_data, dict):
        desc = pkg_data.get("description")
        if isinstance(desc, str) and desc.strip():
            return _truncate_text(desc)

    pyp_desc = _extract_pyproject_description(repo_dir / "pyproject.toml")
    if pyp_desc:
        return _truncate_text(pyp_desc)

    readme_desc = _extract_readme_summary(repo_dir)
    if readme_desc:
        return readme_desc

    return f"Projet suivi ({pid})"


def inspect_project_dir(
    repo_dir: Path,
    ws_root: Path,
    *,
    project_id: str | None = None,
    path_override: str | None = None,
) -> dict:
    """Extrait en lecture seule les métadonnées d'un dépôt suivi ou candidat."""
    resolved = repo_dir.expanduser().resolve()
    pid = project_id or _normalize_project_id(resolved.name)
    path_str = path_override if path_override is not None else _compute_portable_path(resolved, ws_root)

    if not resolved.is_dir():
        return {
            "id": pid,
            "name": _humanize_id(pid),
            "path": path_str,
            "preset": "generic",
            "plugin_manifest": None,
            "validator_script": None,
            "version_source": None,
            "main_branch": "main",
            "default_dev_branch": "dev",
            "role": f"Projet suivi ({pid})",
            "has_changelog": False,
            "has_agents": False,
        }

    manifest_rel = detect_plugin_manifest({"id": pid}, resolved)
    manifest_data = _read_json_safe(resolved / manifest_rel) if manifest_rel else None
    validator_script = derive_validator_script({}, manifest_rel) if manifest_rel else None
    preset = "antigravity-plugin" if manifest_rel else "generic"
    version_source = detect_version_source({"id": pid, "preset": preset}, resolved, default_preset=preset)

    display_name = manifest_data.get("displayName") if isinstance(manifest_data, dict) else None
    name = (
        display_name.strip()
        if isinstance(display_name, str) and display_name.strip()
        else _humanize_id(pid)
    )
    main_branch, default_dev_branch = _detect_git_branches(resolved)
    role = _extract_role(resolved, pid, manifest_data)

    return {
        "id": pid,
        "name": name,
        "path": path_str,
        "preset": preset,
        "plugin_manifest": manifest_rel,
        "validator_script": validator_script,
        "version_source": version_source,
        "main_branch": main_branch,
        "default_dev_branch": default_dev_branch,
        "role": role,
        "has_changelog": (resolved / "CHANGELOG.md").is_file(),
        "has_agents": (resolved / "AGENTS.md").is_file(),
    }


def discover_repositories(workspace: Path, *, scan_dir: Path | None = None) -> dict:
    """Scanne en profondeur 1 les dépôts Git du dossier cible sans sortir de son périmètre."""
    ws_root = workspace.expanduser().resolve()
    scan_root = scan_dir.expanduser().resolve() if scan_dir is not None else ws_root
    if not scan_root.is_dir():
        raise ValueError(f"Dossier à scanner introuvable : {scan_root}")

    candidates: list[dict] = []
    seen_ids: set[str] = set()
    for child in sorted(scan_root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue
        if child.resolve() == ws_root:
            continue
        if not _is_git_repo(child):
            continue

        base_id = _normalize_project_id(child.name)
        unique_id = base_id
        suffix = 2
        while unique_id in seen_ids:
            tag = f"-{suffix}"
            unique_id = base_id[: 49 - len(tag)].rstrip("-_") + tag
            suffix += 1
        seen_ids.add(unique_id)

        candidates.append(inspect_project_dir(child, ws_root=ws_root, project_id=unique_id))

    return {
        "workspace": str(ws_root),
        "scan_dir": str(scan_root),
        "initialized": (ws_root / "projects.json").is_file(),
        "candidates": candidates,
    }


def _parse_target_spec(raw: str, ws_root: Path) -> tuple[str, str, Path]:
    """Parse `id=chemin` ou `<chemin>` et retourne `(id, path_str, resolved_dir)`."""
    if "=" in raw:
        pid_raw, ppath_raw = raw.split("=", 1)
        pid = pid_raw.strip().lower()
        ppath = ppath_raw.strip()
        if not PROJECT_ID_RE.match(pid):
            raise ValueError(
                f"Identifiant projet invalide ({pid!r}) : uniquement [a-z0-9_-]."
            )
        if not ppath:
            raise ValueError(f"Chemin vide pour {pid}=...")
        resolved = _resolve_target_dir(ppath, ws_root)
        cand = Path(ppath).expanduser()
        if not cand.is_absolute() and not (ws_root / cand).exists() and resolved.exists():
            ppath = _compute_portable_path(resolved, ws_root)
        return pid, ppath, resolved

    ppath = raw.strip()
    if not ppath:
        raise ValueError("Chemin projet vide.")
    resolved = _resolve_target_dir(ppath, ws_root)
    pid = _normalize_project_id(resolved.name)
    if not PROJECT_ID_RE.match(pid):
        raise ValueError(f"Identifiant projet dérivé invalide ({pid!r}).")
    portable = _compute_portable_path(resolved, ws_root) if resolved.exists() else ppath.replace("\\", "/")
    return pid, portable, resolved


def _parse_project_specs(
    raw_specs: list[str], ws_root: Path | None = None
) -> list[tuple[str, str, Path]]:
    base = ws_root.expanduser().resolve() if ws_root is not None else Path.cwd().resolve()
    parsed: list[tuple[str, str, Path]] = []
    seen_ids: set[str] = set()
    for raw in raw_specs:
        pid, ppath, resolved = _parse_target_spec(raw, base)
        if pid in seen_ids:
            raise ValueError(f"Projet dupliqué : {pid}")
        seen_ids.add(pid)
        parsed.append((pid, ppath, resolved))
    return parsed


def _parse_watch_urls(raw_urls: list[str]) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    seen_ids: set[str] = set()
    for raw in raw_urls:
        if "=" not in raw:
            raise ValueError(f"Format --watch-url invalide ({raw!r}) : attendu id=url.")
        wid_raw, url_raw = raw.split("=", 1)
        wid = wid_raw.strip().lower()
        url = url_raw.strip()
        if not PROJECT_ID_RE.match(wid):
            raise ValueError(
                f"Identifiant veille invalide ({wid!r}) : uniquement [a-z0-9_-]."
            )
        if not url.startswith(("https://", "http://")) or any(ch.isspace() for ch in url):
            raise ValueError(f"URL veille invalide ({url!r}) : http(s):// attendu.")
        if wid in seen_ids:
            raise ValueError(f"Veille dupliquée dans --watch-url : {wid}")
        seen_ids.add(wid)
        parsed.append((wid, url))
    return parsed


def _build_antigravity_watch() -> dict:
    return {
        "id": "antigravity",
        "name": "Google Antigravity",
        "type": "antigravity-changelog",
        "url": ANTIGRAVITY_CHANGELOG_URL,
        "out_dir": "tracking/antigravity",
        "impact_file": "tracking/antigravity/IMPACT.md",
        "releases_per_surface": 5,
        "local_cli_check": {"cmd": "agy", "surface_slug": "cli"},
        "relevance_keywords": list(DEFAULT_WATCH_KEYWORDS),
        "surfaces": [dict(s) for s in ANTIGRAVITY_WATCH_SURFACES],
    }


def _build_project_entry(
    pid: str,
    ppath: str,
    resolved: Path,
    ws_root: Path,
    *,
    preset_override: str | None = None,
) -> dict:
    info = inspect_project_dir(resolved, ws_root=ws_root, project_id=pid, path_override=ppath)
    effective_preset = preset_override if preset_override is not None else info["preset"]
    entry: dict = {
        "id": pid,
        "name": info["name"],
        "path": ppath,
        "preset": effective_preset,
        "changelog": "CHANGELOG.md",
        "agents_file": "AGENTS.md",
        "main_branch": info["main_branch"],
        "default_dev_branch": info["default_dev_branch"],
        "runtime_ignore_paths": [".agents/", ".agents"],
        "role": info["role"],
    }
    if effective_preset == "antigravity-plugin":
        entry["plugin_manifest"] = info["plugin_manifest"] or "plugin/plugin.json"
        entry["validator_script"] = info["validator_script"] or "plugin/scripts/validate.py"
    return entry


def _render_project_card(card_tpl: str, entry: dict) -> str:
    return (
        card_tpl.replace("<Nom>", entry["name"])
        .replace("<id>", entry["id"])
        .replace("<chemin>", entry["path"])
        .replace("<rôle court>", entry["role"])
    )


def init_workspace(
    workspace: Path,
    *,
    name: str = "Mon Atelier Projets",
    preset: str | None = None,
    projects: list[tuple[str, str] | tuple[str, str, Path] | str] | None = None,
    watches: list[str] | None = None,
    watch_urls: list[tuple[str, str]] | None = None,
    public_mode: bool = False,
    force: bool = False,
    templates_dir: Path = TEMPLATES_DIR,
) -> dict:
    """Initialise un atelier de conception isolé dans `workspace`."""
    ws_root = workspace.expanduser().resolve()

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
        cfg_watches.append(
            {
                "id": wid,
                "name": _humanize_id(wid),
                "type": "markdown-changelog",
                "url": url,
                "out_dir": f"tracking/{wid}",
                "releases_per_surface": 5,
                "relevance_keywords": list(DEFAULT_WATCH_KEYWORDS),
            }
        )

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
    impact_tpl = (templates_dir / "impact-template.md").read_text(encoding="utf-8")
    archives_readme = (templates_dir / "archives-readme.md").read_text(encoding="utf-8")
    audit_code_readme = (templates_dir / "audit-code-readme.md").read_text(encoding="utf-8")
    audit_code_tpl = (templates_dir / "audit-code-template.md").read_text(encoding="utf-8")

    cfg = json.loads((templates_dir / "projects.json").read_text(encoding="utf-8"))
    cfg["workspace_name"] = name
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
        (ws_root / "handoffs" / "_TEMPLATE.md", handoff_tpl),
        (ws_root / "handoffs" / "archive" / ".gitkeep", ""),
        (ws_root / "tracking" / "projects" / "_TEMPLATE.md", card_tpl),
        (ws_root / "tracking" / "snapshots" / ".gitkeep", ""),
        (ws_root / "archives" / "README.md", archives_readme),
        (ws_root / "archives" / "changelogs" / ".gitkeep", ""),
        (ws_root / "audits" / "code" / "README.md", audit_code_readme),
        (ws_root / "audits" / "code" / "_TEMPLATE.md", audit_code_tpl),
        (ws_root / "audits" / "agents" / ".gitkeep", ""),
    ]

    if deploy_antigravity_impact:
        targets.append((ws_root / "tracking" / "antigravity" / "IMPACT.md", impact_tpl))

    for entry in cfg_projects:
        targets.append(
            (
                ws_root / "tracking" / "projects" / f"{entry['id']}.md",
                _render_project_card(card_tpl, entry),
            )
        )

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


def add_projects_to_workspace(
    workspace: Path,
    raw_targets: list[str],
    *,
    preset: str | None = None,
    templates_dir: Path = TEMPLATES_DIR,
) -> dict:
    """Ajoute de façon atomique et fail-closed des projets à un atelier existant."""
    ws_root = workspace.expanduser().resolve()
    cfg_path = ws_root / "projects.json"
    if not cfg_path.is_file():
        raise ValueError(
            f"Atelier non initialisé : {cfg_path} introuvable. Exécutez d'abord init_workspace.py."
        )

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
            resolved_p = (p_obj if p_obj.is_absolute() else (ws_root / p_obj)).resolve()
            existing_paths.add(resolved_p)

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
        pending_entries.append(
            _build_project_entry(pid, ppath, resolved, ws_root, preset_override=preset)
        )

    if not pending_entries:
        raise ValueError("Aucun projet spécifié pour --add.")

    card_tpl = (templates_dir / "project-card-template.md").read_text(encoding="utf-8")
    cfg["projects"] = list(existing_projects) + pending_entries
    _write_utf8(cfg_path, json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")

    cards_created: list[str] = []
    cards_skipped: list[str] = []
    for entry in pending_entries:
        card_path = ws_root / "tracking" / "projects" / f"{entry['id']}.md"
        rel = card_path.relative_to(ws_root).as_posix()
        if card_path.exists():
            cards_skipped.append(rel)
        else:
            _write_utf8(card_path, _render_project_card(card_tpl, entry))
            cards_created.append(rel)

    return {
        "workspace": str(ws_root),
        "added": [entry["id"] for entry in pending_entries],
        "cards_created": cards_created,
        "cards_skipped": cards_skipped,
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
        "--discover",
        action="store_true",
        help="Découvre les dépôts Git en profondeur 1 (lecture seule, sans modification)",
    )
    parser.add_argument(
        "--scan-dir",
        type=Path,
        default=None,
        help="Dossier parent à scanner pour --discover (défaut : --workspace)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Sortie JSON structurée pour --discover",
    )
    parser.add_argument(
        "--add",
        action="append",
        default=[],
        help="Ajoute un projet (<chemin> ou id=chemin) à un atelier existant (répétable)",
    )
    parser.add_argument(
        "--name",
        default="Mon Atelier Projets",
        help="Nom affiché de l'atelier dans ECOSYSTEM.md et projects.json",
    )
    parser.add_argument(
        "--preset",
        choices=("generic", "antigravity-plugin"),
        default=None,
        help="Surcharge explicite du preset des projets (sinon auto-détecté)",
    )
    parser.add_argument(
        "--project",
        action="append",
        default=[],
        help="Déclare un projet initial au format id=chemin ou <chemin> (répétable)",
    )
    parser.add_argument(
        "--watch",
        action="append",
        choices=("antigravity",),
        default=[],
        help="Active un preset de veille officiel (répétable : antigravity)",
    )
    parser.add_argument(
        "--watch-url",
        action="append",
        default=[],
        help="Ajoute une veille markdown-changelog au format id=url (répétable)",
    )
    parser.add_argument(
        "--public-mode",
        action="store_true",
        help="Active privacy.public_mode=true dans projects.json",
    )
    parser.add_argument(
        "--run-sync",
        action="store_true",
        help="Exécute sync_tracking.run_sync(...) après initialisation",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Passe offline=True lors de --run-sync",
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
        if args.discover and args.add:
            raise ValueError("Options --discover et --add incompatibles.")

        if args.discover:
            info = discover_repositories(args.workspace, scan_dir=args.scan_dir)
            if args.json:
                print(json.dumps(info, indent=2, ensure_ascii=False))
            else:
                print(
                    f"[OK] Découverte ({info['scan_dir']}) : "
                    f"{len(info['candidates'])} dépôt(s) Git détecté(s) "
                    f"(atelier initialisé : {'oui' if info['initialized'] else 'non'})."
                )
                for cand in info["candidates"]:
                    print(
                        f"  - {cand['id']} [{cand['preset']}] -> {cand['path']} "
                        f"(main={cand['main_branch']}, dev={cand['default_dev_branch']})"
                    )
            return 0

        if args.add:
            add_res = add_projects_to_workspace(
                args.workspace, list(args.add), preset=args.preset
            )
            print(
                f"[OK] Projets ajoutés à {add_res['workspace']} : "
                f"{', '.join(add_res['added'])} "
                f"(fiches créées: {len(add_res['cards_created'])}, "
                f"préservées: {len(add_res['cards_skipped'])})."
            )
            if args.run_sync:
                ws_root = Path(add_res["workspace"])
                run_sync(
                    config_path=ws_root / "projects.json",
                    offline=args.offline,
                    concept_root=ws_root,
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
            run_sync(
                config_path=ws_resolved / "projects.json",
                offline=args.offline,
                concept_root=ws_resolved,
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
