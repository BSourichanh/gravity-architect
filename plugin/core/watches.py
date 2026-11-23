"""Veilles technologiques (Google Antigravity, changelogs Markdown, --offline) et inspection CLI locale."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import sys
from typing import Callable
import urllib.error
import urllib.request

from core.discovery import PROJECT_ID_RE
from core.io_utils import (
    CHANGELOG_SECTION_RE,
    SECTION_RE,
    humanize_id,
    run_readonly_cmd,
    write_md_if_changed,
    write_utf8,
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

ANTIGRAVITY_CHANGELOG_URL = "https://antigravity.google/docs/changelog.md"
ANTIGRAVITY_IMPACT_BUDGET = 6000
ANTIGRAVITY_WATCH_SURFACES = [
    {"heading": "Antigravity App", "slug": "app"},
    {"heading": "Antigravity CLI", "slug": "cli"},
    {"heading": "IDE Extensions", "slug": "ide-extensions"},
    {"heading": "Antigravity SDK", "slug": "sdk"},
    {"heading": "Antigravity IDE", "slug": "ide"},
]

SEPARATOR_RE = re.compile(r"^\s*---\s*$", re.MULTILINE)
VERSION_HEADING_RE = re.compile(r"^###\s+\[(v[0-9][^\]]*)\]", re.MULTILINE)
SUB_HEADING_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
MD_BULLET_RE = re.compile(r"^\s*[\*\-]\s+(.+?)\s*$", re.MULTILINE)


def parse_watch_urls(raw_urls: list[str]) -> list[tuple[str, str]]:
    """Parse et valide une liste d'arguments `--watch-url id=url`."""
    parsed: list[tuple[str, str]] = []
    seen_ids: set[str] = set()
    for raw in raw_urls:
        if "=" not in raw:
            raise ValueError(f"Format --watch-url invalide ({raw!r}) : attendu id=url.")
        wid_raw, url_raw = raw.split("=", 1)
        wid = wid_raw.strip().lower()
        url = url_raw.strip()
        if not PROJECT_ID_RE.match(wid):
            raise ValueError(f"Identifiant veille invalide ({wid!r}) : uniquement [a-z0-9_-].")
        if not url.startswith(("https://", "http://")) or any(ch.isspace() for ch in url):
            raise ValueError(f"URL veille invalide ({url!r}) : http(s):// attendu.")
        if wid in seen_ids:
            raise ValueError(f"Veille dupliquée dans --watch-url : {wid}")
        seen_ids.add(wid)
        parsed.append((wid, url))
    return parsed


def build_antigravity_watch() -> dict:
    """Construit la configuration de veille officielle Google Antigravity."""
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


def split_top_sections(markdown_text: str) -> dict[str, str]:
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
    sections = split_top_sections(markdown_text)
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
                title_match = SUB_HEADING_RE.search(block[version_match.end() :])
                if title_match:
                    release_titles[ver] = title_match.group(1).strip()
                release_digests[ver] = extract_relevant_antigravity_bullets(block, kw_list)
            elif len(versions) < releases_per_surface:
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
    req = urllib.request.Request(url, headers={"User-Agent": "gravity-architect-sync/5.0"})
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
    lines.append(body if body else "*Aucune release extraite pour cette surface.*")
    lines.append("")
    return "\n".join(lines)


def normalize_watches_cfg(cfg: dict) -> list[dict]:
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
                "url": str(ag_cfg.get("changelog_url", ANTIGRAVITY_CHANGELOG_URL)),
                "out_dir": "tracking/antigravity",
                "impact_file": "tracking/antigravity/IMPACT.md",
                "releases_per_surface": int(ag_cfg.get("releases_per_surface", 5)),
                "relevance_keywords": list(ag_cfg.get("relevance_keywords") or DEFAULT_WATCH_KEYWORDS),
                "surfaces": list(ag_cfg.get("surfaces") or []),
                "local_cli_check": {"cmd": "agy", "surface_slug": "cli"},
            }
        ]
    return []


def collect_watches(
    watches_cfg: list[dict],
    out_dir: Path,
    concept_root: Path,
    releases_override: int | None,
    offline: bool,
    save_raw: bool,
    dry_run: bool,
    synced_at: str,
    fetch_fn: Callable[[str], str] | None = None,
) -> dict[str, dict]:
    """Collecte les veilles configurées sans effet de bord si offline ou dry-run."""
    fetcher = fetch_fn or fetch_antigravity_changelog
    results: dict[str, dict] = {}
    for wcfg in watches_cfg:
        wid = str(wcfg["id"])
        wname = str(wcfg.get("name") or wid)
        wtype = str(wcfg.get("type") or "markdown-changelog")
        url = str(wcfg.get("url") or "")
        raw_out = wcfg.get("out_dir")
        watch_dir = (concept_root / str(raw_out)).resolve() if raw_out else (out_dir / "watches" / wid).resolve()
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

        limit = releases_override if releases_override is not None else int(wcfg.get("releases_per_surface", 5))
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
                raw_md = fetcher(url)
                if save_raw and not dry_run:
                    raw_dir = watch_dir / "raw"
                    raw_dir.mkdir(parents=True, exist_ok=True)
                    write_utf8(raw_dir / "changelog.md", raw_md.replace("\r\n", "\n"))

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
                    if not dry_run:
                        write_md_if_changed(releases_dir / f"{slug}.md", md_content)
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


def collect_local_antigravity_env(
    gemini_home: Path | None = None,
    cmd_runner: Callable[..., tuple[int, str, str]] | None = None,
) -> dict:
    """Inspecte en lecture seule `agy`, `config.json` et les plugins installés."""
    runner = cmd_runner or run_readonly_cmd
    agy_bin = shutil.which("agy")
    agy_version = None
    if agy_bin:
        rc, out, err = runner([agy_bin, "--version"], timeout=5)
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
            cfg_entry = plugin_cfg_map.get(plugin_info["name"]) or plugin_cfg_map.get(entry.name)
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


def make_watch_url_entry(wid: str, url: str) -> dict:
    """Construit l'entrée `watches[]` pour un changelog Markdown générique."""
    return {
        "id": wid,
        "name": humanize_id(wid),
        "type": "markdown-changelog",
        "url": url,
        "out_dir": f"tracking/{wid}",
        "releases_per_surface": 5,
        "relevance_keywords": list(DEFAULT_WATCH_KEYWORDS),
    }
