"""Découverte lecture seule des dépôts, métadonnées projet et évaluation de conformité."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover - fallback Python 3.10
    tomllib = None

from core.io_utils import (
    CHANGELOG_SECTION_RE,
    SECTION_RE,
    humanize_id,
    read_json_safe,
    run_readonly_cmd,
    truncate_text,
)

PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,48}$")
TOML_DESC_RE = re.compile(r'^\s*description\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
PRODUCT_MANIFEST_FILES = (
    "plugin/plugin.json",
    "plugin.json",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "setup.py",
)
REQUIRED_OFFICIAL_PLUGIN_FIELDS = (
    "name",
    "displayName",
    "version",
    "description",
    "logo",
    "suggestedPrompts",
    "author",
    "homepage",
    "repository",
)


def detect_plugin_manifest(project_cfg: dict, repo_dir: Path) -> str | None:
    """Résout le chemin relatif de `plugin.json` (`plugin/plugin.json` > `{id}-plugin/plugin.json` > `plugin.json`)."""
    explicit = project_cfg.get("plugin_manifest")
    if explicit:
        return str(explicit)

    project_id = str(project_cfg.get("id") or repo_dir.name)
    for candidate in ("plugin/plugin.json", f"{project_id}-plugin/plugin.json", "plugin.json"):
        if (repo_dir / candidate).is_file():
            return candidate
    for pjson in sorted(repo_dir.glob("*-plugin/plugin.json"), key=lambda p: p.as_posix()):
        return pjson.relative_to(repo_dir).as_posix()
    return None


def derive_validator_script(project_cfg: dict, manifest_rel: str | None) -> str | None:
    """Dérive le chemin relatif de `validate.py` depuis `validator_script` ou `plugin_manifest`."""
    explicit = project_cfg.get("validator_script")
    if explicit:
        return str(explicit)
    if not manifest_rel:
        return None
    return (Path(str(manifest_rel)).parent / "scripts" / "validate.py").as_posix()


def detect_version_source(
    project_cfg: dict,
    repo_dir: Path,
    default_preset: str = "generic",
) -> str | None:
    """Identifie le fichier source de version d'un dépôt (explicite ou auto-détecté)."""
    explicit = project_cfg.get("version_file") or project_cfg.get("plugin_manifest")
    if explicit:
        return str(explicit)

    preset = str(project_cfg.get("preset") or default_preset or "generic").strip().lower()
    if preset == "antigravity-plugin":
        manifest_rel = detect_plugin_manifest(project_cfg, repo_dir)
        if manifest_rel:
            return manifest_rel

    for candidate in ("package.json", "pyproject.toml", "Cargo.toml", "setup.cfg", "VERSION", "version.txt"):
        if (repo_dir / candidate).is_file():
            return candidate
    return detect_plugin_manifest(project_cfg, repo_dir)


def resolve_project_preset(project_cfg: dict, global_cfg: dict | None = None) -> str:
    """Résout le preset applicable à un projet (`generic` ou `antigravity-plugin`)."""
    raw = project_cfg.get("preset")
    if raw is None and isinstance(global_cfg, dict):
        raw = global_cfg.get("default_preset")
    return str(raw or "generic").strip().lower()


def check_agents_doc(
    agents_path: Path,
    agents_rel: str,
    max_bytes: int | None,
    required_sections: list[str],
    issues: list[str],
) -> None:
    """Vérifie la taille et la présence des sections attendues dans AGENTS.md."""
    if not agents_path.is_file():
        issues.append(f"{agents_rel} manquant")
        return
    raw_bytes = agents_path.read_bytes()
    if max_bytes and len(raw_bytes) > max_bytes:
        issues.append(f"{agents_rel} > {max_bytes} o ({len(raw_bytes)} o)")
    headings = [m.group(1).strip().lower() for m in SECTION_RE.finditer(raw_bytes.decode("utf-8", errors="replace"))]
    missing_secs: list[str] = []
    for sec in required_sections:
        low = sec.lower()
        if "périmètre" in low or "architecture" in low:
            matched = any(re.search(r"p[ée]rim[èe]tre|architecture", h) for h in headings)
        elif "invariant" in low:
            matched = any("invariant" in h for h in headings)
        elif "vérification" in low or "verification" in low:
            matched = any(re.search(r"v[ée]rification", h) for h in headings)
        else:
            matched = any(low in h for h in headings)
        if not matched:
            missing_secs.append(sec)
    if missing_secs:
        issues.append(f"{agents_rel}: section(s) manquante(s) ({', '.join(missing_secs)})")


