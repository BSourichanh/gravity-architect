"""Utilitaires partagés d'E/S UTF-8/LF atomiques, chemins, mode public et résolution d'atelier."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

SCHEMA_VERSION = 5
ATELIERS_REGISTRY_FILENAME = "ateliers.json"
MAX_REGISTERED_ATELIERS = 20

DEFAULT_HOT_BUDGETS = {
    "AGENTS.md": 2500, "ECOSYSTEM.md": 6000,
    "tracking/antigravity/IMPACT.md": 6000, "project_card_max_bytes": 3500,
}
AUTO_DISCOVER_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}

SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
CHANGELOG_SECTION_RE = re.compile(r"^##[ \t]+\[([^\]]+)\](?:[ \t]*-[ \t]*([^\s(]+))?[^\n]*$", re.MULTILINE)
SYNC_LINE_RE = re.compile(r"^- \*\*Synchronisé le :\*\*.*$", re.MULTILINE)
DATE_LINE_RE = re.compile(r"^- \*\*Date :\*\*.*$", re.MULTILINE)
AUTO_BLOCK_RE = re.compile(r"<!-- AUTO:START:[^>]+ -->.*?<!-- AUTO:END:[^>]+ -->", re.DOTALL)
MACHINE_ABS_PATH_RE = re.compile(
    r"(?:(?<![A-Za-z0-9_])[A-Za-z]:[\\/][^\s`\"'<>|)\]]+|\\\\[A-Za-z0-9_.-]+[\\/][^\s`\"'<>|)\]]+"
    r"|(?<![:\w/])/(?:Users|home|var|tmp|opt|etc|mnt|Volumes|private|root)/[^\s`\"'<>|)\]]+)"
)
SEMVER_RE = re.compile(r"\bv?(\d+(?:\.\d+)+)")


def parse_semver_tuple(raw: str) -> tuple[int, ...] | None:
    """Extrait un tuple SemVer numérique (au moins MAJOR.MINOR) depuis une chaîne."""
    if not isinstance(raw, str):
        return None
    match = SEMVER_RE.search(raw.strip())
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def compare_cli_versions(local_raw: str, latest_raw: str) -> str:
    """Compare une version CLI locale à la dernière connue ('behind'|'ahead'|'equal')."""
    local_tuple, latest_tuple = parse_semver_tuple(local_raw), parse_semver_tuple(latest_raw)
    if local_tuple is not None and latest_tuple is not None:
        return "behind" if local_tuple < latest_tuple else ("ahead" if local_tuple > latest_tuple else "equal")
    return "behind" if local_raw.strip().lstrip("v") != latest_raw.strip().lstrip("v") else "equal"


def configure_utf8_stdio() -> None:
    """Force stdout/stderr en UTF-8 pour éviter les erreurs cp1252 sous Windows."""
    for stream in (sys.stdout, sys.stderr):
        reconf = getattr(stream, "reconfigure", None)
        if callable(reconf):
            try:
                reconf(encoding="utf-8", errors="replace")
            except Exception:
                pass


def write_utf8(path: Path, text: str) -> None:
    """Écrit un fichier texte de façon atomique en UTF-8 sans BOM avec fins de ligne LF."""
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = text.replace("\r\n", "\n")
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as fh:
            tmp_path = Path(fh.name)
            fh.write(normalized)
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def deploy_file(dst: Path, content: str, *, force: bool) -> str:
    """Écrit ou préserve un fichier cible et retourne son statut (`created`, `updated` ou `skipped`)."""
    if dst.exists():
        if not force:
            return "skipped"
        write_utf8(dst, content)
        return "updated"
    write_utf8(dst, content)
    return "created"


def read_json_safe(path: Path) -> dict | None:
    """Lit un objet JSON en toute sécurité (UTF-8 avec/sans BOM), ou retourne None."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def load_config(config_path: Path) -> dict:
    """Charge la configuration JSON d'un atelier Gravity Architect."""
    text = config_path.read_text(encoding="utf-8-sig")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"Configuration invalide dans {config_path}: objet JSON attendu.")
    return data


