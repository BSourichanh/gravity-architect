#!/usr/bin/env python3
"""Moteur générique de collecte lecture seule, delta éditorial et suivi Hot/Cold (100 % stdlib)."""

from __future__ import annotations

import argparse
import configparser
from datetime import datetime, timezone
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover - fallback Python 3.10
    tomllib = None

SCHEMA_VERSION = 5

DEFAULT_HOT_BUDGETS = {
    "AGENTS.md": 2500,
    "ECOSYSTEM.md": 6000,
    "tracking/antigravity/IMPACT.md": 6000,
    "project_card_max_bytes": 3500,
}

INSTALL_ADAPTED_FILENAMES = {"hooks.json", "mcp_config.json", "sidecar.json"}
INSTALL_IGNORED_DIRS = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache"}
INSTALL_IGNORED_SUFFIXES = (".pyc", ".pyo")

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

DEFAULT_WATCH_KEYWORDS = [
    "mcp",
    "hook",
    "plugin",
    "skill",
    "workflow",
    "run_workflow",
    "swarm",
    "subagent",
    "model",
    "gemini",
    "orchestrator",
    "sandbox",
    "windows",
    "bom",
    "sidecar",
    "validate",
    "agy",
    "effort",
    "thinking",
    "rule",
]

AUTO_DISCOVER_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}

SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
SEPARATOR_RE = re.compile(r"^\s*---\s*$", re.MULTILINE)
VERSION_HEADING_RE = re.compile(r"^###\s+\[(v[0-9][^\]]*)\]", re.MULTILINE)
SUB_HEADING_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
CHANGELOG_SECTION_RE = re.compile(
    r"^##[ \t]+\[([^\]]+)\](?:[ \t]*-[ \t]*([^\s(]+))?[^\n]*$", re.MULTILINE
)
MD_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
MD_BULLET_RE = re.compile(r"^\s*[\*\-]\s+(.+?)\s*$", re.MULTILINE)
STATUS_LINE_RE = re.compile(
    r"^\s*-\s*\*\*(?:Date\s*/\s*)?Statut\s*:\*\*\s*(.+?)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
TARGET_LINE_RE = re.compile(
    r"^\s*-\s*\*\*(?:Dépôt cible|Projets? impactés?)\s*:\*\*\s*(.+?)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
SYNC_LINE_RE = re.compile(r"^- \*\*Synchronisé le :\*\*.*$", re.MULTILINE)
DATE_LINE_RE = re.compile(r"^- \*\*Date :\*\*.*$", re.MULTILINE)
AUTO_BLOCK_RE = re.compile(
    r"<!-- AUTO:START:[^>]+ -->.*?<!-- AUTO:END:[^>]+ -->",
    re.DOTALL,
)
MACHINE_ABS_PATH_RE = re.compile(
    r"(?:"
    r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/][^\s`\"'<>|)\]]+"
    r"|\\\\[A-Za-z0-9_.-]+[\\/][^\s`\"'<>|)\]]+"
    r"|(?<![:\w/])/(?:Users|home|var|tmp|opt|etc|mnt|Volumes|private|root)/[^\s`\"'<>|)\]]+"
    r")"
)
SEMVER_RE = re.compile(r"\bv?(\d+(?:\.\d+)+)")


def _parse_semver_tuple(raw: str) -> tuple[int, ...] | None:
    """Extrait un tuple SemVer numérique (au moins MAJOR.MINOR) depuis une chaîne."""
    if not isinstance(raw, str):
        return None
    match = SEMVER_RE.search(raw.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _compare_cli_versions(local_raw: str, latest_raw: str) -> str:
    """Compare une version CLI locale à la dernière connue ('behind'|'ahead'|'equal')."""
    local_tuple = _parse_semver_tuple(local_raw)
    latest_tuple = _parse_semver_tuple(latest_raw)
    if local_tuple is not None and latest_tuple is not None:
        if local_tuple < latest_tuple:
            return "behind"
        if local_tuple > latest_tuple:
            return "ahead"
        return "equal"
    if local_raw.strip().lstrip("v") != latest_raw.strip().lstrip("v"):
        return "behind"
    return "equal"


def _configure_utf8_stdio() -> None:
    """Configure stdout/stderr en UTF-8 pour éviter les erreurs cp1252 sous Windows."""
    for stream in (sys.stdout, sys.stderr):
        reconfig = getattr(stream, "reconfigure", None)
        if callable(reconfig):
            try:
                reconfig(encoding="utf-8", errors="replace")
            except OSError:
                pass


def _write_utf8(path: Path, text: str) -> None:
    """Écrit un fichier texte en UTF-8 sans BOM avec fins de ligne LF."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _strip_volatile_json(obj):
    """Retourne une copie récursive sans les horodatages volatils (`synced_at`, `acked_at`)."""
    if isinstance(obj, dict):
        return {
            k: _strip_volatile_json(v)
            for k, v in obj.items()
            if k not in ("synced_at", "acked_at")
        }
    if isinstance(obj, list):
        return [_strip_volatile_json(item) for item in obj]
    return obj


def _write_json_if_changed(path: Path, payload: dict) -> bool:
    """Écrit un JSON sur disque uniquement si sa charge utile hors horodatages diffère."""
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if _strip_volatile_json(existing) == _strip_volatile_json(payload):
                return False
        except (OSError, json.JSONDecodeError):
            pass
    _write_utf8(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return True


def _strip_volatile_md(md_text: str) -> str:
    """Supprime les lignes de date/synchro volatiles pour éviter le churn Markdown."""
    cleaned = SYNC_LINE_RE.sub("", md_text)
    cleaned = DATE_LINE_RE.sub("", cleaned)
    return cleaned.replace("\r\n", "\n").strip()


def _strip_sync_line(md_text: str) -> str:
    """Alias conservé pour compatibilité : normalise le Markdown hors horodatages."""
    return _strip_volatile_md(md_text)


def _write_md_if_changed(path: Path, text: str) -> bool:
    """Écrit un Markdown sur disque uniquement si son contenu hors horodatages diffère."""
    normalized = text.replace("\r\n", "\n")
    if path.is_file():
        existing = path.read_text(encoding="utf-8", errors="replace")
        if _strip_volatile_md(existing) == _strip_volatile_md(normalized):
            return False
    _write_utf8(path, normalized)
    return True


def _editorial_prose_sha256(path: Path) -> str | None:
    """Calcule le SHA-256 de la prose éditoriale d'une fiche (blocs AUTO exclus)."""
    if not path.is_file():
        return None
    raw = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    without_auto = AUTO_BLOCK_RE.sub("", raw)
    normalized = "\n".join(line.rstrip() for line in without_auto.splitlines()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def default_architect_home(
    *,
    env: dict[str, str] | None = None,
    home_dir: Path | None = None,
) -> Path:
    """Résout le dossier centralisé Architect (`GRAVITY_ARCHITECT_HOME` > `GRAVITY_HOME/architect` > `~/.gemini/gravity/architect`)."""
    env_map = env if env is not None else os.environ
    architect_env = str(env_map.get("GRAVITY_ARCHITECT_HOME") or "").strip()
    if architect_env:
        return Path(architect_env).expanduser().resolve()
    gravity_env = str(env_map.get("GRAVITY_HOME") or "").strip()
    if gravity_env:
        return (Path(gravity_env).expanduser().resolve() / "architect").resolve()
    base_home = (home_dir if home_dir is not None else Path.home()).expanduser().resolve()
    return (base_home / ".gemini" / "gravity" / "architect").resolve()


def resolve_public_mode(cfg: dict | None) -> bool:
    """Retourne True si `privacy.public_mode` ou `public_mode` est activé."""
    if not isinstance(cfg, dict):
        return False
    privacy = cfg.get("privacy")
    if isinstance(privacy, dict) and "public_mode" in privacy:
        return bool(privacy.get("public_mode"))
    if "public_mode" in cfg:
        return bool(cfg.get("public_mode"))
    return False


def _is_machine_absolute_path(raw: str) -> bool:
    """Retourne True si `raw` est un chemin absolu machine (Windows, UNC ou POSIX)."""
    s = raw.strip()
    if not s:
        return False
    if Path(s).is_absolute():
        return True
    if s.startswith("/") or s.startswith("\\"):
        return True
    return bool(re.match(r"^[A-Za-z]:[\\/]", s))


def _tracked_project_keys(snapshot: dict) -> set[str]:
    """Retourne l'ensemble des identifiants (`id`, `plugin_name`) des projets suivis."""
    keys: set[str] = set()
    for proj in snapshot.get("projects") or []:
        if not isinstance(proj, dict):
            continue
        for val in (
            proj.get("id"),
            proj.get("plugin_name"),
            (proj.get("stable") or {}).get("plugin_name"),
        ):
            cleaned = str(val or "").strip()
            if cleaned:
                keys.add(cleaned)
    return keys


def _visible_installed_plugins(snapshot: dict, public_mode: bool) -> list[dict]:
    """Filtre `installed_plugins` aux seuls plugins suivis lorsque `public_mode` est actif."""
    installed = [
        p
        for p in ((snapshot.get("environment") or {}).get("installed_plugins") or [])
        if isinstance(p, dict)
    ]
    if not public_mode:
        return installed
    tracked = _tracked_project_keys(snapshot)
    return [p for p in installed if p.get("name") in tracked or p.get("dir") in tracked]


def _visible_orphan_plugin_dirs(snapshot: dict, public_mode: bool) -> list[str]:
    """Exclut les dossiers tiers hors projets suivis lorsque `public_mode` est actif."""
    orphans = list((snapshot.get("environment") or {}).get("orphan_plugin_dirs") or [])
    if not public_mode:
        return orphans
    tracked = _tracked_project_keys(snapshot)
    return [d for d in orphans if d in tracked]


def _format_project_display_path(proj: dict, *, public_mode: bool) -> str:
    """Formate le chemin affiché d'un projet en masquant tout chemin absolu machine en mode public."""
    pid = str(proj.get("id") or "project")
    raw_display = str(proj.get("display_path") or f"../{pid}").strip()
    if not public_mode:
        return raw_display
    if not _is_machine_absolute_path(raw_display) and not MACHINE_ABS_PATH_RE.search(raw_display):
        return raw_display.replace("\\", "/")
    return f"<repo:{pid}>"


def _collect_path_replacements(
    snapshot: dict | None = None,
    *,
    concept_root: Path | None = None,
    gemini_home: Path | None = None,
) -> list[tuple[str, str]]:
    """Construit la table ordonnée `(chemin_absolu, masque)` pour la sanitisation Markdown."""
    pairs: list[tuple[str, str]] = []

    def _add(raw_path: str | Path | None, token: str) -> None:
        if not raw_path:
            return
        s = str(raw_path).strip()
        if not s or not _is_machine_absolute_path(s):
            return
        variants = {s, s.rstrip("/\\"), s.replace("\\", "/"), s.replace("/", "\\")}
        try:
            res = str(Path(s).resolve())
            variants.update({res, res.replace("\\", "/"), res.replace("/", "\\")})
        except OSError:
            pass
        for v in variants:
            if len(v) >= 4:
                pairs.append((v, token))

    if isinstance(snapshot, dict):
        env = snapshot.get("environment") or {}
        for p in env.get("installed_plugins") or []:
            if isinstance(p, dict):
                _add(
                    p.get("install_path"),
                    f"<install:{p.get('name') or p.get('dir') or 'plugin'}>",
                )
        _add(env.get("plugins_dir"), "<plugins-dir>")
        _add(env.get("agy_path"), "<agy>")
        for proj in snapshot.get("projects") or []:
            if isinstance(proj, dict):
                pid = str(proj.get("id") or "project")
                _add(proj.get("path"), f"<repo:{pid}>")
                disp = str(proj.get("display_path") or "")
                if _is_machine_absolute_path(disp):
                    _add(disp, f"<repo:{pid}>")

    if concept_root is not None:
        _add(concept_root, "<workspace>")
    if gemini_home is not None:
        _add(gemini_home, "<gemini-home>")
    try:
        _add(Path.home() / ".gemini", "<gemini-home>")
        _add(Path.home(), "<home>")
    except OSError:
        pass

    dedup: dict[str, str] = {}
    for raw, tok in sorted(pairs, key=lambda item: len(item[0]), reverse=True):
        if raw not in dedup:
            dedup[raw] = tok
    return list(dedup.items())


def _sanitize_markdown_paths(
    text: str,
    *,
    replacements: list[tuple[str, str]] | None = None,
) -> str:
    """Masque les chemins absolus machine connus ou génériques dans un texte Markdown."""
    cleaned = text
    for raw_path, token in replacements or []:
        if raw_path in cleaned:
            cleaned = cleaned.replace(raw_path, token)
    return MACHINE_ABS_PATH_RE.sub("<path>", cleaned)


def resolve_workspace_root(
    config_arg: Path | None = None,
    workspace_arg: Path | None = None,
    cwd: Path | None = None,
    env: dict | None = None,
) -> tuple[Path, Path]:
    """Résout `(concept_root, config_path)` par paramètres, env ou auto-détection d'atelier."""
    if config_arg is not None:
        cfg_path = config_arg.expanduser().resolve()
        return cfg_path.parent, cfg_path

    if workspace_arg is not None:
        ws = workspace_arg.expanduser().resolve()
        return ws, ws / "projects.json"

    env_map = env if env is not None else os.environ
    env_ws = str(env_map.get("GRAVITY_ARCHITECT_WORKSPACE") or "").strip()
    if env_ws:
        ws = Path(env_ws).expanduser().resolve()
        return ws, ws / "projects.json"

    base_cwd = (cwd if cwd is not None else Path.cwd()).resolve()
    direct_cfg = base_cwd / "projects.json"
    if direct_cfg.is_file():
        return base_cwd, direct_cfg

    candidates: list[Path] = []
    for entry in sorted(base_cwd.iterdir(), key=lambda p: p.name.lower()):
        if not entry.is_dir():
            continue
        if entry.name.startswith(".") or entry.name in AUTO_DISCOVER_SKIP_DIRS:
            continue
        if (entry / "projects.json").is_file() and (entry / "ECOSYSTEM.md").is_file():
            candidates.append(entry)

    if len(candidates) == 1:
        ws = candidates[0].resolve()
        return ws, ws / "projects.json"
    if len(candidates) > 1:
        names = ", ".join(c.name for c in candidates)
        raise ValueError(
            f"Plusieurs ateliers détectés dans {base_cwd} ({names}) ; précisez --workspace."
        )
    raise FileNotFoundError(
        f"Aucun fichier projects.json trouvé dans {base_cwd} ni dans un sous-dossier atelier. "
        "Utilisez --workspace <dir> ou init_workspace.py."
    )


def load_config(config_path: Path) -> dict:
    """Charge la configuration JSON d'un atelier Gravity Architect."""
    text = config_path.read_text(encoding="utf-8-sig")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"Configuration invalide dans {config_path}: objet JSON attendu.")
    return data


def run_readonly_cmd(
    args: list[str],
    cwd: Path | None = None,
    timeout: int = 15,
) -> tuple[int, str, str]:
    """Exécute une commande sans shell=True et retourne (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except OSError as exc:
        return 127, "", str(exc)
    except subprocess.TimeoutExpired as exc:
        return 124, "", f"Délai expiré après {timeout}s ({exc})"


def _collect_plugin_tree_hashes(root_dir: Path) -> tuple[dict[str, str], str]:
    """Indexe les empreintes SHA-256 (LF normalisé) des fichiers significatifs d'un plugin."""
    hashes: dict[str, str] = {}
    for file_path in sorted(root_dir.rglob("*"), key=lambda p: p.as_posix()):
        if not file_path.is_file():
            continue
        rel_parts = file_path.relative_to(root_dir).parts
        if any(part in INSTALL_IGNORED_DIRS for part in rel_parts[:-1]):
            continue
        if file_path.name in INSTALL_ADAPTED_FILENAMES:
            continue
        if file_path.name.endswith(INSTALL_IGNORED_SUFFIXES):
            continue
        raw = file_path.read_bytes()
        if b"\x00" not in raw:
            raw = raw.replace(b"\r\n", b"\n")
        rel_posix = "/".join(rel_parts)
        hashes[rel_posix] = hashlib.sha256(raw).hexdigest()

    tree_digest = hashlib.sha256(
        "\n".join(f"{k}:{v}" for k, v in sorted(hashes.items())).encode("utf-8")
    ).hexdigest()
    return hashes, tree_digest


def compare_plugin_dirs(repo_plugin_dir: Path, installed_plugin_dir: Path) -> dict:
    """Compare le contenu d'un plugin dépôt et de sa copie installée hors adaptations OS."""
    if not repo_plugin_dir.is_dir() or not installed_plugin_dir.is_dir():
        return {
            "compared": False,
            "in_sync": False,
            "diff_files": [],
            "repo_sha256": None,
            "installed_sha256": None,
        }
    repo_hashes, repo_tree = _collect_plugin_tree_hashes(repo_plugin_dir)
    inst_hashes, inst_tree = _collect_plugin_tree_hashes(installed_plugin_dir)
    diff_files = sorted(
        k
        for k in (set(repo_hashes) | set(inst_hashes))
        if repo_hashes.get(k) != inst_hashes.get(k)
    )
    return {
        "compared": True,
        "in_sync": len(diff_files) == 0,
        "diff_files": diff_files,
        "repo_sha256": repo_tree,
        "installed_sha256": inst_tree,
    }


def _classify_porcelain_status(code: str) -> str:
    """Classe un code `git status --porcelain=v1` en catégorie agrégée."""
    if code == "??":
        return "untracked"
    if "D" in code:
        return "deleted"
    if "A" in code:
        return "added"
    if "M" in code or "R" in code or "C" in code:
        return "modified"
    return "other"


def _parse_porcelain_lines(raw_output: str) -> tuple[list[dict], dict]:
    """Parse `git status --porcelain=v1` en préservant le caractère d'index initial."""
    files: list[dict] = []
    counts = {
        "modified": 0,
        "added": 0,
        "deleted": 0,
        "untracked": 0,
        "other": 0,
        "total": 0,
    }
    for raw_line in raw_output.splitlines():
        line = raw_line.rstrip("\r\n")
        if len(line) < 4:
            continue
        code = line[:2]
        rel_path = line[3:]
        category = _classify_porcelain_status(code)
        counts[category] += 1
        counts["total"] += 1
        files.append({"status": code, "path": rel_path, "category": category})
    return files, counts


def _is_runtime_ignored_path(rel_path: str, ignore_prefixes: list[str]) -> bool:
    """Retourne True si `rel_path` correspond à un chemin runtime ignoré."""
    norm = rel_path.replace("\\", "/").strip().strip('"').rstrip("/")
    for prefix in ignore_prefixes:
        cleaned = prefix.replace("\\", "/").strip().rstrip("/")
        if cleaned and (norm == cleaned or norm.startswith(cleaned + "/")):
            return True
    return False


def extract_latest_changelog_section(text: str, max_lines: int = 45) -> dict:
    """Extrait la section récente et la dernière release réelle d'un CHANGELOG.md."""
    matches = list(CHANGELOG_SECTION_RE.finditer(text))
    if not matches:
        return {
            "latest_changelog_version": None,
            "latest_changelog_date": None,
            "latest_changelog_excerpt": "",
            "latest_released_changelog_version": None,
            "latest_released_changelog_date": None,
            "has_unreleased": False,
            "unreleased_has_content": False,
        }

    has_unreleased = False
    unreleased_has_content = False
    released_idx: int | None = None

    for idx, match in enumerate(matches):
        ver = match.group(1).strip()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[match.end() : end].strip()
        if ver.lower() == "unreleased":
            if not has_unreleased:
                has_unreleased = True
                unreleased_has_content = bool(body)
        elif released_idx is None:
            released_idx = idx

    chosen_idx = 0
    if (
        matches[0].group(1).strip().lower() == "unreleased"
        and not unreleased_has_content
        and released_idx is not None
    ):
        chosen_idx = released_idx

    chosen = matches[chosen_idx]
    chosen_end = (
        matches[chosen_idx + 1].start()
        if chosen_idx + 1 < len(matches)
        else len(text)
    )
    raw_lines = [
        line.rstrip() for line in text[chosen.start() : chosen_end].strip().splitlines()
    ]
    if len(raw_lines) > max_lines:
        raw_lines = raw_lines[:max_lines] + ["... (extrait tronqué)"]

    rel_match = matches[released_idx] if released_idx is not None else None
    return {
        "latest_changelog_version": chosen.group(1).strip(),
        "latest_changelog_date": chosen.group(2).strip() if chosen.group(2) else None,
        "latest_changelog_excerpt": "\n".join(raw_lines),
        "latest_released_changelog_version": (
            rel_match.group(1).strip() if rel_match else None
        ),
        "latest_released_changelog_date": (
            rel_match.group(2).strip() if (rel_match and rel_match.group(2)) else None
        ),
        "has_unreleased": has_unreleased,
        "unreleased_has_content": unreleased_has_content,
    }


def _extract_toml_section_value(text: str, section_name: str, key: str) -> str | None:
    """Extrait une valeur chaîne `key = "..."` dans une section TOML donnée (fallback 3.10)."""
    in_section = False
    target = section_name.strip().lower()
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        sec_m = re.match(r"^\[([^\]]+)\]$", line)
        if sec_m:
            in_section = sec_m.group(1).strip().lower() == target
            continue
        if in_section:
            kv_m = re.match(rf"^{re.escape(key)}\s*=\s*[\"']([^\"']+)[\"']\s*$", line)
            if kv_m:
                return kv_m.group(1).strip()
    return None


def parse_version_from_text(
    rel_path: str,
    text: str,
    version_json_path: str | None = None,
) -> dict:
    """Extrait `version`, `name` et `display_name` depuis divers formats standards de manifestes."""
    name = Path(rel_path).name.lower()
    result = {"version": None, "name": None, "display_name": None}

    if name.endswith(".json"):
        try:
            data = json.loads(text.lstrip("\ufeff"))
        except json.JSONDecodeError:
            return result
        if not isinstance(data, dict):
            return result
        result["name"] = data.get("name")
        result["display_name"] = data.get("displayName")
        if version_json_path:
            cur = data
            for part in version_json_path.split("."):
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    cur = None
                    break
            if isinstance(cur, str) and cur.strip():
                result["version"] = cur.strip()
        elif isinstance(data.get("version"), str) and data["version"].strip():
            result["version"] = data["version"].strip()
        return result

    if name == "pyproject.toml":
        if tomllib is not None:
            try:
                data = tomllib.loads(text)
                proj = data.get("project") if isinstance(data.get("project"), dict) else {}
                poetry = ((data.get("tool") or {}).get("poetry")) if isinstance(data.get("tool"), dict) else {}
                ver = proj.get("version") or (poetry.get("version") if isinstance(poetry, dict) else None)
                pkg_name = proj.get("name") or (poetry.get("name") if isinstance(poetry, dict) else None)
                result["version"] = str(ver).strip() if ver else None
                result["name"] = str(pkg_name).strip() if pkg_name else None
                return result
            except Exception:
                pass
        result["version"] = (
            _extract_toml_section_value(text, "project", "version")
            or _extract_toml_section_value(text, "tool.poetry", "version")
        )
        result["name"] = (
            _extract_toml_section_value(text, "project", "name")
            or _extract_toml_section_value(text, "tool.poetry", "name")
        )
        return result

    if name == "cargo.toml":
        if tomllib is not None:
            try:
                data = tomllib.loads(text)
                pkg = data.get("package") if isinstance(data.get("package"), dict) else {}
                ver = pkg.get("version")
                pkg_name = pkg.get("name")
                result["version"] = str(ver).strip() if ver else None
                result["name"] = str(pkg_name).strip() if pkg_name else None
                return result
            except Exception:
                pass
        result["version"] = _extract_toml_section_value(text, "package", "version")
        result["name"] = _extract_toml_section_value(text, "package", "name")
        return result

    if name == "setup.cfg":
        cp = configparser.ConfigParser()
        try:
            cp.read_string(text)
            if cp.has_section("metadata"):
                if cp.has_option("metadata", "version"):
                    val = cp.get("metadata", "version").strip()
                    if val and not val.startswith("attr:"):
                        result["version"] = val
                if cp.has_option("metadata", "name"):
                    result["name"] = cp.get("metadata", "name").strip() or None
        except configparser.Error:
            pass
        return result

    # VERSION ou fichier texte brut
    for line in text.splitlines():
        cleaned = line.strip()
        if cleaned and not cleaned.startswith("#"):
            result["version"] = cleaned
            break
    return result


def detect_plugin_manifest(project_cfg: dict, repo_dir: Path) -> str | None:
    """Résout le chemin relatif de `plugin.json` (`plugin/plugin.json` > `{id}-plugin/plugin.json` > `plugin.json`)."""
    explicit = project_cfg.get("plugin_manifest")
    if explicit:
        return str(explicit)

    project_id = str(project_cfg.get("id") or repo_dir.name)
    for candidate in (
        "plugin/plugin.json",
        f"{project_id}-plugin/plugin.json",
        "plugin.json",
    ):
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


def _git_branch_short_rev(repo_dir: Path, branch_name: str) -> str | None:
    """Retourne le hash court d'une branche locale si elle existe."""
    if not branch_name:
        return None
    rc, out, _ = run_readonly_cmd(
        ["git", "-C", str(repo_dir), "rev-parse", "--verify", "--short", branch_name]
    )
    return out.strip() if rc == 0 and out.strip() else None


def _git_show_text(repo_dir: Path, ref: str, rel_path: str) -> str | None:
    """Lit un fichier suivi depuis une révision Git spécifique en lecture seule."""
    if not ref or not rel_path:
        return None
    norm_rel = Path(rel_path).as_posix()
    rc, out, _ = run_readonly_cmd(
        ["git", "-C", str(repo_dir), "show", f"{ref}:{norm_rel}"]
    )
    return out if rc == 0 else None


def _git_is_ancestor(repo_dir: Path, ancestor_ref: str, descendant_ref: str) -> bool:
    """Retourne True si `ancestor_ref` est contenu dans l'historique de `descendant_ref`."""
    if not ancestor_ref or not descendant_ref:
        return False
    rc, _, _ = run_readonly_cmd(
        [
            "git",
            "-C",
            str(repo_dir),
            "merge-base",
            "--is-ancestor",
            ancestor_ref,
            descendant_ref,
        ]
    )
    return rc == 0


def _git_commits_ahead(
    repo_dir: Path,
    base_ref: str,
    head_ref: str,
    *,
    no_merges: bool = False,
) -> int:
    """Compte les commits présents dans `head_ref` mais absents de `base_ref`."""
    if not base_ref or not head_ref:
        return 0
    cmd = ["git", "-C", str(repo_dir), "rev-list", "--count"]
    if no_merges:
        cmd.append("--no-merges")
    cmd.append(f"{base_ref}..{head_ref}")
    rc, out, _ = run_readonly_cmd(cmd)
    return int(out.strip()) if rc == 0 and out.strip().isdigit() else 0


def _check_agents_doc(
    agents_path: Path,
    agents_rel: str,
    max_bytes: int | None,
    required_sections: list[str],
    issues: list[str],
) -> None:
    if not agents_path.is_file():
        issues.append(f"{agents_rel} manquant")
        return
    raw_bytes = agents_path.read_bytes()
    if max_bytes and len(raw_bytes) > max_bytes:
        issues.append(f"{agents_rel} > {max_bytes} o ({len(raw_bytes)} o)")
    agents_text = raw_bytes.decode("utf-8", errors="replace")
    headings = [m.group(1).strip().lower() for m in SECTION_RE.finditer(agents_text)]
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


def _evaluate_antigravity_plugin_compliance(
    project_cfg: dict,
    repo_dir: Path,
    issues: list[str],
) -> None:
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
                missing_fields = [
                    k for k in REQUIRED_OFFICIAL_PLUGIN_FIELDS if k not in manifest
                ]
                if missing_fields:
                    issues.append(
                        f"plugin.json: champs manquants ({', '.join(missing_fields)})"
                    )
                desc = str(manifest.get("description") or "")
                if not desc or len(desc) > 160:
                    issues.append("plugin.json: description vide ou > 160 car.")
                prompts = manifest.get("suggestedPrompts")
                if (
                    not isinstance(prompts, list)
                    or len(prompts) != 3
                    or not all(isinstance(p, str) and p.strip() for p in prompts)
                ):
                    issues.append("plugin.json: 3 suggestedPrompts requis")
        except (OSError, json.JSONDecodeError):
            issues.append("plugin.json JSON invalide")

    agents_rel = str(project_cfg.get("agents_file") or "AGENTS.md")
    _check_agents_doc(
        repo_dir / agents_rel,
        agents_rel,
        max_bytes=2500,
        required_sections=["Périmètre & Architecture", "Invariants", "Vérifications obligatoires"],
        issues=issues,
    )

    changelog_rel = str(project_cfg.get("changelog") or "CHANGELOG.md")
    changelog_path = repo_dir / changelog_rel
    if not changelog_path.is_file():
        issues.append(f"{changelog_rel} manquant")
    else:
        chg_text = changelog_path.read_text(encoding="utf-8", errors="replace")
        if not CHANGELOG_SECTION_RE.search(chg_text):
            issues.append(f"{changelog_rel}: aucune section ## [X.Y.Z]")

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
        _evaluate_antigravity_plugin_compliance(project_cfg, repo_dir, issues)

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
            _check_agents_doc(
                repo_dir / agents_rel,
                agents_rel,
                max_bytes=int(agents_max) if agents_max is not None else None,
                required_sections=req_secs,
                issues=issues,
            )

        if comp_cfg.get("require_changelog_semver"):
            changelog_rel = str(project_cfg.get("changelog") or "CHANGELOG.md")
            changelog_path = repo_dir / changelog_rel
            if not changelog_path.is_file():
                issues.append(f"{changelog_rel} manquant")
            else:
                chg_text = changelog_path.read_text(encoding="utf-8", errors="replace")
                if not CHANGELOG_SECTION_RE.search(chg_text):
                    issues.append(f"{changelog_rel}: aucune section ## [X.Y.Z]")

    return {"ok": len(issues) == 0, "issues": issues}


def evaluate_hot_budgets(
    concept_root: Path,
    budgets_cfg: dict | None,
    project_ids: list[str],
    watch_impact_files: list[str] | None = None,
) -> dict[str, dict]:
    """Vérifie que les fichiers Hot ne dépassent pas leur budget en octets."""
    merged = dict(DEFAULT_HOT_BUDGETS)
    if isinstance(budgets_cfg, dict):
        for k, v in budgets_cfg.items():
            if isinstance(v, (int, float)) and int(v) > 0:
                merged[k] = int(v)

    static_files = ["AGENTS.md", "ECOSYSTEM.md"]
    for imp in watch_impact_files or []:
        if imp and imp not in static_files:
            static_files.append(imp)

    report: dict[str, dict] = {}
    for rel_path in static_files:
        fpath = concept_root / rel_path
        if fpath.is_file():
            size = fpath.stat().st_size
            limit = int(merged.get(rel_path, 6000))
            report[rel_path] = {
                "bytes": size,
                "budget": limit,
                "over_budget": size > limit,
            }

    card_limit = int(merged.get("project_card_max_bytes", 3500))
    for pid in project_ids:
        rel_path = f"tracking/projects/{pid}.md"
        fpath = concept_root / rel_path
        if fpath.is_file():
            size = fpath.stat().st_size
            report[rel_path] = {
                "bytes": size,
                "budget": card_limit,
                "over_budget": size > card_limit,
            }
    return report


def _read_version_from_ref(
    repo_dir: Path,
    ref: str,
    version_rel: str | None,
    version_json_path: str | None = None,
) -> str | None:
    if not version_rel or not ref:
        return None
    raw = _git_show_text(repo_dir, ref, version_rel)
    if raw is None:
        return None
    return parse_version_from_text(version_rel, raw, version_json_path=version_json_path).get("version")


def collect_project_snapshot(
    project_cfg: dict,
    base_dir: Path,
    changelogs_dir: Path,
    installed_plugins_map: dict[str, dict] | None = None,
    dry_run: bool = False,
    concept_root: Path | None = None,
    default_preset: str = "generic",
) -> dict:
    """Collecte en lecture seule les métadonnées stables, conformité et WIP d'un dépôt suivi."""
    project_id = str(project_cfg["id"])
    raw_path_str = str(project_cfg["path"])
    raw_path = Path(raw_path_str)
    repo_dir = raw_path.resolve() if raw_path.is_absolute() else (base_dir / raw_path).resolve()
    dev_branch = str(project_cfg.get("default_dev_branch") or "dev")
    main_branch = str(project_cfg.get("main_branch") or "main")
    ignore_paths = list(project_cfg.get("runtime_ignore_paths") or [".agents/", ".agents"])
    preset = str(project_cfg.get("preset") or default_preset or "generic").strip().lower()
    version_json_path = project_cfg.get("version_json_path")

    archive_rel_prefix = "archives/changelogs"
    if concept_root is not None:
        try:
            archive_rel_prefix = changelogs_dir.resolve().relative_to(concept_root.resolve()).as_posix()
        except ValueError:
            pass

    snapshot: dict = {
        "id": project_id,
        "name": project_cfg.get("name", project_id),
        "plugin_name": project_cfg.get("plugin_name"),
        "role": project_cfg.get("role", ""),
        "preset": preset,
        "display_path": raw_path_str,
        "main_branch": main_branch,
        "default_dev_branch": dev_branch,
        "path": str(repo_dir),
        "exists": repo_dir.is_dir(),
        "is_git_repo": False,
        "stable": {
            "plugin_name": None,
            "display_name": None,
            "version": None,
            "version_source": None,
            "plugin_version": None,
            "installed_version": None,
            "installed_enabled": None,
            "install_drift": False,
            "install_content_compared": False,
            "install_content_drift": False,
            "install_content_diff_files": [],
            "latest_tag": None,
            "tags": [],
            "recent_commits": [],
            "has_changelog": False,
            "changelog_archive": None,
            "changelog_sha256": None,
            "latest_changelog_version": None,
            "latest_changelog_date": None,
            "latest_changelog_excerpt": "",
            "latest_released_changelog_version": None,
            "latest_released_changelog_date": None,
            "has_unreleased": False,
            "unreleased_has_content": False,
            "has_agents_md": False,
            "agents_md_sha256": None,
            "agents_md_lines": [],
            "compliance": {"ok": False, "issues": ["dépôt introuvable"]},
            "branches": {
                "main_branch": main_branch,
                "dev_branch": dev_branch,
                "main_head": None,
                "dev_head": None,
                "main_tag": None,
                "main_latest_tag": None,
                "latest_tag_on_main": True,
                "commits_since_latest_tag": 0,
                "main_plugin_version": None,
                "dev_plugin_version": None,
                "main_ahead_of_dev": 0,
                "dev_ahead_of_main": 0,
                "branch_drift": False,
            },
        },
        "wip": {
            "branch": None,
            "head": None,
            "is_dirty": False,
            "code_wip_count": 0,
            "runtime_only_wip": False,
            "counts": {
                "modified": 0,
                "added": 0,
                "deleted": 0,
                "untracked": 0,
                "other": 0,
                "total": 0,
            },
            "files": [],
        },
    }

    if not snapshot["exists"]:
        return snapshot

    snapshot["stable"]["compliance"] = evaluate_project_compliance(
        project_cfg, repo_dir, default_preset=preset
    )

    version_rel = detect_version_source(project_cfg, repo_dir, default_preset=preset)
    if version_rel:
        version_path = repo_dir / version_rel
        if version_path.is_file():
            try:
                parsed_ver = parse_version_from_text(
                    version_rel,
                    version_path.read_text(encoding="utf-8-sig", errors="replace"),
                    version_json_path=version_json_path,
                )
                snapshot["stable"]["version"] = parsed_ver["version"]
                snapshot["stable"]["version_source"] = version_rel
                snapshot["stable"]["plugin_version"] = parsed_ver["version"]
                snapshot["stable"]["plugin_name"] = parsed_ver["name"]
                snapshot["stable"]["display_name"] = parsed_ver["display_name"]
            except OSError:
                pass

    manifest_rel = detect_plugin_manifest(project_cfg, repo_dir)
    if preset == "antigravity-plugin" and installed_plugins_map:
        lookup_key = snapshot["stable"]["plugin_name"] or project_id
        installed_info = installed_plugins_map.get(lookup_key) or installed_plugins_map.get(
            project_id
        )
        if installed_info:
            inst_ver = installed_info.get("version")
            snapshot["stable"]["installed_version"] = inst_ver
            snapshot["stable"]["installed_enabled"] = installed_info.get("enabled", True)
            repo_ver = snapshot["stable"]["version"]
            snapshot["stable"]["install_drift"] = bool(
                repo_ver and inst_ver and repo_ver != inst_ver
            )
            inst_path_str = installed_info.get("install_path")
            plugin_src_rel = manifest_rel or version_rel
            if plugin_src_rel and inst_path_str:
                repo_plugin_dir = repo_dir / Path(str(plugin_src_rel)).parent
                cmp_res = compare_plugin_dirs(repo_plugin_dir, Path(inst_path_str))
                snapshot["stable"]["install_content_compared"] = cmp_res["compared"]
                if cmp_res["compared"]:
                    snapshot["stable"]["install_content_drift"] = not cmp_res["in_sync"]
                    snapshot["stable"]["install_content_diff_files"] = cmp_res["diff_files"][:10]

    changelog_rel = project_cfg.get("changelog") or ("CHANGELOG.md" if (repo_dir / "CHANGELOG.md").is_file() else None)
    if changelog_rel:
        changelog_path = repo_dir / str(changelog_rel)
        if changelog_path.is_file():
            changelog_text = changelog_path.read_text(encoding="utf-8", errors="replace")
            snapshot["stable"]["has_changelog"] = True
            snapshot["stable"]["changelog_archive"] = (
                f"{archive_rel_prefix}/{project_id}-CHANGELOG.md"
            )
            snapshot["stable"]["changelog_sha256"] = hashlib.sha256(
                changelog_text.encode("utf-8")
            ).hexdigest()
            snapshot["stable"].update(extract_latest_changelog_section(changelog_text))
            if not dry_run:
                archive_file = changelogs_dir / f"{project_id}-CHANGELOG.md"
                if (
                    not archive_file.is_file()
                    or archive_file.read_text(encoding="utf-8", errors="replace").replace(
                        "\r\n", "\n"
                    )
                    != changelog_text.replace("\r\n", "\n")
                ):
                    _write_utf8(archive_file, changelog_text.replace("\r\n", "\n"))

    agents_rel = project_cfg.get("agents_file", "AGENTS.md")
    if agents_rel:
        agents_path = repo_dir / str(agents_rel)
        if agents_path.is_file():
            agents_text = agents_path.read_text(encoding="utf-8", errors="replace")
            snapshot["stable"]["has_agents_md"] = True
            snapshot["stable"]["agents_md_sha256"] = hashlib.sha256(
                agents_text.encode("utf-8")
            ).hexdigest()
            snapshot["stable"]["agents_md_lines"] = agents_text.splitlines()

    rc, inside, _ = run_readonly_cmd(
        ["git", "-C", str(repo_dir), "rev-parse", "--is-inside-work-tree"]
    )
    if rc != 0 or inside.strip().lower() != "true":
        return snapshot

    snapshot["is_git_repo"] = True

    rc, tags_out, _ = run_readonly_cmd(
        ["git", "-C", str(repo_dir), "tag", "--sort=-v:refname"]
    )
    if rc == 0:
        tags = [t.strip() for t in tags_out.splitlines() if t.strip()][:10]
        snapshot["stable"]["tags"] = tags
        snapshot["stable"]["latest_tag"] = tags[0] if tags else None

    dev_head = _git_branch_short_rev(repo_dir, dev_branch)
    main_head = _git_branch_short_rev(repo_dir, main_branch)

    log_args = ["git", "-C", str(repo_dir), "log"]
    if dev_head:
        log_args.append(dev_branch)
    log_args.extend(["-n", "10", "--format=%h%x1f%cs%x1f%D%x1f%s"])
    rc, log_out, _ = run_readonly_cmd(log_args)
    if rc == 0:
        commits = []
        for row in log_out.splitlines():
            parts = row.split("\x1f")
            if len(parts) == 4:
                commits.append(
                    {
                        "hash": parts[0],
                        "date": parts[1],
                        "refs": parts[2],
                        "subject": parts[3],
                    }
                )
        snapshot["stable"]["recent_commits"] = commits

    main_tag = None
    main_latest_tag = None
    if main_head:
        rc, mtag_out, _ = run_readonly_cmd(
            ["git", "-C", str(repo_dir), "tag", "--points-at", main_branch, "--sort=-v:refname"]
        )
        if rc == 0:
            mtags = [t.strip() for t in mtag_out.splitlines() if t.strip()]
            main_tag = mtags[0] if mtags else None
        rc, mmerged_out, _ = run_readonly_cmd(
            ["git", "-C", str(repo_dir), "tag", "--merged", main_branch, "--sort=-v:refname"]
        )
        if rc == 0:
            merged_tags = [t.strip() for t in mmerged_out.splitlines() if t.strip()]
            main_latest_tag = merged_tags[0] if merged_tags else main_tag
        else:
            main_latest_tag = main_tag

    latest_tag = snapshot["stable"]["latest_tag"]
    latest_tag_on_main = (
        _git_is_ancestor(repo_dir, latest_tag, main_branch)
        if (latest_tag and main_head)
        else True
    )
    tag_target_ref = dev_branch if dev_head else "HEAD"
    commits_since_latest_tag = (
        _git_commits_ahead(repo_dir, latest_tag, tag_target_ref, no_merges=True)
        if latest_tag
        else 0
    )
    main_ver = _read_version_from_ref(
        repo_dir, main_branch if main_head else "", version_rel, version_json_path=version_json_path
    )
    dev_ver = _read_version_from_ref(
        repo_dir, dev_branch if dev_head else "", version_rel, version_json_path=version_json_path
    )
    if dev_ver is None:
        dev_ver = snapshot["stable"]["version"]

    main_ahead_of_dev = 0
    dev_ahead_of_main = 0
    if dev_head and main_head and dev_branch != main_branch:
        rc, cnt_out, _ = run_readonly_cmd(
            [
                "git",
                "-C",
                str(repo_dir),
                "rev-list",
                "--left-right",
                "--count",
                f"{main_branch}...{dev_branch}",
            ]
        )
        if rc == 0:
            parts = cnt_out.strip().split()
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                main_ahead_of_dev = int(parts[0])
                dev_ahead_of_main = int(parts[1])

    snapshot["stable"]["branches"] = {
        "main_branch": main_branch,
        "dev_branch": dev_branch,
        "main_head": main_head,
        "dev_head": dev_head,
        "main_tag": main_tag,
        "main_latest_tag": main_latest_tag,
        "latest_tag_on_main": latest_tag_on_main,
        "commits_since_latest_tag": commits_since_latest_tag,
        "main_plugin_version": main_ver,
        "dev_plugin_version": dev_ver,
        "main_ahead_of_dev": main_ahead_of_dev,
        "dev_ahead_of_main": dev_ahead_of_main,
        "branch_drift": (main_ahead_of_dev > 0 or dev_ahead_of_main > 0),
    }

    rc, branch_out, _ = run_readonly_cmd(
        ["git", "-C", str(repo_dir), "rev-parse", "--abbrev-ref", "HEAD"]
    )
    if rc == 0:
        snapshot["wip"]["branch"] = branch_out.strip()

    rc, head_out, _ = run_readonly_cmd(
        ["git", "-C", str(repo_dir), "rev-parse", "--short", "HEAD"]
    )
    if rc == 0:
        snapshot["wip"]["head"] = head_out.strip()

    rc, status_out, _ = run_readonly_cmd(
        ["git", "-C", str(repo_dir), "status", "--porcelain=v1"]
    )
    if rc == 0:
        wip_files, wip_counts = _parse_porcelain_lines(status_out)
        code_wip = [
            f for f in wip_files if not _is_runtime_ignored_path(f["path"], ignore_paths)
        ]
        snapshot["wip"]["files"] = wip_files
        snapshot["wip"]["counts"] = wip_counts
        snapshot["wip"]["is_dirty"] = wip_counts["total"] > 0
        snapshot["wip"]["code_wip_count"] = len(code_wip)
        snapshot["wip"]["runtime_only_wip"] = (
            wip_counts["total"] > 0 and len(code_wip) == 0
        )

    return snapshot


def collect_local_antigravity_env(gemini_home: Path | None = None) -> dict:
    """Inspecte en lecture seule `agy`, `config.json` et les plugins installés."""
    agy_bin = shutil.which("agy")
    agy_version = None
    if agy_bin:
        rc, out, err = run_readonly_cmd([agy_bin, "--version"], timeout=5)
        if rc == 0:
            agy_version = out.strip() or err.strip() or None

    home = gemini_home if gemini_home is not None else (Path.home() / ".gemini")
    config_path = home / "config" / "config.json"
    plugin_cfg_map: dict[str, dict] = {}
    if config_path.is_file():
        try:
            cfg_data = json.loads(config_path.read_text(encoding="utf-8-sig"))
            if isinstance(cfg_data, dict) and isinstance(cfg_data.get("plugins"), dict):
                plugin_cfg_map = cfg_data["plugins"]
        except (OSError, json.JSONDecodeError):
            plugin_cfg_map = {}

    plugins_dir = home / "config" / "plugins"
    installed_plugins: list[dict] = []
    orphan_plugin_dirs: list[str] = []
    if plugins_dir.is_dir():
        for entry in sorted(plugins_dir.iterdir(), key=lambda p: p.name.lower()):
            if not entry.is_dir():
                continue
            manifest_path = entry / "plugin.json"
            if not manifest_path.is_file():
                orphan_plugin_dirs.append(entry.name)
                continue
            plugin_info: dict = {
                "dir": entry.name,
                "name": entry.name,
                "display_name": None,
                "version": None,
                "install_path": str(entry),
                "enabled": True,
            }
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
                if isinstance(data, dict):
                    plugin_info["name"] = data.get("name", entry.name)
                    plugin_info["display_name"] = data.get("displayName")
                    plugin_info["version"] = data.get("version")
            except (OSError, json.JSONDecodeError):
                pass
            cfg_entry = plugin_cfg_map.get(plugin_info["name"]) or plugin_cfg_map.get(
                entry.name
            )
            if isinstance(cfg_entry, dict) and "enabled" in cfg_entry:
                plugin_info["enabled"] = bool(cfg_entry["enabled"])
            installed_plugins.append(plugin_info)

    return {
        "agy_path": agy_bin,
        "local_agy_version": agy_version,
        "plugins_dir": str(plugins_dir),
        "installed_plugins": installed_plugins,
        "orphan_plugin_dirs": orphan_plugin_dirs,
    }


def _clean_md_field(raw: str) -> str:
    """Nettoie un champ Markdown simple en conservant la valeur utile."""
    text = re.sub(r"\*?\([^)]*\)\*?", "", raw).strip()
    backticked = re.findall(r"`([^`]+)`", text)
    if backticked:
        for cand in backticked:
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", cand):
                return cand.strip()
    return text.strip("`* ").strip()


def _parse_artifact_file(path: Path, concept_root: Path) -> dict:
    """Extrait les métadonnées minimales d'une spec ou d'un handoff Markdown."""
    text = path.read_text(encoding="utf-8", errors="replace")
    title_match = MD_H1_RE.search(text)
    title = title_match.group(1).strip() if title_match else path.stem

    date_match = re.match(r"^(\d{4}-\d{2}-\d{2})-", path.name)
    date_str = date_match.group(1) if date_match else None

    status_match = STATUS_LINE_RE.search(text)
    status = _clean_md_field(status_match.group(1)) if status_match else "unknown"

    target_match = TARGET_LINE_RE.search(text)
    if target_match:
        raw_target = re.sub(r"\*?\([^)]*\)\*?", "", target_match.group(1)).strip()
        target_project = raw_target.replace("`", "").strip("* ").strip()
    else:
        target_project = ""

    return {
        "filename": path.name,
        "rel_path": path.relative_to(concept_root).as_posix(),
        "title": title,
        "date": date_str,
        "status": status,
        "target_project": target_project,
    }


def _scan_md_dir(directory: Path, concept_root: Path) -> list[dict]:
    if not directory.is_dir():
        return []
    return [
        _parse_artifact_file(path, concept_root)
        for path in sorted(directory.glob("*.md"), key=lambda p: p.name)
        if not path.name.startswith("_")
    ]


def collect_concept_artifacts(concept_root: Path) -> dict:
    """Inventorie specs/, specs/archive/, handoffs/ et handoffs/archive/ sans les _TEMPLATE.md."""
    specs_dir = concept_root / "specs"
    handoffs_dir = concept_root / "handoffs"
    return {
        "specs": _scan_md_dir(specs_dir, concept_root),
        "archived_specs": _scan_md_dir(specs_dir / "archive", concept_root),
        "pending_handoffs": _scan_md_dir(handoffs_dir, concept_root),
        "archived_handoffs": _scan_md_dir(handoffs_dir / "archive", concept_root),
    }


def extract_relevant_antigravity_bullets(
    block: str,
    keywords: list[str],
    max_bullets: int = 8,
    max_chars: int = 180,
) -> list[str]:
    """Filtre les puces d'une release Markdown selon des mots-clés optionnels."""
    kw_lower = [k.strip().lower() for k in keywords if str(k).strip()]
    results: list[str] = []
    for match in MD_BULLET_RE.finditer(block):
        cleaned = re.sub(r"\s+", " ", match.group(1)).strip()
        low = cleaned.lower()
        if not kw_lower or any(kw in low for kw in kw_lower):
            if len(cleaned) > max_chars:
                cleaned = cleaned[: max_chars - 1].rstrip() + "…"
            results.append(cleaned)
            if len(results) >= max_bullets:
                break
    return results


def _split_top_sections(markdown_text: str) -> dict[str, str]:
    """Découpe le changelog Markdown par titres de niveau 2 (`## Surface`)."""
    matches = list(SECTION_RE.finditer(markdown_text))
    sections: dict[str, str] = {}
    for idx, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(markdown_text)
        sections[heading] = markdown_text[start:end].strip()
    return sections


def parse_antigravity_changelog(
    markdown_text: str,
    surfaces: list[dict],
    releases_per_surface: int = 5,
    keywords: list[str] | None = None,
) -> dict[str, dict]:
    """Extrait jusqu'à `releases_per_surface` releases versionnées + digest filtré par surface."""
    sections = _split_top_sections(markdown_text)
    kw_list = keywords if keywords is not None else list(DEFAULT_WATCH_KEYWORDS)
    parsed: dict[str, dict] = {}

    for surface in surfaces:
        heading = str(surface["heading"])
        slug = str(surface["slug"])
        body = sections.get(heading, "")
        raw_blocks = [b.strip() for b in SEPARATOR_RE.split(body) if b.strip()] if body else []

        kept_blocks: list[str] = []
        versions: list[str] = []
        release_titles: dict[str, str] = {}
        release_digests: dict[str, list[str]] = {}

        for block in raw_blocks:
            version_match = VERSION_HEADING_RE.search(block)
            if version_match:
                if len(versions) >= releases_per_surface:
                    break
                ver = version_match.group(1)
                versions.append(ver)
                kept_blocks.append(block)
                rest = block[version_match.end():]
                title_match = SUB_HEADING_RE.search(rest)
                if title_match:
                    release_titles[ver] = title_match.group(1).strip()
                release_digests[ver] = extract_relevant_antigravity_bullets(
                    block, kw_list
                )
            else:
                if len(versions) < releases_per_surface:
                    kept_blocks.append(block)

        parsed[slug] = {
            "slug": slug,
            "heading": heading,
            "versions": versions,
            "release_titles": release_titles,
            "release_digests": release_digests,
            "latest_version": versions[0] if versions else None,
            "release_count": len(versions),
            "blocks": kept_blocks,
            "markdown": "\n\n---\n\n".join(kept_blocks),
        }

    return parsed


def parse_markdown_changelog_watch(
    markdown_text: str,
    watch_id: str,
    watch_name: str,
    releases_limit: int = 5,
    keywords: list[str] | None = None,
) -> dict[str, dict]:
    """Parse un changelog Keep a Changelog générique (`## [X.Y.Z] - YYYY-MM-DD`)."""
    matches = list(CHANGELOG_SECTION_RE.finditer(markdown_text))
    kw_list = keywords or []
    versions: list[str] = []
    release_titles: dict[str, str] = {}
    release_digests: dict[str, list[str]] = {}
    blocks: list[str] = []

    for idx, match in enumerate(matches):
        ver = match.group(1).strip()
        if ver.lower() == "unreleased":
            continue
        if len(versions) >= releases_limit:
            break
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(markdown_text)
        block = markdown_text[match.start() : end].strip()
        date_part = match.group(2).strip() if match.group(2) else ""
        versions.append(ver)
        blocks.append(block)
        if date_part:
            release_titles[ver] = date_part
        release_digests[ver] = extract_relevant_antigravity_bullets(block, kw_list)

    return {
        watch_id: {
            "slug": watch_id,
            "heading": watch_name,
            "versions": versions,
            "release_titles": release_titles,
            "release_digests": release_digests,
            "latest_version": versions[0] if versions else None,
            "release_count": len(versions),
            "blocks": blocks,
            "markdown": "\n\n---\n\n".join(blocks),
        }
    }


def fetch_url_text(url: str, timeout: int = 20) -> str:
    """Télécharge une ressource texte/Markdown via HTTPS."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "gravity-architect-sync/5.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_antigravity_changelog(url: str, timeout: int = 20) -> str:
    """Télécharge un changelog Markdown distant."""
    return fetch_url_text(url, timeout=timeout)


def render_surface_markdown(surface_data: dict, source_url: str, synced_at: str) -> str:
    """Formate l'archive Markdown lisible d'une surface de veille."""
    heading = surface_data["heading"]
    versions = ", ".join(surface_data["versions"]) if surface_data["versions"] else "aucune"
    lines = [
        f"# {heading} — Extrait officiel des dernières releases",
        "",
        f"- **Source officielle :** {source_url}",
        f"- **Synchronisé le :** `{synced_at}`",
        f"- **Dernière version :** `{surface_data['latest_version'] or 'n/a'}`",
        f"- **Versions archivées ({surface_data['release_count']}) :** {versions}",
        "",
        "---",
        "",
    ]
    body = surface_data.get("markdown", "").strip()
    if body:
        lines.append(body)
        lines.append("")
    else:
        lines.append("*Aucune release extraite pour cette surface.*")
        lines.append("")
    return "\n".join(lines)


def _normalize_watches_cfg(cfg: dict) -> list[dict]:
    """Unifie `watches` (v5) et la clé historique `antigravity` (v3/v4)."""
    if "watches" in cfg:
        watches = cfg.get("watches") or []
        return [dict(w) for w in watches if isinstance(w, dict) and w.get("id")]

    ag_cfg = cfg.get("antigravity")
    if isinstance(ag_cfg, dict) and ag_cfg.get("surfaces"):
        return [
            {
                "id": "antigravity",
                "name": "Google Antigravity",
                "type": "antigravity-changelog",
                "url": str(ag_cfg.get("changelog_url", "https://antigravity.google/docs/changelog.md")),
                "out_dir": "tracking/antigravity",
                "impact_file": "tracking/antigravity/IMPACT.md",
                "releases_per_surface": int(ag_cfg.get("releases_per_surface", 5)),
                "relevance_keywords": list(ag_cfg.get("relevance_keywords") or DEFAULT_WATCH_KEYWORDS),
                "surfaces": list(ag_cfg.get("surfaces") or []),
                "local_cli_check": {"cmd": "agy", "surface_slug": "cli"},
            }
        ]
    return []


def _collect_watches(
    watches_cfg: list[dict],
    out_dir: Path,
    concept_root: Path,
    releases_override: int | None,
    offline: bool,
    save_raw: bool,
    dry_run: bool,
    synced_at: str,
) -> dict[str, dict]:
    """Collecte les veilles configurées sans effet de bord si offline ou dry-run."""
    results: dict[str, dict] = {}
    for wcfg in watches_cfg:
        wid = str(wcfg["id"])
        wname = str(wcfg.get("name") or wid)
        wtype = str(wcfg.get("type") or "markdown-changelog")
        url = str(wcfg.get("url") or "")
        raw_out = wcfg.get("out_dir")
        watch_dir = (
            (concept_root / str(raw_out)).resolve()
            if raw_out
            else (out_dir / "watches" / wid).resolve()
        )
        releases_dir = watch_dir / "releases"
        summary_path = watch_dir / "summary.json"
        if not dry_run:
            watch_dir.mkdir(parents=True, exist_ok=True)
            releases_dir.mkdir(parents=True, exist_ok=True)

        existing_summary: dict = {}
        if summary_path.is_file():
            try:
                existing_summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing_summary = {}

        limit = (
            releases_override
            if releases_override is not None
            else int(wcfg.get("releases_per_surface", 5))
        )
        wres: dict = {
            "id": wid,
            "name": wname,
            "type": wtype,
            "source_url": url,
            "out_dir": str(wcfg.get("out_dir") or f"tracking/watches/{wid}"),
            "impact_file": wcfg.get("impact_file"),
            "releases_per_surface": limit,
            "fetch_status": "skipped" if (offline or not url) else "ok",
            "fetch_error": None,
            "synced_at": synced_at,
            "surfaces": existing_summary.get("surfaces", {}),
            "local_cli_check": wcfg.get("local_cli_check"),
        }

        if not offline and url:
            try:
                raw_md = fetch_antigravity_changelog(url)
                if save_raw and not dry_run:
                    raw_dir = watch_dir / "raw"
                    raw_dir.mkdir(parents=True, exist_ok=True)
                    _write_utf8(raw_dir / "changelog.md", raw_md.replace("\r\n", "\n"))

                keywords = list(wcfg.get("relevance_keywords") or [])
                if wtype == "antigravity-changelog":
                    parsed = parse_antigravity_changelog(
                        raw_md,
                        surfaces=list(wcfg.get("surfaces") or []),
                        releases_per_surface=limit,
                        keywords=keywords or list(DEFAULT_WATCH_KEYWORDS),
                    )
                else:
                    parsed = parse_markdown_changelog_watch(
                        raw_md,
                        watch_id=wid,
                        watch_name=wname,
                        releases_limit=limit,
                        keywords=keywords,
                    )

                surfaces_summary: dict = {}
                for slug, surface_data in parsed.items():
                    md_content = render_surface_markdown(surface_data, url, synced_at)
                    target_surface_file = releases_dir / f"{slug}.md"
                    if not dry_run:
                        _write_md_if_changed(target_surface_file, md_content)
                    surfaces_summary[slug] = {
                        "heading": surface_data["heading"],
                        "latest_version": surface_data["latest_version"],
                        "versions": surface_data["versions"],
                        "release_titles": surface_data.get("release_titles", {}),
                        "release_digests": surface_data.get("release_digests", {}),
                        "release_count": surface_data["release_count"],
                    }
                wres["surfaces"] = surfaces_summary
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                wres["fetch_status"] = "error"
                wres["fetch_error"] = str(exc)
                print(
                    f"[avertissement] Échec veille {wid} ({exc}) ; archives conservées.",
                    file=sys.stderr,
                )

        results[wid] = wres
    return results


def _format_installed_plugin_badge(plugin_info: dict) -> str:
    """Formate un badge plugin installé en indiquant s'il est désactivé."""
    ver = plugin_info.get("version") or "?"
    suffix = " *(désactivé)*" if plugin_info.get("enabled") is False else ""
    return f"`{plugin_info['name']}@{ver}`{suffix}"


def _format_main_release_cell(proj: dict) -> str:
    """Formate la cellule `Release (main)` d'un projet."""
    if not proj["exists"]:
        return "Dépôt absent"
    stable = proj["stable"]
    branches = stable.get("branches") or {}
    main_tag = branches.get("main_latest_tag") or branches.get("main_tag")
    main_head = branches.get("main_head")
    main_ver = branches.get("main_plugin_version")
    if main_tag and main_head:
        ver_note = (
            f" *(manifest `{main_ver}`)*"
            if main_ver and main_ver != main_tag.lstrip("v")
            else ""
        )
        return f"`{main_tag}` (`{main_head}`){ver_note}"
    if main_head:
        return f"`{main_ver or 'n/a'}` (`{main_head}`)"
    tag = stable.get("latest_tag") or stable.get("version") or "n/a"
    head = (proj.get("wip") or {}).get("head") or "?"
    return f"`{tag}` (`{head}`)"


def _format_dev_branch_cell(proj: dict) -> str:
    """Formate la cellule `Branche dev` (version + avance `main` + post-tag)."""
    if not proj["exists"]:
        return "—"
    stable = proj["stable"]
    branches = stable.get("branches") or {}
    dev_ver = branches.get("dev_plugin_version") or stable.get("version") or "n/a"
    main_b = branches.get("main_branch") or "main"
    latest_tag = stable.get("latest_tag")
    adv = branches.get("dev_ahead_of_main", 0)
    post = branches.get("commits_since_latest_tag", 0)
    notes: list[str] = []
    if adv > 0:
        notes.append(f"+{adv} vs `{main_b}`")
    if latest_tag and not branches.get("latest_tag_on_main", True):
        notes.append(f"tag `{latest_tag}`")
    if post > 0:
        notes.append(f"+{post} post-tag")
    if not notes and not branches.get("branch_drift"):
        return f"`{dev_ver}` *(alignée `{main_b}`)*"
    return f"`{dev_ver}` ({', '.join(notes)})" if notes else f"`{dev_ver}`"


def _format_installed_cell(proj: dict) -> str:
    """Formate la cellule `Installé local` (version + contenu + état activé)."""
    stable = proj["stable"]
    inst = stable.get("installed_version")
    if not inst:
        return "Non installé"
    flags: list[str] = []
    if stable.get("install_drift"):
        flags.append(f"≠ `{stable.get('version') or '?'}`")
    elif stable.get("install_content_drift"):
        cnt = len(stable.get("install_content_diff_files") or [])
        flags.append(f"contenu ≠ ({cnt} f.)")
    else:
        flags.append("aligné")
    if stable.get("installed_enabled") is False:
        flags.append("désactivé")
    return f"`{inst}` *({', '.join(flags)})*"


def _format_wip_cell(proj: dict) -> str:
    if not proj["exists"]:
        return "**Absent**"
    wip = proj["wip"]
    code_cnt = wip.get("code_wip_count", 0)
    if code_cnt == 0 and wip.get("runtime_only_wip"):
        return "**Propre** (`?? .agents/`)"
    if code_cnt == 0:
        return "**Propre**"
    return f"**{code_cnt} WIP** (`{wip.get('branch') or '?'}`)"


def _has_install_audit(snapshot: dict) -> bool:
    return any(
        p.get("preset") == "antigravity-plugin" for p in snapshot.get("projects") or []
    )


def render_ecosystem_snapshot_markdown(
    snapshot: dict,
    *,
    public_mode: bool | None = None,
    replacements: list[tuple[str, str]] | None = None,
) -> str:
    """Génère la synthèse Markdown séparant l'état stable (`main`), `dev`, et le WIP."""
    effective_public = resolve_public_mode(snapshot) if public_mode is None else public_mode
    env = snapshot.get("environment") or {}
    show_installed = _has_install_audit(snapshot)
    lines = [
        "# Snapshot Atelier & Veilles",
        "",
        f"- **Synchronisé le :** `{snapshot['synced_at']}`",
    ]
    if env.get("local_agy_version"):
        lines.append(f"- **CLI locale `agy` :** `{env['local_agy_version']}`")
    installed = _visible_installed_plugins(snapshot, effective_public)
    if show_installed:
        installed_fmt = (
            ", ".join(_format_installed_plugin_badge(p) for p in installed)
            if installed
            else "aucun"
        )
        lines.append(f"- **Plugins installés :** {installed_fmt}")
        orphans = _visible_orphan_plugin_dirs(snapshot, effective_public)
        if orphans:
            lines.append(
                f"- **Dossiers sans `plugin.json` :** {', '.join(f'`{d}`' for d in orphans)}"
            )

    lines.extend(["", "---", "", "## 1. Synthèse Projets (Stable vs WIP)", ""])
    if show_installed:
        lines.append(
            "| Projet | Release (`main`) | Branche `dev` | Installé | Dernier Tag | Conformité | État WIP |"
        )
        lines.append("|---|---|---|---|---|---|---|")
    else:
        lines.append(
            "| Projet | Release (`main`) | Branche `dev` | Dernier Tag | Conformité | État WIP |"
        )
        lines.append("|---|---|---|---|---|---|")

    for proj in snapshot["projects"]:
        stable = proj["stable"]
        wip = proj["wip"]
        comp = stable.get("compliance") or {}
        tag = stable["latest_tag"] or "n/a"
        comp_flag = "OK" if comp.get("ok") else f"{len(comp.get('issues') or [])} écart(s)"

        if not proj["exists"]:
            wip_summary = "Dépôt absent"
        else:
            c = wip["counts"]
            if wip.get("code_wip_count", c["total"]) == 0 and wip.get("runtime_only_wip"):
                wip_summary = "Propre *(runtime `.agents/` seul)*"
            elif c["total"] == 0:
                wip_summary = "Propre"
            else:
                wip_summary = (
                    f"**{wip.get('code_wip_count', c['total'])} code / {c['total']} total** "
                    f"(M:{c['modified']}, A:{c['added']}, D:{c['deleted']}, ??:{c['untracked']})"
                )
        if show_installed:
            lines.append(
                f"| **{proj['name']}** (`{proj['id']}`) | {_format_main_release_cell(proj)} | "
                f"{_format_dev_branch_cell(proj)} | {_format_installed_cell(proj)} | "
                f"`{tag}` | {comp_flag} | {wip_summary} |"
            )
        else:
            lines.append(
                f"| **{proj['name']}** (`{proj['id']}`) | {_format_main_release_cell(proj)} | "
                f"{_format_dev_branch_cell(proj)} | `{tag}` | {comp_flag} | {wip_summary} |"
            )

    lines.extend(["", "## 2. Détail par projet", ""])
    for proj in snapshot["projects"]:
        stable = proj["stable"]
        wip = proj["wip"]
        branches = stable.get("branches") or {}
        comp = stable.get("compliance") or {}
        lines.append(f"### {proj['name']} (`{proj['id']}`)")
        lines.append("")
        shown_path = (
            _format_project_display_path(proj, public_mode=True)
            if effective_public
            else proj["path"]
        )
        lines.append(f"- **Chemin :** `{shown_path}`")
        lines.append(f"- **Rôle :** {proj['role']}")
        lines.append("")
        lines.append("#### Releases & Historique Git (Stable)")
        inst_note = (
            f", installée : `{stable.get('installed_version') or 'n/a'}`"
            if proj.get("preset") == "antigravity-plugin"
            else ""
        )
        enabled_note = (
            ", désactivé dans `config.json`"
            if stable.get("installed_enabled") is False
            else ""
        )
        ver_src = stable.get("version_source") or "manifeste"
        lines.append(
            f"- **Version (`{ver_src}`) :** `{stable['version'] or 'n/a'}` "
            f"(`main` : `{branches.get('main_plugin_version') or 'n/a'}`{inst_note}{enabled_note})"
        )
        if stable.get("install_content_compared"):
            if stable.get("install_content_drift"):
                diffs = ", ".join(stable.get("install_content_diff_files") or [])
                lines.append(f"- **Contenu installé :** écart détecté (`{diffs}`)")
            else:
                lines.append("- **Contenu installé :** identique au dépôt (hors adaptations OS)")
        lines.append(
            f"- **Branches :** `{branches.get('dev_branch', 'dev')}` @ `{branches.get('dev_head') or 'n/a'}` "
            f"vs `{branches.get('main_branch', 'main')}` @ `{branches.get('main_head') or 'n/a'}` "
            f"(tag `main` : `{branches.get('main_latest_tag') or branches.get('main_tag') or 'aucun'}`, "
            f"post-tag : `{branches.get('commits_since_latest_tag', 0)}`)"
        )
        lines.append(
            f"- **Tags :** {', '.join(f'`{t}`' for t in stable['tags']) if stable['tags'] else 'aucun'}"
        )
        lines.append(
            f"- **Archive CHANGELOG :** `{stable['changelog_archive']}`"
            if stable["changelog_archive"]
            else "- **Archive CHANGELOG :** absent dans le dépôt"
        )
        if not comp.get("ok"):
            lines.append(
                f"- **Écarts conformité :** {'; '.join(comp.get('issues') or [])}"
            )
        if stable["recent_commits"]:
            lines.append("- **Derniers commits :**")
            for c in stable["recent_commits"][:5]:
                refs = f" *({c['refs']})*" if c["refs"] else ""
                lines.append(f"  - `{c['hash']}` ({c['date']}){refs} — {c['subject']}")
        lines.append("")
        lines.append("#### État de travail en cours (WIP non commité)")
        lines.append(
            f"- **Branche / HEAD :** `{wip['branch'] or 'n/a'}` @ `{wip['head'] or 'n/a'}` "
            f"(branche dev attendue : `{proj['default_dev_branch']}`)"
        )
        if wip["files"]:
            lines.append(f"- **Modifications en cours ({wip['counts']['total']}) :**")
            for f in wip["files"]:
                lines.append(f"  - `{f['status']}` `{f['path']}`")
        else:
            lines.append("- Aucune modification non commitée.")
        lines.append("")

    watches = snapshot.get("watches") or {}
    if watches:
        lines.extend(["## 3. Veilles configurées", ""])
        for wid, winfo in watches.items():
            lines.append(f"### {winfo.get('name', wid)} (`{winfo.get('fetch_status')}`)")
            if winfo.get("fetch_error"):
                lines.append(f"- **Erreur réseau :** `{winfo['fetch_error']}`")
            lines.append("")
            lines.append("| Surface | Dernière version | Versions suivies |")
            lines.append("|---|---|---|")
            for slug, sinfo in (winfo.get("surfaces") or {}).items():
                latest = sinfo.get("latest_version") or "n/a"
                vers = ", ".join(f"`{v}`" for v in sinfo.get("versions") or []) or "n/a"
                lines.append(f"| {sinfo.get('heading', slug)} | `{latest}` | {vers} |")
            lines.append("")
    rendered = "\n".join(lines).rstrip() + "\n"
    if effective_public:
        mask_pairs = (
            replacements
            if replacements is not None
            else _collect_path_replacements(snapshot)
        )
        rendered = _sanitize_markdown_paths(rendered, replacements=mask_pairs)
    return rendered


def _compute_unified_diff(
    old_lines: list[str],
    new_lines: list[str],
    project_id: str,
    max_lines: int = 35,
) -> list[str]:
    """Calcule un diff unifié compact sur `AGENTS.md`."""
    diff = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{project_id}/AGENTS.md",
            tofile=f"b/{project_id}/AGENTS.md",
            lineterm="",
            n=2,
        )
    )
    if len(diff) > max_lines:
        return diff[:max_lines] + ["... (diff AGENTS.md tronqué)"]
    return diff


def _build_acked_project_entry(proj: dict) -> dict:
    """Construit la baseline éditoriale acquittée pour un projet."""
    stable = proj.get("stable") or {}
    branches = stable.get("branches") or {}
    return {
        "tags": list(stable.get("tags") or []),
        "main_tag": branches.get("main_latest_tag") or branches.get("main_tag"),
        "plugin_version": stable.get("version") or stable.get("plugin_version"),
        "main_plugin_version": branches.get("main_plugin_version"),
        "changelog_sha256": stable.get("changelog_sha256"),
        "agents_md_sha256": stable.get("agents_md_sha256"),
        "agents_md_lines": list(stable.get("agents_md_lines") or []),
    }


def _build_acked_surface_entry(info: dict) -> dict:
    """Construit la baseline éditoriale acquittée pour une surface de veille."""
    return {"versions": list(info.get("versions") or [])}


def _snapshot_watches_map(snapshot: dict | None) -> dict[str, dict]:
    if not isinstance(snapshot, dict):
        return {}
    if isinstance(snapshot.get("watches"), dict):
        return snapshot["watches"]
    if isinstance(snapshot.get("antigravity"), dict):
        return {"antigravity": snapshot["antigravity"]}
    return {}


def _editorial_state_from_snapshot(snapshot: dict | None) -> dict | None:
    """Dérive une baseline éditoriale depuis un snapshot existant (migration v3/v4 -> v5)."""
    if not isinstance(snapshot, dict):
        return None
    projects_map: dict[str, dict] = {}
    for proj in snapshot.get("projects") or []:
        if isinstance(proj, dict) and proj.get("id"):
            projects_map[str(proj["id"])] = _build_acked_project_entry(proj)

    watches_map: dict[str, dict] = {}
    for wid, winfo in _snapshot_watches_map(snapshot).items():
        if not isinstance(winfo, dict):
            continue
        surfaces_map = {
            slug: _build_acked_surface_entry(sinfo)
            for slug, sinfo in (winfo.get("surfaces") or {}).items()
            if isinstance(sinfo, dict)
        }
        watches_map[str(wid)] = surfaces_map

    return {
        "schema_version": SCHEMA_VERSION,
        "acked_at": snapshot.get("synced_at"),
        "projects": projects_map,
        "watches": watches_map,
        "pending_editorial": {},
    }


def _load_editorial_state(state_path: Path, prev_snapshot: dict | None) -> dict | None:
    """Charge `editorial_state.json` ou migre doucement depuis `prev_snapshot`."""
    if state_path.is_file():
        try:
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                loaded.setdefault("projects", {})
                if "watches" not in loaded and isinstance(loaded.get("antigravity"), dict):
                    loaded["watches"] = {"antigravity": loaded["antigravity"]}
                loaded.setdefault("watches", {})
                loaded.setdefault("pending_editorial", {})
                return loaded
        except (OSError, json.JSONDecodeError):
            pass
    return _editorial_state_from_snapshot(prev_snapshot)


def _collect_project_hygiene_alerts(proj: dict, curr_branch: str | None) -> list[str]:
    """Construit les alertes d'hygiène et d'intégrité de versions pour un projet existant."""
    pid = proj["id"]
    stable = proj["stable"]
    wip = proj["wip"]
    branches = stable.get("branches") or {}
    comp = stable.get("compliance") or {"ok": True, "issues": []}
    curr_ver = stable.get("version")
    latest_tag = stable.get("latest_tag")
    alerts: list[str] = []

    if branches.get("dev_ahead_of_main", 0) > 0:
        m_ref = (
            branches.get("main_latest_tag")
            or branches.get("main_tag")
            or branches.get("main_head")
            or "?"
        )
        alerts.append(
            f"`{pid}` : `{branches['dev_branch']}` a {branches['dev_ahead_of_main']} commit(s) "
            f"d'avance sur `{branches['main_branch']}` (`{m_ref}`)."
        )
    if branches.get("main_ahead_of_dev", 0) > 0:
        alerts.append(
            f"`{pid}` : `{branches['main_branch']}` a {branches['main_ahead_of_dev']} commit(s) "
            f"absent(s) de `{branches['dev_branch']}`."
        )
    if latest_tag and branches.get("main_head") and not branches.get("latest_tag_on_main", True):
        alerts.append(
            f"`{pid}` : dernier tag release `{latest_tag}` absent de `{branches['main_branch']}`."
        )
    post_tag = branches.get("commits_since_latest_tag", 0)
    if post_tag > 0 and latest_tag:
        unrel_note = " (`[Unreleased]`)" if stable.get("unreleased_has_content") else ""
        alerts.append(
            f"`{pid}` : {post_tag} commit(s) non tagué(s) sur `{branches['dev_branch']}` "
            f"après `{latest_tag}`{unrel_note}."
        )
    if curr_ver and latest_tag and curr_ver.lstrip("v") != latest_tag.lstrip("v"):
        alerts.append(
            f"`{pid}` : version (`{curr_ver}`) ≠ dernier tag (`{latest_tag}`)."
        )
    rel_chg_ver = stable.get("latest_released_changelog_version")
    if curr_ver and rel_chg_ver and curr_ver.lstrip("v") != rel_chg_ver.lstrip("v"):
        alerts.append(
            f"`{pid}` : version (`{curr_ver}`) ≠ dernière release CHANGELOG (`{rel_chg_ver}`)."
        )
    if proj.get("preset") == "antigravity-plugin":
        if stable.get("install_drift"):
            diff_cnt = len(stable.get("install_content_diff_files") or [])
            diff_note = f" ({diff_cnt} fichier(s) différent(s))" if diff_cnt else ""
            alerts.append(
                f"`{pid}` : plugin installé (`{stable.get('installed_version')}`) "
                f"≠ manifeste dépôt (`{curr_ver}`){diff_note}."
            )
        elif stable.get("install_content_drift"):
            diff_files = stable.get("install_content_diff_files") or []
            sample = ", ".join(diff_files[:3])
            more = f", +{len(diff_files) - 3}" if len(diff_files) > 3 else ""
            alerts.append(
                f"`{pid}` : copie installée (`{stable.get('installed_version')}`) "
                f"diffère du dépôt à version égale ({len(diff_files)} fichier(s) : {sample}{more})."
            )
        if stable.get("installed_version") and stable.get("installed_enabled") is False:
            alerts.append(
                f"`{pid}` : plugin installé (`{stable.get('installed_version')}`) "
                "désactivé dans `config.json` (`enabled: false`)."
            )
    if wip.get("code_wip_count", 0) > 0:
        alerts.append(
            f"`{pid}` : {wip['code_wip_count']} fichier(s) de code en WIP non commité "
            f"sur `{curr_branch or '?'}`."
        )
    if not comp.get("ok") and comp.get("issues"):
        alerts.append(
            f"`{pid}` : conformité dépôt — {'; '.join(comp['issues'])}."
        )
    return alerts


def compute_delta_with_state(
    prev_snapshot: dict | None,
    curr_snapshot: dict,
    concept_root: Path,
    editorial_state: dict | None = None,
    ack_editorial: bool = False,
    public_mode: bool | None = None,
    replacements: list[tuple[str, str]] | None = None,
) -> tuple[dict, dict]:
    """Calcule le micro-delta avec persistance de l'état éditorial et auto-acquittement."""
    effective_public = (
        resolve_public_mode(curr_snapshot) if public_mode is None else public_mode
    )
    prev_projects_wip: dict[str, dict] = {}
    if isinstance(prev_snapshot, dict):
        for p in prev_snapshot.get("projects", []):
            if isinstance(p, dict) and p.get("id"):
                prev_projects_wip[str(p["id"])] = p

    base_state = (
        editorial_state
        if editorial_state is not None
        else _editorial_state_from_snapshot(prev_snapshot)
    )
    base_projects = (base_state or {}).get("projects") or {}
    base_watches = (base_state or {}).get("watches") or {}
    if not base_watches and isinstance((base_state or {}).get("antigravity"), dict):
        base_watches = {"antigravity": base_state["antigravity"]}
    base_pending = (base_state or {}).get("pending_editorial") or {}

    next_projects: dict[str, dict] = {}
    next_watches: dict[str, dict] = {}
    next_pending: dict[str, dict] = {}

    hygiene_alerts: list[str] = []
    editorial_targets: list[str] = []
    project_deltas: dict[str, dict] = {}

    for proj in curr_snapshot["projects"]:
        pid = proj["id"]
        stable = proj["stable"]
        wip = proj["wip"]
        branches = stable.get("branches") or {}
        comp = stable.get("compliance") or {"ok": True, "issues": []}
        card_rel = f"tracking/projects/{pid}.md"
        missing_card = proj["exists"] and not (concept_root / card_rel).is_file()

        curr_tags = list(stable.get("tags") or [])
        curr_ver = stable.get("version")
        curr_main_tag = branches.get("main_latest_tag") or branches.get("main_tag")
        curr_main_ver = branches.get("main_plugin_version")
        curr_head = wip.get("head")
        curr_branch = wip.get("branch")
        curr_chg_sha = stable.get("changelog_sha256")
        curr_agents_sha = stable.get("agents_md_sha256")
        curr_wip_pairs = sorted((f["status"], f["path"]) for f in wip.get("files") or [])

        prev_snap = prev_projects_wip.get(pid)
        if prev_snap is None:
            head_changed = bool(curr_head)
            branch_changed = False
            wip_changed = bool(wip.get("code_wip_count", 0) > 0)
        else:
            prev_wip = prev_snap.get("wip") or {}
            head_changed = curr_head != prev_wip.get("head")
            branch_changed = curr_branch != prev_wip.get("branch")
            prev_wip_pairs = sorted(
                (f["status"], f["path"]) for f in prev_wip.get("files") or []
            )
            wip_changed = curr_wip_pairs != prev_wip_pairs

        curr_prose_sha = _editorial_prose_sha256(concept_root / card_rel)
        pending_entry = base_pending.get(card_rel)
        auto_acked_prose = bool(
            pending_entry is not None
            and curr_prose_sha != pending_entry.get("prose_sha256_at_trigger")
        )
        is_acked = ack_editorial or auto_acked_prose
        prev_base = base_projects.get(pid)

        if is_acked:
            new_tags = []
            manifest_changed = False
            main_tag_changed = False
            main_manifest_changed = False
            changelog_changed = False
            agents_changed = False
            agents_diff = []
            missing_card_flag = False
        elif prev_base is None:
            new_tags = curr_tags
            manifest_changed = bool(curr_ver)
            main_tag_changed = False
            main_manifest_changed = False
            changelog_changed = bool(curr_chg_sha)
            agents_changed = bool(curr_agents_sha)
            agents_diff = []
            missing_card_flag = missing_card
        else:
            prev_tags = set(prev_base.get("tags") or [])
            new_tags = [t for t in curr_tags if t not in prev_tags]
            manifest_changed = curr_ver != prev_base.get("plugin_version")

            prev_main_tag = prev_base.get("main_tag")
            main_tag_changed = bool(
                prev_main_tag is not None and curr_main_tag != prev_main_tag
            )
            prev_main_ver = prev_base.get("main_plugin_version")
            main_manifest_changed = bool(
                prev_main_ver is not None and curr_main_ver != prev_main_ver
            )

            prev_chg_sha = prev_base.get("changelog_sha256")
            if prev_chg_sha is None:
                changelog_changed = bool(new_tags or manifest_changed)
            else:
                changelog_changed = curr_chg_sha != prev_chg_sha

            prev_agents_sha = prev_base.get("agents_md_sha256")
            if prev_agents_sha is None:
                agents_changed = False
                agents_diff = []
            else:
                agents_changed = curr_agents_sha != prev_agents_sha
                agents_diff = (
                    _compute_unified_diff(
                        list(prev_base.get("agents_md_lines") or []),
                        list(stable.get("agents_md_lines") or []),
                        pid,
                    )
                    if agents_changed
                    else []
                )
            missing_card_flag = missing_card

        needs_card = proj["exists"] and (
            new_tags
            or manifest_changed
            or main_tag_changed
            or main_manifest_changed
            or changelog_changed
            or agents_changed
            or missing_card_flag
        )
        if needs_card:
            if card_rel not in editorial_targets:
                editorial_targets.append(card_rel)
            trig_sha = (
                pending_entry["prose_sha256_at_trigger"]
                if pending_entry is not None
                else curr_prose_sha
            )
            next_pending[card_rel] = {"prose_sha256_at_trigger": trig_sha}
            if prev_base is not None:
                next_projects[pid] = prev_base
        elif proj["exists"]:
            next_projects[pid] = _build_acked_project_entry(proj)

        project_deltas[pid] = {
            "id": pid,
            "exists": proj["exists"],
            "new_tags": new_tags,
            "manifest_version_changed": manifest_changed,
            "version": curr_ver,
            "plugin_version": curr_ver,
            "installed_version": stable.get("installed_version"),
            "installed_enabled": stable.get("installed_enabled"),
            "install_drift": bool(stable.get("install_drift")),
            "install_content_drift": bool(stable.get("install_content_drift")),
            "install_content_diff_files": list(
                stable.get("install_content_diff_files") or []
            ),
            "head_changed": head_changed,
            "branch_changed": branch_changed,
            "changelog_changed": changelog_changed,
            "latest_changelog_excerpt": (
                stable.get("latest_changelog_excerpt", "") if changelog_changed else ""
            ),
            "agents_md_changed": agents_changed,
            "agents_md_diff": agents_diff,
            "wip_changed": wip_changed,
            "code_wip_count": wip.get("code_wip_count", 0),
            "runtime_only_wip": bool(wip.get("runtime_only_wip")),
            "branch_drift": bool(branches.get("branch_drift")),
            "compliance": comp,
            "missing_project_card": missing_card_flag,
        }

        if proj["exists"]:
            hygiene_alerts.extend(_collect_project_hygiene_alerts(proj, curr_branch))

    # Delta des veilles configurées
    watches_curr = _snapshot_watches_map(curr_snapshot)
    watch_deltas: dict[str, dict] = {}
    any_watch_auto_acked = False
    env = curr_snapshot.get("environment") or {}

    for wid, winfo in watches_curr.items():
        impact_rel = str(winfo.get("impact_file") or "")
        curr_imp_prose = _editorial_prose_sha256(concept_root / impact_rel) if impact_rel else None
        pending_w = base_pending.get(impact_rel) if impact_rel else None
        auto_acked_w = bool(
            pending_w is not None
            and curr_imp_prose != pending_w.get("prose_sha256_at_trigger")
        )
        if auto_acked_w:
            any_watch_auto_acked = True
        w_acked = ack_editorial or auto_acked_w
        base_w_surfaces = base_watches.get(wid) or {}
        next_w_surfaces: dict[str, dict] = {}
        w_surf_deltas: dict[str, dict] = {}
        any_new = False

        for slug, sinfo in (winfo.get("surfaces") or {}).items():
            curr_versions = list(sinfo.get("versions") or [])
            prev_s = base_w_surfaces.get(slug)
            prev_versions = set((prev_s or {}).get("versions") or [])
            if w_acked:
                new_releases = []
            elif base_state is None or prev_s is None:
                new_releases = curr_versions
            else:
                new_releases = [v for v in curr_versions if v not in prev_versions]

            titles = sinfo.get("release_titles") or {}
            digests = sinfo.get("release_digests") or {}
            w_surf_deltas[slug] = {
                "heading": sinfo.get("heading", slug),
                "latest_version": sinfo.get("latest_version"),
                "new_releases": [
                    {
                        "version": v,
                        "title": titles.get(v, ""),
                        "digest": digests.get(v, []),
                    }
                    for v in new_releases
                ],
            }
            if new_releases:
                any_new = True

        missing_impact = bool(
            impact_rel
            and winfo.get("fetch_status") == "ok"
            and not (concept_root / impact_rel).is_file()
        )
        if impact_rel and not w_acked and (any_new or missing_impact):
            if impact_rel not in editorial_targets:
                editorial_targets.append(impact_rel)
            trig_w_sha = (
                pending_w["prose_sha256_at_trigger"]
                if pending_w is not None
                else curr_imp_prose
            )
            next_pending[impact_rel] = {"prose_sha256_at_trigger": trig_w_sha}
            for slug in (winfo.get("surfaces") or {}):
                if slug in base_w_surfaces:
                    next_w_surfaces[slug] = base_w_surfaces[slug]
        else:
            for slug, sinfo in (winfo.get("surfaces") or {}).items():
                next_w_surfaces[slug] = _build_acked_surface_entry(sinfo)

        next_watches[wid] = next_w_surfaces
        watch_deltas[wid] = {
            "id": wid,
            "name": winfo.get("name", wid),
            "fetch_status": winfo.get("fetch_status"),
            "surfaces": w_surf_deltas,
        }

        cli_check = winfo.get("local_cli_check")
        if isinstance(cli_check, dict):
            cmd_name = str(cli_check.get("cmd") or "agy")
            surf_slug = str(cli_check.get("surface_slug") or "cli")
            local_cli_ver = env.get("local_agy_version") if cmd_name == "agy" else None
            surf_latest = ((winfo.get("surfaces") or {}).get(surf_slug) or {}).get("latest_version")
            if (
                local_cli_ver
                and surf_latest
                and _compare_cli_versions(str(local_cli_ver), str(surf_latest)) == "behind"
            ):
                hygiene_alerts.append(
                    f"`{cmd_name}` local (`{local_cli_ver}`) en retrait par rapport à "
                    f"{winfo.get('name', wid)} CLI (`{surf_latest}`)."
                )

    if _has_install_audit(curr_snapshot):
        orphan_dirs = _visible_orphan_plugin_dirs(curr_snapshot, effective_public)
        if orphan_dirs:
            hygiene_alerts.append(
                "Plugins locaux : dossier(s) sans `plugin.json` "
                f"({', '.join(f'`{d}`' for d in orphan_dirs)})."
            )

    if effective_public:
        mask_pairs = (
            replacements
            if replacements is not None
            else _collect_path_replacements(curr_snapshot, concept_root=concept_root)
        )
        hygiene_alerts = [
            _sanitize_markdown_paths(alert, replacements=mask_pairs)
            for alert in hygiene_alerts
        ]

    ag_watch = watch_deltas.get("antigravity") or {}
    fetch_status_summary = (
        ag_watch.get("fetch_status")
        if ag_watch
        else (
            next(iter(watch_deltas.values())).get("fetch_status")
            if watch_deltas
            else "none"
        )
    )

    delta_payload = {
        "schema_version": SCHEMA_VERSION,
        "synced_at": curr_snapshot["synced_at"],
        "public_mode": effective_public,
        "fetch_status": fetch_status_summary,
        "needs_editorial_update": len(editorial_targets) > 0,
        "editorial_targets": editorial_targets,
        "hygiene_alerts": hygiene_alerts,
        "auto_updated_files": [],
        "projects": project_deltas,
        "watches": watch_deltas,
        "antigravity": ag_watch.get("surfaces", {}),
    }

    any_project_auto_acked = any(
        base_pending.get(f"tracking/projects/{p['id']}.md") is not None
        and _editorial_prose_sha256(concept_root / f"tracking/projects/{p['id']}.md")
        != base_pending[f"tracking/projects/{p['id']}.md"].get("prose_sha256_at_trigger")
        for p in curr_snapshot["projects"]
    )
    acked_ts = (
        (base_state or {}).get("acked_at") or curr_snapshot["synced_at"]
        if next_pending and not ack_editorial and not any_project_auto_acked and not any_watch_auto_acked
        else curr_snapshot["synced_at"]
    )
    next_editorial_state = {
        "schema_version": SCHEMA_VERSION,
        "acked_at": acked_ts,
        "projects": next_projects,
        "watches": next_watches,
        "pending_editorial": next_pending,
    }
    return delta_payload, next_editorial_state


def compute_delta(
    prev_snapshot: dict | None,
    curr_snapshot: dict,
    concept_root: Path,
    editorial_state: dict | None = None,
    ack_editorial: bool = False,
    public_mode: bool | None = None,
) -> dict:
    """Calcule le micro-delta entre le snapshot précédent et le snapshot courant."""
    delta, _ = compute_delta_with_state(
        prev_snapshot=prev_snapshot,
        curr_snapshot=curr_snapshot,
        concept_root=concept_root,
        editorial_state=editorial_state,
        ack_editorial=ack_editorial,
        public_mode=public_mode,
    )
    return delta


def _append_budget_alerts(delta: dict, hot_budgets: dict[str, dict]) -> None:
    """Met à jour les alertes d'hygiène pour tout fichier Hot dépassant son budget en octets."""
    budget_prefixes = tuple(f"`{rel_path}` :" for rel_path in hot_budgets)
    cleaned = [
        alert
        for alert in (delta.get("hygiene_alerts") or [])
        if not (alert.startswith(budget_prefixes) and "> budget " in alert)
    ]
    for rel_path, info in sorted(hot_budgets.items()):
        if info.get("over_budget"):
            cleaned.append(f"`{rel_path}` : {info['bytes']} o > budget {info['budget']} o.")
    delta["hygiene_alerts"] = cleaned


def render_delta_markdown(
    delta: dict,
    dry_run: bool = False,
    *,
    replacements: list[tuple[str, str]] | None = None,
) -> str:
    """Formate le micro-delta ultra-compact pour consommation LLM à coût minimal."""
    status = (
        "EDITORIAL_UPDATE_REQUIRED"
        if delta.get("needs_editorial_update")
        else "NO_EDITORIAL_CHANGES"
    )
    auto_files = delta.get("auto_updated_files") or []
    targets = delta.get("editorial_targets") or []
    alerts = delta.get("hygiene_alerts") or []

    mode_label = " [DRY-RUN]" if dry_run else ""
    lines = [
        f"# Gravity Architect — Delta de synchronisation{mode_label}",
        "",
        f"- **Date :** `{delta['synced_at']}`",
        f"- **Statut éditorial :** `{status}`",
        f"- **Veilles :** `{delta.get('fetch_status')}`",
        (
            f"- **Fichiers auto-mis à jour (0 token) :** {', '.join(f'`{f}`' for f in auto_files)}"
            if auto_files
            else "- **Fichiers auto-mis à jour (0 token) :** aucun"
        ),
        (
            f"- **Cibles éditoriales LLM :** {', '.join(f'`{t}`' for t in targets)}"
            if targets
            else "- **Cibles éditoriales LLM :** aucune"
        ),
        "",
    ]

    if alerts:
        lines.append("## Alertes hygiène")
        for alert in alerts:
            lines.append(f"- {alert}")
        lines.append("")

    changed_projects = [
        pd
        for pd in (delta.get("projects") or {}).values()
        if pd["new_tags"]
        or pd["manifest_version_changed"]
        or pd["changelog_changed"]
        or pd["agents_md_changed"]
        or pd["wip_changed"]
        or pd["missing_project_card"]
    ]
    if changed_projects:
        lines.append("## Changements projets détectés")
        for pd in changed_projects:
            flags = []
            if pd["new_tags"]:
                flags.append(f"nouveaux tags: {', '.join(pd['new_tags'])}")
            if pd["manifest_version_changed"]:
                flags.append(f"version={pd['version']}")
            if pd["changelog_changed"]:
                flags.append("CHANGELOG.md modifié")
            if pd["agents_md_changed"]:
                flags.append("AGENTS.md modifié")
            if pd["wip_changed"]:
                flags.append(f"WIP code={pd['code_wip_count']}")
            if pd["missing_project_card"]:
                flags.append("fiche projet manquante")
            lines.append(f"### `{pd['id']}` — {'; '.join(flags)}")
            if pd["latest_changelog_excerpt"]:
                lines.append("")
                lines.append("```markdown")
                lines.append(pd["latest_changelog_excerpt"])
                lines.append("```")
            if pd["agents_md_diff"]:
                lines.append("")
                lines.append("```diff")
                lines.extend(pd["agents_md_diff"])
                lines.append("```")
            lines.append("")

    watch_changes: list[tuple[str, dict]] = []
    for wid, wdelta in (delta.get("watches") or {}).items():
        for slug, sinfo in (wdelta.get("surfaces") or {}).items():
            if sinfo.get("new_releases"):
                watch_changes.append((wdelta.get("name", wid), sinfo))

    if watch_changes:
        lines.append("## Nouvelles releases (veilles)")
        char_budget = 1200
        used_chars = 0
        for _wname, info in watch_changes:
            for rel in info["new_releases"]:
                title = f" — *{rel['title']}*" if rel.get("title") else ""
                header = f"- **{info['heading']}** `{rel['version']}`{title}"
                lines.append(header)
                used_chars += len(header)
                for bullet in rel.get("digest") or []:
                    if used_chars + len(bullet) > char_budget:
                        lines.append("  - *(digest plafonné)*")
                        break
                    lines.append(f"  - {bullet}")
                    used_chars += len(bullet) + 4
        lines.append("")

    rendered = "\n".join(lines).rstrip() + "\n"
    if delta.get("public_mode"):
        mask_pairs = replacements if replacements is not None else _collect_path_replacements()
        rendered = _sanitize_markdown_paths(rendered, replacements=mask_pairs)
    return rendered


def replace_auto_block(text: str, block_id: str, new_body: str) -> tuple[str, bool]:
    """Remplace strictement le corps entre `<!-- AUTO:START:<id> -->` et `<!-- AUTO:END:<id> -->`."""
    start_marker = f"<!-- AUTO:START:{block_id} -->"
    end_marker = f"<!-- AUTO:END:{block_id} -->"
    pattern = re.compile(
        re.escape(start_marker) + r".*?" + re.escape(end_marker),
        re.DOTALL,
    )
    if not pattern.search(text):
        return text, False
    cleaned_body = new_body.strip("\r\n")
    replacement = f"{start_marker}\n{cleaned_body}\n{end_marker}"
    updated = pattern.sub(lambda _m: replacement, text, count=1)
    changed = updated.replace("\r\n", "\n") != text.replace("\r\n", "\n")
    return updated, changed


def _format_project_handoffs_block(pid: str, artifacts: dict) -> str:
    target_re = re.compile(rf"(?<![a-z0-9-]){re.escape(pid.lower())}(?![a-z0-9-])")

    def _matches(item: dict) -> bool:
        target = (item.get("target_project") or "").lower()
        if target:
            return bool(target_re.search(target))
        return f"-{pid.lower()}-" in item["filename"].lower()

    pending = [h for h in artifacts.get("pending_handoffs", []) if _matches(h)]
    archived = [h for h in artifacts.get("archived_handoffs", []) if _matches(h)]
    lines: list[str] = []
    if pending:
        lines.append("- **Handoffs en attente (`handoffs/`) :**")
        for h in pending:
            lines.append(
                f"  - [`{h['filename']}`](../../{h['rel_path']}) (`{h['status']}`) — *{h['title']}*"
            )
    else:
        lines.append("- **Handoffs en attente (`handoffs/`) :** aucun.")
    if archived:
        lines.append("- **Handoffs archivés (`handoffs/archive/`) :**")
        for h in archived[-3:]:
            lines.append(
                f"  - [`{h['filename']}`](../../{h['rel_path']}) (`{h['status']}`)"
            )
        if len(archived) > 3:
            lines.append(
                f"  - *(+{len(archived) - 3} plus anciens dans `handoffs/archive/`)*"
            )
    return "\n".join(lines)


def _build_ecosystem_blocks(
    snapshot: dict,
    delta: dict,
    concept_root: Path,
    *,
    public_mode: bool | None = None,
    replacements: list[tuple[str, str]] | None = None,
) -> dict[str, str]:
    effective_public = resolve_public_mode(snapshot) if public_mode is None else public_mode
    sync_date = snapshot["synced_at"][:10]
    env = snapshot.get("environment") or {}
    show_installed = _has_install_audit(snapshot)

    meta_lines = [
        "- **Espace de conception :** atelier courant *(lecture seule stricte sur les dépôts suivis)*",
        f"- **Dernier snapshot :** [`tracking/snapshots/ecosystem_snapshot.md`](tracking/snapshots/ecosystem_snapshot.md) *({sync_date})*",
    ]
    if show_installed:
        agy_ver = env.get("local_agy_version") or "non détectée"
        installed = _visible_installed_plugins(snapshot, effective_public)
        installed_fmt = (
            ", ".join(_format_installed_plugin_badge(p) for p in installed)
            if installed
            else "aucun"
        )
        meta_lines.append(
            f"- **CLI locale `agy` :** `{agy_ver}` · **Plugins installés :** {installed_fmt}"
        )
    meta_lines.append("- **Charte :** [`AGENTS.md`](AGENTS.md) · **Archives :** [`archives/README.md`](archives/README.md)")
    meta_block = "\n".join(meta_lines)

    if show_installed:
        proj_lines = [
            "| Projet | Release (`main`) | Branche `dev` | Installé local | WIP | Fiche |",
            "|---|---|---|---|---|---|",
        ]
    else:
        proj_lines = [
            "| Projet | Release (`main`) | Branche `dev` | WIP | Fiche |",
            "|---|---|---|---|---|",
        ]
    for proj in snapshot["projects"]:
        pid = proj["id"]
        rel_path = _format_project_display_path(proj, public_mode=effective_public)
        card_rel = f"tracking/projects/{pid}.md"
        card_cell = (
            f"[`{pid}.md`]({card_rel})"
            if (concept_root / card_rel).is_file()
            else "*(absente)*"
        )
        if show_installed:
            proj_lines.append(
                f"| **{proj['name']}** (`{rel_path}`) | {_format_main_release_cell(proj)} | "
                f"{_format_dev_branch_cell(proj)} | {_format_installed_cell(proj)} | "
                f"{_format_wip_cell(proj)} | {card_cell} |"
            )
        else:
            proj_lines.append(
                f"| **{proj['name']}** (`{rel_path}`) | {_format_main_release_cell(proj)} | "
                f"{_format_dev_branch_cell(proj)} | {_format_wip_cell(proj)} | {card_cell} |"
            )

    watches_map = _snapshot_watches_map(snapshot)
    watch_lines: list[str] = []
    if watches_map:
        watch_lines.extend(
            [
                "| Surface | Dernière release | Versions archivées | Détails |",
                "|---|---|---|---|",
            ]
        )
        for wid, winfo in watches_map.items():
            w_out = str(winfo.get("out_dir") or f"tracking/watches/{wid}").rstrip("/")
            for slug, sinfo in (winfo.get("surfaces") or {}).items():
                latest = sinfo.get("latest_version") or "n/a"
                vers = ", ".join(f"`{v}`" for v in sinfo.get("versions") or []) or "n/a"
                watch_lines.append(
                    f"| **{sinfo.get('heading', slug)}** | `{latest}` | {vers} | "
                    f"[`{w_out}/releases/{slug}.md`]({w_out}/releases/{slug}.md) |"
                )
    else:
        watch_lines.append("- Aucune veille configurée dans `projects.json`.")

    artifacts = snapshot.get("artifacts") or {
        "specs": [],
        "archived_specs": [],
        "pending_handoffs": [],
        "archived_handoffs": [],
    }
    art_lines: list[str] = []
    if artifacts["specs"]:
        art_lines.append("- **Spécifications actives (`specs/`) :**")
        for s in artifacts["specs"]:
            art_lines.append(
                f"  - [`{s['filename']}`]({s['rel_path']}) (`{s['status']}`, cible : `{s['target_project'] or 'n/a'}`) — *{s['title']}*"
            )
    else:
        art_lines.append(
            "- **Spécifications actives (`specs/`) :** aucune *(modèle : [`specs/_TEMPLATE.md`](specs/_TEMPLATE.md))*."
        )
    if artifacts.get("archived_specs"):
        art_lines.append(
            f"- **Spécifications archivées (`specs/archive/`) :** {len(artifacts['archived_specs'])} *(ex. [`{artifacts['archived_specs'][-1]['filename']}`]({artifacts['archived_specs'][-1]['rel_path']}))*"
        )
    if artifacts["pending_handoffs"]:
        art_lines.append("- **Handoffs en attente (`handoffs/`) :**")
        for h in artifacts["pending_handoffs"]:
            art_lines.append(
                f"  - [`{h['filename']}`]({h['rel_path']}) (`{h['status']}`, cible : `{h['target_project'] or 'n/a'}`) — *{h['title']}*"
            )
    else:
        art_lines.append(
            "- **Handoffs en attente (`handoffs/`) :** aucun *(modèle : [`handoffs/_TEMPLATE.md`](handoffs/_TEMPLATE.md))*."
        )
    archived_handoffs = artifacts.get("archived_handoffs") or []
    if archived_handoffs:
        last_handoff = archived_handoffs[-1]
        art_lines.append(
            f"- **Handoffs archivés (`handoffs/archive/`) :** {len(archived_handoffs)} *(dernier : [`{last_handoff['filename']}`]({last_handoff['rel_path']}))*"
        )
    else:
        art_lines.append("- **Handoffs archivés (`handoffs/archive/`) :** aucun pour le moment.")

    alerts = delta.get("hygiene_alerts") or []
    hygiene_block = (
        "\n".join(f"- {a}" for a in alerts)
        if alerts
        else "- Aucune alerte d'hygiène détectée."
    )

    watch_body = "\n".join(watch_lines)
    blocks = {
        "ecosystem-meta": meta_block,
        "ecosystem-projects": "\n".join(proj_lines),
        "ecosystem-watches": watch_body,
        "ecosystem-antigravity": watch_body,
        "ecosystem-artifacts": "\n".join(art_lines),
        "ecosystem-hygiene": hygiene_block,
    }
    if effective_public:
        mask_pairs = (
            replacements
            if replacements is not None
            else _collect_path_replacements(snapshot, concept_root=concept_root)
        )
        blocks = {
            key: _sanitize_markdown_paths(val, replacements=mask_pairs)
            for key, val in blocks.items()
        }
    return blocks


def apply_auto_doc_updates(
    concept_root: Path,
    snapshot: dict,
    delta: dict,
    dry_run: bool = False,
    *,
    public_mode: bool | None = None,
    replacements: list[tuple[str, str]] | None = None,
) -> list[str]:
    """Met à jour les blocs `<!-- AUTO:START/END -->` des fiches vivantes existantes."""
    effective_public = resolve_public_mode(snapshot) if public_mode is None else public_mode
    mask_pairs = (
        (
            replacements
            if replacements is not None
            else _collect_path_replacements(snapshot, concept_root=concept_root)
        )
        if effective_public
        else None
    )
    updated_files: list[str] = []
    sync_date = snapshot["synced_at"][:10]
    artifacts = snapshot.get("artifacts") or {}

    # 1. ECOSYSTEM.md
    eco_path = concept_root / "ECOSYSTEM.md"
    if eco_path.is_file():
        original = eco_path.read_text(encoding="utf-8", errors="replace")
        current = original
        any_changed = False
        eco_blocks = _build_ecosystem_blocks(
            snapshot,
            delta,
            concept_root,
            public_mode=effective_public,
            replacements=mask_pairs,
        )
        for block_id, body in eco_blocks.items():
            current, changed = replace_auto_block(current, block_id, body)
            any_changed = any_changed or changed
        if any_changed:
            if not dry_run:
                _write_utf8(eco_path, current.replace("\r\n", "\n"))
            updated_files.append("ECOSYSTEM.md")

    # 2. tracking/projects/<id>.md
    for proj in snapshot["projects"]:
        pid = proj["id"]
        rel = f"tracking/projects/{pid}.md"
        card_path = concept_root / rel
        if not card_path.is_file():
            continue
        stable = proj["stable"]
        branches = stable.get("branches") or {}
        wip = proj["wip"]
        dev_b = branches.get("dev_branch") or proj.get("default_dev_branch") or "dev"
        main_b = branches.get("main_branch") or "main"
        display_path = _format_project_display_path(proj, public_mode=effective_public)

        chg_link = (
            f"[`{pid}-CHANGELOG.md`](../../archives/changelogs/{pid}-CHANGELOG.md)"
            if stable.get("has_changelog")
            else "**Absent**"
        )
        if not proj["exists"]:
            release_line = "dépôt introuvable"
            branch_line = "dépôt introuvable"
        else:
            main_tag = branches.get("main_latest_tag") or branches.get("main_tag")
            main_head = branches.get("main_head")
            dev_head = branches.get("dev_head") or wip.get("head")
            latest_tag = stable.get("latest_tag")
            dev_ver = branches.get("dev_plugin_version") or stable.get("version") or "n/a"
            adv = branches.get("dev_ahead_of_main", 0)
            post = branches.get("commits_since_latest_tag", 0)
            tag_dev_note = (
                f" *(tag `{latest_tag}` sur `{dev_b}`)*"
                if (latest_tag and not branches.get("latest_tag_on_main", True))
                else ""
            )
            release_line = (
                f"`{main_tag or 'aucune'}` (`{main_head or '?'}`) — {chg_link}{tag_dev_note}"
            )
            if branches.get("branch_drift") or post > 0:
                post_note = (
                    f", +{post} post-`{latest_tag}`" if (post > 0 and latest_tag) else ""
                )
                branch_line = (
                    f"`{dev_head or '?'}` (`+{adv}` vs `{main_b}`{post_note}), "
                    f"manifeste `{dev_ver}`"
                )
            else:
                branch_line = (
                    f"alignée sur `{main_b}` (`{dev_head or '?'}`), manifeste `{dev_ver}`"
                )

        if not proj["exists"]:
            wip_line = "Dépôt absent"
        elif wip.get("code_wip_count", 0) == 0 and wip.get("runtime_only_wip"):
            wip_line = "Propre *(runtime `.agents/` uniquement)*"
        elif wip.get("code_wip_count", 0) == 0:
            wip_line = "Propre (`0` fichier)"
        else:
            wip_line = f"**{wip['code_wip_count']} fichier(s) code WIP**"

        meta_lines = [
            f"- **Dépôt :** `{display_path}`",
            f"- **Rôle :** {proj['role']}",
            f"- **Release (`{main_b}`) :** {release_line}",
            f"- **Branche `{dev_b}` :** {branch_line}",
        ]
        if proj.get("preset") == "antigravity-plugin":
            meta_lines.append(f"- **Installé local :** {_format_installed_cell(proj)}")
        meta_lines.extend(
            [
                f"- **WIP en cours :** {wip_line}",
                f"- **Dernière synchro :** `{sync_date}`",
            ]
        )
        handoffs_body = _format_project_handoffs_block(pid, artifacts)
        meta_body = "\n".join(meta_lines)
        if effective_public:
            meta_body = _sanitize_markdown_paths(meta_body, replacements=mask_pairs)
            handoffs_body = _sanitize_markdown_paths(handoffs_body, replacements=mask_pairs)

        original = card_path.read_text(encoding="utf-8", errors="replace")
        current, ch1 = replace_auto_block(original, f"project-meta:{pid}", meta_body)
        current, ch2 = replace_auto_block(current, f"project-handoffs:{pid}", handoffs_body)
        if ch1 or ch2:
            if not dry_run:
                _write_utf8(card_path, current.replace("\r\n", "\n"))
            updated_files.append(rel)

    # 3. Fichiers d'impact des veilles
    env = snapshot.get("environment") or {}
    for wid, winfo in _snapshot_watches_map(snapshot).items():
        impact_rel = winfo.get("impact_file")
        if not impact_rel:
            continue
        impact_path = concept_root / str(impact_rel)
        if not impact_path.is_file():
            continue
        cli_check = winfo.get("local_cli_check") or {}
        local_agy = env.get("local_agy_version") or "non détectée"
        meta_lines = [
            f"- **Dernière synchro :** `{sync_date}`",
            f"- **Source officielle :** `{winfo.get('source_url')}`",
            "",
            "| Surface | Dernière version officielle | Versions suivies | Écart local |",
            "|---|---|---|---|",
        ]
        for slug, sinfo in (winfo.get("surfaces") or {}).items():
            latest = sinfo.get("latest_version") or "n/a"
            vers = ", ".join(f"`{v}`" for v in sinfo.get("versions") or []) or "n/a"
            if isinstance(cli_check, dict) and slug == cli_check.get("surface_slug"):
                if local_agy == "non détectée":
                    gap = f"`{local_agy}` local"
                else:
                    cmp_state = _compare_cli_versions(str(local_agy), str(latest))
                    if cmp_state == "behind":
                        gap = f"**`{local_agy}` local** *(écart)*"
                    elif cmp_state == "ahead":
                        gap = f"`{local_agy}` local *(en avance)*"
                    else:
                        gap = f"`{local_agy}` local"
            else:
                gap = "—"
            meta_lines.append(f"| **{sinfo.get('heading', slug)}** | `{latest}` | {vers} | {gap} |")

        original = impact_path.read_text(encoding="utf-8", errors="replace")
        body = "\n".join(meta_lines)
        if effective_public:
            body = _sanitize_markdown_paths(body, replacements=mask_pairs)
        current, ch = replace_auto_block(original, f"watch-meta:{wid}", body)
        if not ch and wid == "antigravity":
            current, ch = replace_auto_block(current, "antigravity-meta", body)
        if ch:
            if not dry_run:
                _write_utf8(impact_path, current.replace("\r\n", "\n"))
            if str(impact_rel) not in updated_files:
                updated_files.append(str(impact_rel))

    return updated_files


def run_sync(
    config_path: Path,
    out_dir: Path | None = None,
    releases_override: int | None = None,
    offline: bool = False,
    save_raw: bool = False,
    gemini_home: Path | None = None,
    concept_root: Path | None = None,
    dry_run: bool = False,
    apply_docs: bool = True,
    ack_editorial: bool = False,
    public_mode: bool | None = None,
) -> tuple[dict, dict]:
    """Exécute la synchronisation complète et retourne `(snapshot, delta)`."""
    cfg = load_config(config_path)
    effective_public = resolve_public_mode(cfg) if public_mode is None else public_mode
    base_dir = config_path.resolve().parent
    resolved_concept_root = (
        concept_root.resolve() if concept_root is not None else base_dir
    )
    resolved_out_dir = (
        out_dir.resolve() if out_dir is not None else (resolved_concept_root / "tracking")
    )
    synced_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    changelogs_dir = resolved_concept_root / "archives" / "changelogs"
    snapshots_dir = resolved_out_dir / "snapshots"
    if not dry_run:
        changelogs_dir.mkdir(parents=True, exist_ok=True)
        snapshots_dir.mkdir(parents=True, exist_ok=True)

    prev_snapshot_path = snapshots_dir / "ecosystem_snapshot.json"
    prev_snapshot: dict | None = None
    if prev_snapshot_path.is_file():
        try:
            loaded_prev = json.loads(prev_snapshot_path.read_text(encoding="utf-8"))
            if isinstance(loaded_prev, dict):
                prev_snapshot = loaded_prev
        except (OSError, json.JSONDecodeError):
            prev_snapshot = None

    editorial_state_path = snapshots_dir / "editorial_state.json"
    prev_editorial_state = _load_editorial_state(editorial_state_path, prev_snapshot)

    prev_delta_path = snapshots_dir / "delta.json"
    prev_delta: dict | None = None
    if prev_delta_path.is_file():
        try:
            loaded_delta = json.loads(prev_delta_path.read_text(encoding="utf-8"))
            if isinstance(loaded_delta, dict):
                prev_delta = loaded_delta
        except (OSError, json.JSONDecodeError):
            prev_delta = None

    projects_cfg = [p for p in (cfg.get("projects") or []) if isinstance(p, dict)]
    default_preset = str(cfg.get("default_preset") or "generic").strip().lower()
    watches_cfg = _normalize_watches_cfg(cfg)

    needs_local_env = any(
        resolve_project_preset(p, cfg) == "antigravity-plugin" for p in projects_cfg
    ) or any(isinstance(w.get("local_cli_check"), dict) for w in watches_cfg)

    if needs_local_env:
        env_data = collect_local_antigravity_env(gemini_home=gemini_home)
    else:
        env_data = {
            "agy_path": None,
            "local_agy_version": None,
            "plugins_dir": None,
            "installed_plugins": [],
            "orphan_plugin_dirs": [],
        }

    installed_map = {
        p["name"]: p for p in env_data.get("installed_plugins") or [] if p.get("name")
    }
    for p in env_data.get("installed_plugins") or []:
        if p.get("dir") and p["dir"] not in installed_map:
            installed_map[p["dir"]] = p

    projects_data = [
        collect_project_snapshot(
            proj,
            base_dir=base_dir,
            changelogs_dir=changelogs_dir,
            installed_plugins_map=installed_map,
            dry_run=dry_run,
            concept_root=resolved_concept_root,
            default_preset=default_preset,
        )
        for proj in projects_cfg
    ]

    watches_data = _collect_watches(
        watches_cfg=watches_cfg,
        out_dir=resolved_out_dir,
        concept_root=resolved_concept_root,
        releases_override=releases_override,
        offline=offline,
        save_raw=save_raw,
        dry_run=dry_run,
        synced_at=synced_at,
    )

    artifacts_data = collect_concept_artifacts(resolved_concept_root)
    project_ids = [p["id"] for p in projects_data]
    watch_impacts = [
        str(w["impact_file"]) for w in watches_data.values() if w.get("impact_file")
    ]
    budgets_cfg = cfg.get("hot_budgets")

    full_snapshot = {
        "schema_version": SCHEMA_VERSION,
        "synced_at": synced_at,
        "public_mode": effective_public,
        "environment": env_data,
        "projects": projects_data,
        "watches": watches_data,
        "artifacts": artifacts_data,
        "hot_budgets": {},
    }
    if "antigravity" in watches_data:
        full_snapshot["antigravity"] = watches_data["antigravity"]

    mask_pairs = (
        _collect_path_replacements(
            full_snapshot,
            concept_root=resolved_concept_root,
            gemini_home=gemini_home,
        )
        if effective_public
        else None
    )

    delta, next_editorial_state = compute_delta_with_state(
        prev_snapshot,
        full_snapshot,
        resolved_concept_root,
        editorial_state=prev_editorial_state,
        ack_editorial=ack_editorial,
        public_mode=effective_public,
        replacements=mask_pairs,
    )
    pre_budgets = evaluate_hot_budgets(
        resolved_concept_root, budgets_cfg, project_ids, watch_impact_files=watch_impacts
    )
    _append_budget_alerts(delta, pre_budgets)

    if prev_snapshot is not None and not ack_editorial:
        prev_no_budgets = {k: v for k, v in prev_snapshot.items() if k != "hot_budgets"}
        curr_no_budgets = {k: v for k, v in full_snapshot.items() if k != "hot_budgets"}
        same_snapshot = _strip_volatile_json(prev_no_budgets) == _strip_volatile_json(
            curr_no_budgets
        )
        same_state = (
            prev_editorial_state is not None
            and _strip_volatile_json(prev_editorial_state)
            == _strip_volatile_json(next_editorial_state)
        )
        same_delta_core = (
            isinstance(prev_delta, dict)
            and prev_delta.get("hygiene_alerts") == delta.get("hygiene_alerts")
            and prev_delta.get("editorial_targets") == delta.get("editorial_targets")
        )
        if same_snapshot and same_state and same_delta_core:
            stable_ts = prev_snapshot.get("synced_at") or synced_at
            synced_at = stable_ts
            full_snapshot["synced_at"] = stable_ts
            for wobj in full_snapshot["watches"].values():
                wobj["synced_at"] = stable_ts
            delta["synced_at"] = stable_ts
            if prev_editorial_state and prev_editorial_state.get("acked_at"):
                next_editorial_state["acked_at"] = prev_editorial_state["acked_at"]

    if apply_docs:
        delta["auto_updated_files"] = apply_auto_doc_updates(
            resolved_concept_root,
            full_snapshot,
            delta,
            dry_run=dry_run,
            public_mode=effective_public,
            replacements=mask_pairs,
        )

    post_budgets = evaluate_hot_budgets(
        resolved_concept_root, budgets_cfg, project_ids, watch_impact_files=watch_impacts
    )
    full_snapshot["hot_budgets"] = post_budgets
    before_alerts = list(delta["hygiene_alerts"])
    _append_budget_alerts(delta, post_budgets)
    if apply_docs and not dry_run and delta["hygiene_alerts"] != before_alerts:
        extra = apply_auto_doc_updates(
            resolved_concept_root,
            full_snapshot,
            delta,
            dry_run=False,
            public_mode=effective_public,
            replacements=mask_pairs,
        )
        for item in extra:
            if item not in delta["auto_updated_files"]:
                delta["auto_updated_files"].append(item)

    delta_md = render_delta_markdown(delta, dry_run=dry_run, replacements=mask_pairs)

    if not dry_run:
        for wid, wobj in watches_data.items():
            raw_out = wobj.get("out_dir") or f"tracking/watches/{wid}"
            wdir = (resolved_concept_root / str(raw_out)).resolve()
            _write_json_if_changed(wdir / "summary.json", wobj)
        _write_json_if_changed(snapshots_dir / "ecosystem_snapshot.json", full_snapshot)
        _write_md_if_changed(
            snapshots_dir / "ecosystem_snapshot.md",
            render_ecosystem_snapshot_markdown(
                full_snapshot,
                public_mode=effective_public,
                replacements=mask_pairs,
            ),
        )
        _write_json_if_changed(snapshots_dir / "delta.json", delta)
        _write_md_if_changed(snapshots_dir / "delta.md", delta_md)
        _write_json_if_changed(editorial_state_path, next_editorial_state)

    return full_snapshot, delta


def build_parser() -> argparse.ArgumentParser:
    """Construit le parseur CLI pour `sync_tracking.py`."""
    parser = argparse.ArgumentParser(
        description="Synchronise en lecture seule les dépôts d'un atelier Gravity Architect."
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Racine de l'atelier (détectée automatiquement par défaut via ./projects.json ou sous-dossier unique)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Chemin explicite vers projects.json",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Répertoire de sortie tracking/ (défaut : <atelier>/tracking)",
    )
    parser.add_argument(
        "--concept-root",
        type=Path,
        default=None,
        help="Racine de l'atelier de conception (défaut : répertoire parent de projects.json)",
    )
    parser.add_argument(
        "--releases",
        type=int,
        default=None,
        help="Nombre de releases à extraire par veille",
    )
    parser.add_argument(
        "--offline",
        "--skip-antigravity",
        dest="offline",
        action="store_true",
        help="Ignore la récupération réseau des veilles configurées",
    )
    parser.add_argument(
        "--save-raw",
        action="store_true",
        help="Enregistre la copie brute complète des veilles dans <watch>/raw/changelog.md",
    )
    parser.add_argument(
        "--check",
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Collecte et calcule le delta sans écrire sur disque",
    )
    parser.add_argument(
        "--no-apply-docs",
        action="store_true",
        help="Désactive la mise à jour des blocs <!-- AUTO:START/END -->",
    )
    parser.add_argument(
        "--ack-editorial",
        action="store_true",
        help="Acquitte explicitement les cibles éditoriales après édition des fiches",
    )
    parser.add_argument(
        "--print-delta",
        action="store_true",
        help="Affiche le delta Markdown compact sur stdout",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Point d'entrée CLI."""
    _configure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        detected_root, config_path = resolve_workspace_root(
            config_arg=args.config,
            workspace_arg=args.workspace,
        )
        concept_root = args.concept_root if args.concept_root is not None else detected_root
        out_dir = args.out_dir if args.out_dir is not None else (concept_root / "tracking")
        snapshot, delta = run_sync(
            config_path=config_path,
            out_dir=out_dir,
            releases_override=args.releases,
            offline=args.offline,
            save_raw=args.save_raw,
            concept_root=concept_root,
            dry_run=args.dry_run,
            apply_docs=not args.no_apply_docs,
            ack_editorial=args.ack_editorial,
        )
    except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
        print(f"[erreur] Synchronisation impossible : {exc}", file=sys.stderr)
        return 1

    if args.print_delta:
        delta_masks = (
            _collect_path_replacements(snapshot, concept_root=concept_root)
            if snapshot.get("public_mode")
            else None
        )
        sys.stdout.write(
            render_delta_markdown(delta, dry_run=args.dry_run, replacements=delta_masks)
        )
    else:
        prefix = "[dry-run] " if args.dry_run else ""
        print(
            f"{prefix}Synchronisation terminée ({snapshot['synced_at']}) — "
            f"{len(snapshot['projects'])} projet(s), "
            f"veilles: {delta.get('fetch_status')}, "
            f"éditorial: {'requis' if delta['needs_editorial_update'] else 'à jour'}."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