def _check_changelog_doc(repo_dir: Path, project_cfg: dict, issues: list[str]) -> None:
    changelog_rel = str(project_cfg.get("changelog") or "CHANGELOG.md")
    changelog_path = repo_dir / changelog_rel
    if not changelog_path.is_file():
        issues.append(f"{changelog_rel} manquant")
        return
    if not CHANGELOG_SECTION_RE.search(changelog_path.read_text(encoding="utf-8", errors="replace")):
        issues.append(f"{changelog_rel}: aucune section ## [X.Y.Z]")


def evaluate_antigravity_plugin_compliance(project_cfg: dict, repo_dir: Path, issues: list[str]) -> None:
    """Évalue les exigences de structure d'un plugin Antigravity."""
    manifest_rel = detect_plugin_manifest(project_cfg, repo_dir) or "plugin/plugin.json"
    manifest_path = repo_dir / manifest_rel
    if not manifest_path.is_file():
        issues.append(f"{manifest_rel} manquant")
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            if not isinstance(manifest, dict):
                issues.append("plugin.json doit être un objet JSON")
            else:
                missing_fields = [k for k in REQUIRED_OFFICIAL_PLUGIN_FIELDS if k not in manifest]
                if missing_fields:
                    issues.append(f"plugin.json: champs manquants ({', '.join(missing_fields)})")
                desc = str(manifest.get("description") or "")
                if not desc or len(desc) > 160:
                    issues.append("plugin.json: description vide ou > 160 car.")
                prompts = manifest.get("suggestedPrompts")
                if not isinstance(prompts, list) or len(prompts) != 3 or not all(isinstance(p, str) and p.strip() for p in prompts):
                    issues.append("plugin.json: 3 suggestedPrompts requis")
        except (OSError, json.JSONDecodeError):
            issues.append("plugin.json JSON invalide")

    agents_rel = str(project_cfg.get("agents_file") or "AGENTS.md")
    check_agents_doc(
        repo_dir / agents_rel,
        agents_rel,
        max_bytes=2500,
        required_sections=["Périmètre & Architecture", "Invariants", "Vérifications obligatoires"],
        issues=issues,
    )
    _check_changelog_doc(repo_dir, project_cfg, issues)
    for req_file in ("README.md", "install.py", ".gitattributes", ".gitignore"):
        if not (repo_dir / req_file).is_file():
            issues.append(f"{req_file} manquant")
    if not (repo_dir / "tests").is_dir():
        issues.append("tests/ manquant")
    validator_rel = derive_validator_script(project_cfg, manifest_rel)
    if validator_rel and not (repo_dir / validator_rel).is_file():
        issues.append(f"{validator_rel} manquant")