def strip_volatile_json(obj):
    """Retourne une copie récursive sans les horodatages volatils (`synced_at`, `acked_at`)."""
    if isinstance(obj, dict):
        return {k: strip_volatile_json(v) for k, v in obj.items() if k not in ("synced_at", "acked_at")}
    if isinstance(obj, list):
        return [strip_volatile_json(item) for item in obj]
    return obj


def write_json_if_changed(path: Path, payload: dict) -> bool:
    """Écrit un JSON sur disque uniquement si sa charge utile hors horodatages diffère."""
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if strip_volatile_json(existing) == strip_volatile_json(payload):
                return False
        except (OSError, json.JSONDecodeError):
            pass
    write_utf8(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return True


def strip_volatile_md(md_text: str) -> str:
    """Supprime les lignes de date/synchro volatiles pour éviter le churn Markdown."""
    cleaned = SYNC_LINE_RE.sub("", md_text)
    cleaned = DATE_LINE_RE.sub("", cleaned)
    return cleaned.replace("\r\n", "\n").strip()


def strip_sync_line(md_text: str) -> str:
    """Alias conservé pour compatibilité : normalise le Markdown hors horodatages."""
    return strip_volatile_md(md_text)


def write_md_if_changed(path: Path, text: str) -> bool:
    """Écrit un Markdown sur disque uniquement si son contenu hors horodatages diffère."""
    normalized = text.replace("\r\n", "\n")
    if path.is_file():
        existing = path.read_text(encoding="utf-8", errors="replace")
        if strip_volatile_md(existing) == strip_volatile_md(normalized):
            return False
    write_utf8(path, normalized)
    return True


def editorial_prose_sha256(path: Path) -> str | None:
    """Calcule le SHA-256 de la prose éditoriale d'une fiche (blocs AUTO exclus)."""
    if not path.is_file():
        return None
    raw = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    without_auto = AUTO_BLOCK_RE.sub("", raw)
    normalized = "\n".join(line.rstrip() for line in without_auto.splitlines()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def humanize_id(pid: str) -> str:
    """Transforme un identifiant kebab/snake en libellé lisible."""
    return pid.replace("-", " ").replace("_", " ").strip().title()


def truncate_text(text: str, max_len: int = 160) -> str:
    """Compacte les espaces et tronque proprement à la frontière de mot."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_len:
        return collapsed
    cut = collapsed[: max_len - 1]
    last_space = cut.rfind(" ")
    if last_space >= max_len // 2:
        cut = cut[:last_space]
    return cut.rstrip(" ,;:-") + "…"


def _raw_architect_home(
    architect_home: Path | None = None, *, env: dict[str, str] | None = None, home_dir: Path | None = None
) -> Path:
    if architect_home is not None:
        return architect_home.expanduser()
    env_map = env if env is not None else os.environ
    for key, suffix in (("GRAVITY_ARCHITECT_HOME", None), ("GRAVITY_HOME", "architect")):
        val = str(env_map.get(key) or "").strip()
        if val:
            base = Path(val).expanduser()
            return (base / suffix) if suffix else base
    base_home = (home_dir if home_dir is not None else Path.home()).expanduser()
    return base_home / ".gemini" / "gravity" / "architect"


def default_architect_home(*, env: dict[str, str] | None = None, home_dir: Path | None = None) -> Path:
    """Résout le dossier centralisé Architect (`GRAVITY_ARCHITECT_HOME` > `GRAVITY_HOME/architect` > `~/.gemini/gravity/architect`)."""
    return _raw_architect_home(env=env, home_dir=home_dir).resolve()


def resolve_ateliers_registry_path(
    architect_home: Path | None = None, env: dict[str, str] | None = None, home_dir: Path | None = None
) -> Path:
    """Résout le chemin du registre centralisé `<architect_home>/ateliers.json`."""
    base = architect_home.expanduser().resolve() if architect_home is not None else default_architect_home(env=env, home_dir=home_dir)
    return base / ATELIERS_REGISTRY_FILENAME


def _is_valid_atelier_dir(workspace_dir: Path) -> bool:
    """Vérifie qu'un dossier non symlink contient `projects.json` et `ECOSYSTEM.md` (non symlinks)."""
    try:
        if workspace_dir.is_symlink() or not workspace_dir.is_dir():
            return False
        cfg_file, eco_file = workspace_dir / "projects.json", workspace_dir / "ECOSYSTEM.md"
        return not cfg_file.is_symlink() and cfg_file.is_file() and not eco_file.is_symlink() and eco_file.is_file()
    except OSError:
        return False


def _merge_existing_ateliers(registry_path: Path, seen_keys: set[str], limit: int) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    raw_ateliers = (read_json_safe(registry_path) or {}).get("ateliers")
    if not isinstance(raw_ateliers, list):
        return merged
    for item in raw_ateliers:
        if len(merged) >= limit:
            break
        raw_p = str(item.get("workspace_path") or "").strip() if isinstance(item, dict) else ""
        if not raw_p or not _is_valid_atelier_dir(cand_raw := Path(raw_p).expanduser()):
            continue
        cand_canonical = cand_raw.resolve()
        if (cand_key := os.path.normcase(str(cand_canonical))) in seen_keys:
            continue
        seen_keys.add(cand_key)
        merged.append({
            "workspace_path": str(cand_canonical),
            "workspace_name": str(item.get("workspace_name") or "").strip(),
            "updated_at": str(item.get("updated_at") or "").strip(),
        })
    return merged


def register_atelier(
    workspace_root: Path, *, workspace_name: str = "", architect_home: Path | None = None,
    env: dict[str, str] | None = None, home_dir: Path | None = None,
) -> bool:
    """Enregistre l'atelier courant (MRU, max 20) dans `<architect_home>/ateliers.json` en best-effort."""
    env_map = env if env is not None else os.environ
    if str(env_map.get("GRAVITY_ARCHITECT_SKIP_REGISTRY") or "").strip() == "1":
        return False
    try:
        ws_raw = workspace_root.expanduser()
        if not _is_valid_atelier_dir(ws_raw):
            return False
        ws_canonical = ws_raw.resolve()
        raw_home = _raw_architect_home(architect_home, env=env_map, home_dir=home_dir)
        registry_path = resolve_ateliers_registry_path(architect_home, env=env_map, home_dir=home_dir)
        if any(p.is_symlink() for p in (raw_home / ATELIERS_REGISTRY_FILENAME, raw_home, raw_home.parent)):
            return False
        if registry_path.is_symlink() or (registry_path.exists() and not registry_path.is_file()):
            return False
        resolved_name = str(workspace_name or "").strip() or str((read_json_safe(ws_canonical / "projects.json") or {}).get("workspace_name") or "").strip()
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        entries = [{"workspace_path": str(ws_canonical), "workspace_name": resolved_name, "updated_at": now_utc}]
        entries.extend(_merge_existing_ateliers(registry_path, {os.path.normcase(str(ws_canonical))}, MAX_REGISTERED_ATELIERS - 1))
        write_utf8(registry_path, json.dumps({"schema_version": 1, "ateliers": entries[:MAX_REGISTERED_ATELIERS]}, indent=2, ensure_ascii=False) + "\n")
        return True
    except (OSError, ValueError, TypeError):
        return False


def resolve_public_mode(cfg: dict | None) -> bool:
    """Retourne True si `privacy.public_mode` ou `public_mode` est activé."""
    if not isinstance(cfg, dict):
        return False
    privacy = cfg.get("privacy")
    if isinstance(privacy, dict) and "public_mode" in privacy:
        return bool(privacy.get("public_mode"))
    return bool(cfg.get("public_mode")) if "public_mode" in cfg else False


def is_machine_absolute_path(raw: str) -> bool:
    """Retourne True si `raw` est un chemin absolu machine (Windows, UNC ou POSIX)."""
    s = raw.strip()
    if not s:
        return False
    if Path(s).is_absolute() or s.startswith("/") or s.startswith("\\"):
        return True
    return bool(re.match(r"^[A-Za-z]:[\\/]", s))


def tracked_project_keys(snapshot: dict) -> set[str]:
    """Retourne l'ensemble des identifiants (`id`, `plugin_name`) des projets suivis."""
    keys: set[str] = set()
    for proj in snapshot.get("projects") or []:
        if not isinstance(proj, dict):
            continue
        for val in (proj.get("id"), proj.get("plugin_name"), (proj.get("stable") or {}).get("plugin_name")):
            if cleaned := str(val or "").strip():
                keys.add(cleaned)
    return keys


def visible_installed_plugins(snapshot: dict, public_mode: bool) -> list[dict]:
    """Filtre `installed_plugins` aux seuls plugins suivis lorsque `public_mode` est actif."""
    installed = [p for p in ((snapshot.get("environment") or {}).get("installed_plugins") or []) if isinstance(p, dict)]
    if not public_mode:
        return installed
    tracked = tracked_project_keys(snapshot)
    return [p for p in installed if p.get("name") in tracked or p.get("dir") in tracked]


def visible_orphan_plugin_dirs(snapshot: dict, public_mode: bool) -> list[str]:
    """Exclut les dossiers tiers hors projets suivis lorsque `public_mode` est actif."""
    orphans = list((snapshot.get("environment") or {}).get("orphan_plugin_dirs") or [])
    if not public_mode:
        return orphans
    tracked = tracked_project_keys(snapshot)
    return [d for d in orphans if d in tracked]


def format_project_display_path(proj: dict, *, public_mode: bool) -> str:
    """Formate le chemin affiché d'un projet en masquant tout chemin absolu machine en mode public."""
    pid = str(proj.get("id") or "project")
    raw_display = str(proj.get("display_path") or f"../{pid}").strip()
    if not public_mode:
        return raw_display
    if not is_machine_absolute_path(raw_display) and not MACHINE_ABS_PATH_RE.search(raw_display):
        return raw_display.replace("\\", "/")
    return f"<repo:{pid}>"


def collect_path_replacements(
    snapshot: dict | None = None, *, concept_root: Path | None = None, gemini_home: Path | None = None,
) -> list[tuple[str, str]]:
    """Construit la table ordonnée `(chemin_absolu, masque)` pour la sanitisation Markdown."""
    pairs: list[tuple[str, str]] = []

    def _add(raw_path: str | Path | None, token: str) -> None:
        s = str(raw_path or "").strip()
        if not s or not is_machine_absolute_path(s):
            return
        variants = {s, s.rstrip("/\\"), s.replace("\\", "/"), s.replace("/", "\\")}
        try:
            res = str(Path(s).resolve())
            variants.update({res, res.replace("\\", "/"), res.replace("/", "\\")})
        except OSError:
            pass
        pairs.extend((v, token) for v in variants if len(v) >= 4)

    if isinstance(snapshot, dict):
        env = snapshot.get("environment") or {}
        for p in env.get("installed_plugins") or []:
            if isinstance(p, dict):
                _add(p.get("install_path"), f"<install:{p.get('name') or p.get('dir') or 'plugin'}>")
        _add(env.get("plugins_dir"), "<plugins-dir>")
        _add(env.get("agy_path"), "<agy>")
        for proj in snapshot.get("projects") or []:
            if isinstance(proj, dict):
                pid = str(proj.get("id") or "project")
                _add(proj.get("path"), f"<repo:{pid}>")
                if is_machine_absolute_path(disp := str(proj.get("display_path") or "")):
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
        dedup.setdefault(raw, tok)
    return list(dedup.items())


def sanitize_markdown_paths(text: str, *, replacements: list[tuple[str, str]] | None = None) -> str:
    """Masque les chemins absolus machine connus ou génériques dans un texte Markdown."""
    cleaned = text
    for raw_path, token in replacements or []:
        if raw_path in cleaned:
            cleaned = cleaned.replace(raw_path, token)
    return MACHINE_ABS_PATH_RE.sub("<path>", cleaned)


def resolve_workspace_root(
    config_arg: Path | None = None, workspace_arg: Path | None = None,
    cwd: Path | None = None, env: dict | None = None, home_dir: Path | None = None,
) -> tuple[Path, Path]:
    """Résout `(concept_root, config_path)` par paramètres, env, auto-détection ou accueil centralisé."""
    if config_arg is not None:
        cfg_path = config_arg.expanduser().resolve()
        return cfg_path.parent, cfg_path
    if workspace_arg is not None:
        ws = workspace_arg.expanduser().resolve()
        return ws, ws / "projects.json"

    env_map = env if env is not None else os.environ
    if env_ws := str(env_map.get("GRAVITY_ARCHITECT_WORKSPACE") or "").strip():
        ws = Path(env_ws).expanduser().resolve()
        return ws, ws / "projects.json"

    base_cwd = (cwd if cwd is not None else Path.cwd()).resolve()
    if (direct_cfg := base_cwd / "projects.json").is_file():
        return base_cwd, direct_cfg

    candidates = [
        entry for entry in sorted(base_cwd.iterdir(), key=lambda p: p.name.lower())
        if entry.is_dir() and not entry.name.startswith(".") and entry.name not in AUTO_DISCOVER_SKIP_DIRS
        and (entry / "projects.json").is_file() and (entry / "ECOSYSTEM.md").is_file()
    ]
    if len(candidates) == 1:
        ws = candidates[0].resolve()
        return ws, ws / "projects.json"
    if len(candidates) > 1:
        raise ValueError(f"Plusieurs ateliers détectés dans {base_cwd} ({', '.join(c.name for c in candidates)}) ; précisez --workspace.")

    arch_home = default_architect_home(env=env_map, home_dir=home_dir)
    if (arch_cfg := arch_home / "projects.json").is_file():
        return arch_home, arch_cfg

    raise FileNotFoundError(
        f"Aucun fichier projects.json trouvé dans {base_cwd}, un sous-dossier atelier, "
        f"ni {arch_home}. Utilisez --workspace <dir> ou init_workspace.py."
    )


def snapshot_watches_map(snapshot: dict | None) -> dict[str, dict]:
    """Retourne la table unifiée des veilles d'un snapshot (v5 ou v3/v4)."""
    if not isinstance(snapshot, dict):
        return {}
    if isinstance(snapshot.get("watches"), dict):
        return snapshot["watches"]
    if isinstance(snapshot.get("antigravity"), dict):
        return {"antigravity": snapshot["antigravity"]}
    return {}


def has_install_audit(snapshot: dict) -> bool:
    """Indique si au moins un projet du snapshot utilise le preset `antigravity-plugin`."""
    return any(p.get("preset") == "antigravity-plugin" for p in snapshot.get("projects") or [])


def run_readonly_cmd(args: list[str], cwd: Path | None = None, timeout: int = 15) -> tuple[int, str, str]:
    """Exécute une commande sans shell=True et retourne (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            args, cwd=str(cwd) if cwd is not None else None, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except OSError as exc:
        return 127, "", str(exc)
    except subprocess.TimeoutExpired as exc:
        return 124, "", f"Délai expiré après {timeout}s ({exc})"


MD_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
STATUS_LINE_RE = re.compile(r"^\s*-\s*\*\*(?:Date\s*/\s*)?Statut\s*:\*\*\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
TARGET_LINE_RE = re.compile(r"^\s*-\s*\*\*(?:Dépôt cible|Projets? impactés?)\s*:\*\*\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
WAVE_LINE_RE = re.compile(r"^\s*-\s*\*\*Vague\s*:\*\*\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
DEPS_LINE_RE = re.compile(r"^\s*-\s*\*\*D[ée]pendances\s*:\*\*\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
BRANCH_LINE_RE = re.compile(r"^\s*-\s*\*\*Branche\s+attendue\s*:\*\*\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
PROFILE_LINE_RE = re.compile(r"^\s*-\s*\*\*Profil\s+workflow\s*:\*\*\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
FILES_LINE_RE = re.compile(r"^\s*-\s*\*\*Fichiers\s+cibles\s*:\*\*\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
ANCHORS_LINE_RE = re.compile(r"^\s*-\s*\*\*Ancres\s*:\*\*\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
ARTIFACT_FILE_SECTIONS = frozenset({"ancres exactes", "ancres", "fichiers cibles", "fichiers probables"})
ANCHOR_TAIL_RE = re.compile(r"(?:\s*::.*|\s*\(?~L\d+(?:-\s*L?\d+)?\)?.*)$")
HYBRID_ANCHOR_RE = re.compile(r"::|~L\d+")
EMPTY_FIELD_TOKENS = frozenset({"", "aucun", "aucune", "none", "n/a", "-", "—"})
BARE_ROOT_FILES = frozenset({"Dockerfile", "Makefile", "LICENSE", "README"})


def clean_md_field(raw: str) -> str:
    """Nettoie un champ Markdown simple en conservant la valeur utile."""
    text = re.sub(r"\*?\([^)]*\)\*?", "", raw).strip()
    backticked = re.findall(r"`([^`]+)`", text)
    if backticked:
        for cand in backticked:
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", cand):
                return cand.strip()
    return text.strip("`* ").strip()


def normalize_target_file(raw: str) -> str:
    """Normalise un chemin cible en supprimant ancres `::...` / `~L...` et préfixe `./`."""
    s = raw.strip().strip("`").strip()
    if m := re.match(r"^\[([^\]]+)\]\([^)]+\)(.*)$", s):
        s = m.group(1) + m.group(2)
    s = ANCHOR_TAIL_RE.sub("", s).strip().replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    return s.rstrip("/")


def _looks_like_file_path(head: str) -> bool:
    if not head or head.lower() in EMPTY_FIELD_TOKENS:
        return False
    return "/" in head or "\\" in head or "." in head or head in BARE_ROOT_FILES


def _clean_bullet_item(raw: str) -> str:
    s = re.split(r"\s+[—–]\s+|\s+--\s+", raw.strip(), maxsplit=1)[0].strip()
    if m := re.match(r"^\[([^\]]+)\]\([^)]+\)(.*)$", s):
        s = m.group(1) + m.group(2)
    s = re.sub(r"\*?\((?!~L)[^)]*\)\*?", "", s).replace("`", "").strip()
    return s.strip(",;").strip()


def _record_target_item(item: str, target_files: list[str], anchors: dict[str, list[str]]) -> str | None:
    if not item or item.lower() in EMPTY_FIELD_TOKENS:
        return None
    norm = normalize_target_file(item)
    if not _looks_like_file_path(norm):
        return None
    if norm not in target_files:
        target_files.append(norm)
    if HYBRID_ANCHOR_RE.search(item):
        bucket = anchors.setdefault(norm, [])
        if item not in bucket:
            bucket.append(item)
    return norm


def _extract_targets_and_anchors(text: str) -> tuple[list[str], dict[str, list[str]]]:
    target_files: list[str] = []
    anchors: dict[str, list[str]] = {}
    for rx in (FILES_LINE_RE, ANCHORS_LINE_RE):
        for match in rx.finditer(text):
            for part in re.split(r",(?![^(]*\))", match.group(1)):
                _record_target_item(_clean_bullet_item(part), target_files, anchors)

    section_kind: str | None = None
    current_parent: str | None = None
    for line in text.splitlines():
        if h_match := re.match(r"^#{1,2}\s+(.+?)\s*$", line):
            heading = h_match.group(1).strip().lower()
            section_kind = heading if (line.startswith("## ") and heading in ARTIFACT_FILE_SECTIONS) else None
            current_parent = None
            continue
        if section_kind is None:
            continue
        if b_match := re.match(r"^(\s*)[-*+]\s+(.+?)\s*$", line):
            indent, item = len(b_match.group(1).expandtabs(2)), _clean_bullet_item(b_match.group(2))
            if not item or item.lower() in EMPTY_FIELD_TOKENS:
                continue
            norm = normalize_target_file(item)
            if indent >= 2 and current_parent and not _looks_like_file_path(norm):
                if HYBRID_ANCHOR_RE.search(item) or section_kind in ("ancres exactes", "ancres"):
                    sep = "" if item.startswith("::") else (" " if item.startswith(("~L", "(~L")) else "::")
                    combined = f"{current_parent}{sep}{item}"
                    bucket = anchors.setdefault(current_parent, [])
                    if combined not in bucket:
                        bucket.append(combined)
            else:
                recorded = _record_target_item(item, target_files, anchors)
                if indent < 2:
                    current_parent = recorded
    return target_files, anchors


def _clean_optional_field(pattern: re.Pattern[str], text: str) -> str:
    val = clean_md_field(m.group(1)) if (m := pattern.search(text)) else ""
    return "" if val.lower() in EMPTY_FIELD_TOKENS else val


def parse_artifact_file(path: Path, concept_root: Path) -> dict:
    """Extrait les métadonnées d'une spec ou d'une task Markdown."""
    text = path.read_text(encoding="utf-8", errors="replace")
    title_match = MD_H1_RE.search(text)
    date_match = re.match(r"^(\d{4}-\d{2}-\d{2})-", path.name)
    status_match = STATUS_LINE_RE.search(text)
    target_match = TARGET_LINE_RE.search(text)
    target_project = ""
    if target_match:
        raw_target = re.sub(r"\*?\([^)]*\)\*?", "", target_match.group(1)).strip()
        target_project = raw_target.replace("`", "").strip("* ").strip()

    wave, wave_raw = None, None
    if wave_match := WAVE_LINE_RE.search(text):
        raw_w = clean_md_field(wave_match.group(1))
        if raw_w:
            if re.fullmatch(r"-?\d+", raw_w):
                wave = int(raw_w)
            else:
                wave_raw = raw_w

    dependencies: list[str] = []
    if deps_match := DEPS_LINE_RE.search(text):
        raw_deps = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", deps_match.group(1))
        raw_deps = re.sub(r"\*?\([^)]*\)\*?", "", raw_deps).strip()
        for part in re.split(r"[,;]", raw_deps):
            dep = part.strip("`* ").strip()
            if dep.lower() in EMPTY_FIELD_TOKENS:
                continue
            dep = dep[:-3] if dep.endswith(".md") else dep
            if dep and dep not in dependencies:
                dependencies.append(dep)

    expected_branch = _clean_optional_field(BRANCH_LINE_RE, text)
    workflow_profile = _clean_optional_field(PROFILE_LINE_RE, text)
    target_files, anchors = _extract_targets_and_anchors(text)
    out: dict = {
        "id": path.stem,
        "filename": path.name,
        "rel_path": path.relative_to(concept_root).as_posix(),
        "title": title_match.group(1).strip() if title_match else path.stem,
        "date": date_match.group(1) if date_match else None,
        "status": clean_md_field(status_match.group(1)) if status_match else "unknown",
        "target_project": target_project,
        "expected_branch": expected_branch,
        "wave": wave,
        "dependencies": dependencies,
        "workflow_profile": workflow_profile,
        "target_files": target_files,
        "anchors": anchors,
    }
    if wave_raw is not None:
        out["wave_raw"] = wave_raw
    return out


def scan_md_dir(directory: Path, concept_root: Path) -> list[dict]:
    """Liste les fichiers Markdown d'un répertoire en ignorant les modèles `_*.md`."""
    if not directory.is_dir():
        return []
    return [parse_artifact_file(p, concept_root) for p in sorted(directory.glob("*.md"), key=lambda x: x.name) if not p.name.startswith("_")]


def collect_concept_artifacts(concept_root: Path) -> dict:
    """Inventorie specs/, specs/archive/, tasks/ et tasks/archive/ sans les _TEMPLATE.md."""
    specs_dir, tasks_dir = concept_root / "specs", concept_root / "tasks"
    return {
        "specs": scan_md_dir(specs_dir, concept_root),
        "archived_specs": scan_md_dir(specs_dir / "archive", concept_root),
        "pending_tasks": scan_md_dir(tasks_dir, concept_root),
        "archived_tasks": scan_md_dir(tasks_dir / "archive", concept_root),
    }