def evaluate_project_compliance(
    project_cfg: dict,
    repo_dir: Path,
    default_preset: str = "generic",
) -> dict:
    """Évalue la conformité d'un dépôt selon son preset et les règles opt-in `compliance`."""
    if not repo_dir.is_dir():
        return {"ok": False, "issues": ["dépôt introuvable"]}

    issues: list[str] = []
    preset = str(project_cfg.get("preset") or default_preset or "generic").strip().lower()
    if preset == "antigravity-plugin":
        evaluate_antigravity_plugin_compliance(project_cfg, repo_dir, issues)

    comp_cfg = project_cfg.get("compliance")
    if isinstance(comp_cfg, dict):
        for req_file in comp_cfg.get("required_files") or []:
            if not (repo_dir / str(req_file)).is_file():
                issues.append(f"{req_file} manquant")
        for req_dir in comp_cfg.get("required_dirs") or []:
            if not (repo_dir / str(req_dir)).is_dir():
                issues.append(f"{req_dir}/ manquant")

        agents_max = comp_cfg.get("agents_max_bytes")
        req_secs = list(comp_cfg.get("required_agents_sections") or [])
        if agents_max is not None or req_secs:
            agents_rel = str(project_cfg.get("agents_file") or "AGENTS.md")
            check_agents_doc(
                repo_dir / agents_rel,
                agents_rel,
                max_bytes=int(agents_max) if agents_max is not None else None,
                required_sections=req_secs,
                issues=issues,
            )
        if comp_cfg.get("require_changelog_semver"):
            _check_changelog_doc(repo_dir, project_cfg, issues)

    return {"ok": len(issues) == 0, "issues": issues}


def is_git_repo(repo_dir: Path) -> bool:
    """Retourne True si `repo_dir` possède un marqueur `.git`."""
    git_marker = repo_dir / ".git"
    return git_marker.is_dir() or git_marker.is_file()


def detect_product_repo_manifests(ws_root: Path) -> list[str]:
    """Retourne les manifestes code/plugin détectés si `ws_root` est un dépôt produit sans atelier."""
    if (ws_root / "projects.json").is_file() or not is_git_repo(ws_root):
        return []
    return [rel for rel in PRODUCT_MANIFEST_FILES if (ws_root / rel).is_file()]


def normalize_project_id(raw_name: str) -> str:
    """Normalise un nom de dossier en identifiant projet conforme à PROJECT_ID_RE."""
    cleaned = re.sub(r"[^a-z0-9_-]+", "-", raw_name.strip().lower())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-_")
    if not cleaned or not cleaned[0].isalnum():
        cleaned = f"p-{cleaned}" if cleaned else "project"
    return (cleaned[:49].rstrip("-_")) or "project"


def compute_portable_path(repo_dir: Path, ws_root: Path) -> str:
    """Retourne un chemin relatif POSIX sur le même lecteur, sinon le chemin absolu résolu."""
    repo_resolved = repo_dir.expanduser().resolve()
    ws_resolved = ws_root.expanduser().resolve()
    try:
        return os.path.relpath(str(repo_resolved), str(ws_resolved)).replace("\\", "/")
    except ValueError:
        return str(repo_resolved)


def resolve_target_dir(raw_path: str, ws_root: Path) -> Path:
    """Résout un chemin relatif au workspace ou au CWD sans ambiguïté."""
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    ws_candidate = (ws_root / candidate).resolve()
    if ws_candidate.exists():
        return ws_candidate
    cwd_candidate = (Path.cwd() / candidate).resolve()
    return cwd_candidate if cwd_candidate.exists() else ws_candidate


def detect_git_branches(repo_dir: Path) -> tuple[str, str]:
    """Détecte `(main_branch, default_dev_branch)` en lecture seule."""
    if not is_git_repo(repo_dir):
        return ("main", "main")

    rc, out, _ = run_readonly_cmd(["git", "-C", str(repo_dir), "for-each-ref", "--format=%(refname:short)", "refs/heads"])
    local_branches = {line.strip() for line in out.splitlines() if line.strip()} if rc == 0 else set()
    rc_cur, out_cur, _ = run_readonly_cmd(["git", "-C", str(repo_dir), "rev-parse", "--abbrev-ref", "HEAD"])
    current = out_cur.strip() if rc_cur == 0 and out_cur.strip() != "HEAD" else ""
    if not current:
        rc_sym, out_sym, _ = run_readonly_cmd(["git", "-C", str(repo_dir), "symbolic-ref", "--short", "HEAD"])
        if rc_sym == 0 and out_sym.strip():
            current = out_sym.strip()

    if "main" in local_branches or (not local_branches and current == "main"):
        main_branch = "main"
    elif "master" in local_branches or (not local_branches and current == "master"):
        main_branch = "master"
    else:
        main_branch = current or "main"

    return (main_branch, "dev" if "dev" in local_branches else main_branch)


def extract_pyproject_description(path: Path) -> str | None:
    """Extrait `description` depuis `pyproject.toml` (PEP 621 ou Poetry)."""
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
            for section in (data.get("project"), (data.get("tool") or {}).get("poetry") if isinstance(data.get("tool"), dict) else None):
                if isinstance(section, dict) and isinstance(section.get("description"), str) and section["description"].strip():
                    return section["description"].strip()
    match = TOML_DESC_RE.search(raw)
    return match.group(1).strip() if match and match.group(1).strip() else None


def extract_readme_summary(repo_dir: Path) -> str | None:
    """Extrait la première phrase significative d'un README.md hors badges et titres."""
    readme_path = next((repo_dir / c for c in ("README.md", "readme.md", "Readme.md") if (repo_dir / c).is_file()), None)
    if readme_path is None:
        return None
    try:
        lines = readme_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return None

    in_fence = False
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence or not line or line.startswith("#") or line in ("---", "***", "==="):
            continue
        if line.startswith(("![", "[![", "<", "<!--", "|")):
            continue
        if line.startswith(">"):
            line = line.lstrip(">").strip()
            if not line:
                continue
        sentence_match = re.match(r"^(.+?[.!?])(?:\s+|$)", line)
        return truncate_text(sentence_match.group(1) if sentence_match else line, 160)
    return None


def extract_role(repo_dir: Path, pid: str, manifest_data: dict | None) -> str:
    """Détermine un rôle court pour le projet depuis son manifeste ou son README."""
    for source in (manifest_data, read_json_safe(repo_dir / "package.json")):
        if isinstance(source, dict) and isinstance(source.get("description"), str) and source["description"].strip():
            return truncate_text(source["description"])
    pyp_desc = extract_pyproject_description(repo_dir / "pyproject.toml")
    if pyp_desc:
        return truncate_text(pyp_desc)
    return extract_readme_summary(repo_dir) or f"Projet suivi ({pid})"


def inspect_project_dir(
    repo_dir: Path,
    ws_root: Path,
    *,
    project_id: str | None = None,
    path_override: str | None = None,
) -> dict:
    """Extrait en lecture seule les métadonnées d'un dépôt suivi ou candidat."""
    resolved = repo_dir.expanduser().resolve()
    pid = project_id or normalize_project_id(resolved.name)
    path_str = path_override if path_override is not None else compute_portable_path(resolved, ws_root)

    if not resolved.is_dir():
        return {
            "id": pid, "name": humanize_id(pid), "path": path_str, "preset": "generic",
            "plugin_manifest": None, "validator_script": None, "version_source": None,
            "main_branch": "main", "default_dev_branch": "dev", "role": f"Projet suivi ({pid})",
            "has_changelog": False, "has_agents": False,
        }

    manifest_rel = detect_plugin_manifest({"id": pid}, resolved)
    manifest_data = read_json_safe(resolved / manifest_rel) if manifest_rel else None
    validator_script = derive_validator_script({}, manifest_rel) if manifest_rel else None
    preset = "antigravity-plugin" if manifest_rel else "generic"
    version_source = detect_version_source({"id": pid, "preset": preset}, resolved, default_preset=preset)
    display_name = manifest_data.get("displayName") if isinstance(manifest_data, dict) else None
    name = display_name.strip() if isinstance(display_name, str) and display_name.strip() else humanize_id(pid)
    main_branch, default_dev_branch = detect_git_branches(resolved)

    return {
        "id": pid, "name": name, "path": path_str, "preset": preset,
        "plugin_manifest": manifest_rel, "validator_script": validator_script,
        "version_source": version_source, "main_branch": main_branch,
        "default_dev_branch": default_dev_branch, "role": extract_role(resolved, pid, manifest_data),
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
        if not child.is_dir() or child.name.startswith(".") or child.resolve() == ws_root or not is_git_repo(child):
            continue
        base_id = normalize_project_id(child.name)
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


def parse_target_spec(raw: str, ws_root: Path) -> tuple[str, str, Path]:
    """Parse `id=chemin` ou `<chemin>` et retourne `(id, path_str, resolved_dir)`."""
    if "=" in raw:
        pid_raw, ppath_raw = raw.split("=", 1)
        pid, ppath = pid_raw.strip().lower(), ppath_raw.strip()
        if not PROJECT_ID_RE.match(pid):
            raise ValueError(f"Identifiant projet invalide ({pid!r}) : uniquement [a-z0-9_-].")
        if not ppath:
            raise ValueError(f"Chemin vide pour {pid}=...")
        resolved = resolve_target_dir(ppath, ws_root)
        cand = Path(ppath).expanduser()
        if not cand.is_absolute() and not (ws_root / cand).exists() and resolved.exists():
            ppath = compute_portable_path(resolved, ws_root)
        return pid, ppath, resolved

    ppath = raw.strip()
    if not ppath:
        raise ValueError("Chemin projet vide.")
    resolved = resolve_target_dir(ppath, ws_root)
    pid = normalize_project_id(resolved.name)
    if not PROJECT_ID_RE.match(pid):
        raise ValueError(f"Identifiant projet dérivé invalide ({pid!r}).")
    portable = compute_portable_path(resolved, ws_root) if resolved.exists() else ppath.replace("\\", "/")
    return pid, portable, resolved


def parse_project_specs(raw_specs: list[str], ws_root: Path | None = None) -> list[tuple[str, str, Path]]:
    """Parse et déduplique une liste de spécifications projet `--project`."""
    base = ws_root.expanduser().resolve() if ws_root is not None else Path.cwd().resolve()
    parsed: list[tuple[str, str, Path]] = []
    seen_ids: set[str] = set()
    for raw in raw_specs:
        pid, ppath, resolved = parse_target_spec(raw, base)
        if pid in seen_ids:
            raise ValueError(f"Projet dupliqué : {pid}")
        seen_ids.add(pid)
        parsed.append((pid, ppath, resolved))
    return parsed


def build_project_entry(
    pid: str,
    ppath: str,
    resolved: Path,
    ws_root: Path,
    *,
    preset_override: str | None = None,
) -> dict:
    """Construit l'entrée JSON `projects[]` d'un projet pour `projects.json`."""
    info = inspect_project_dir(resolved, ws_root=ws_root, project_id=pid, path_override=ppath)
    effective_preset = preset_override if preset_override is not None else info["preset"]
    entry: dict = {
        "id": pid, "name": info["name"], "path": ppath, "preset": effective_preset,
        "changelog": "CHANGELOG.md", "agents_file": "AGENTS.md",
        "main_branch": info["main_branch"], "default_dev_branch": info["default_dev_branch"],
        "runtime_ignore_paths": [".agents/", ".agents"], "role": info["role"],
    }
    if effective_preset == "antigravity-plugin":
        entry["plugin_manifest"] = info["plugin_manifest"] or "plugin/plugin.json"
        entry["validator_script"] = info["validator_script"] or "plugin/scripts/validate.py"
    return entry


def render_project_card(card_tpl: str, entry: dict) -> str:
    """Instancie le modèle de fiche projet pour un dépôt déclaré."""
    return (
        card_tpl.replace("<Nom>", entry["name"])
        .replace("<id>", entry["id"])
        .replace("<chemin>", entry["path"])
        .replace("<rôle court>", entry["role"])
    )
