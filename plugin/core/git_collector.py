"""Collecte Git/manifestes/CHANGELOG en lecture seule (100 % stdlib)."""

from __future__ import annotations

import configparser
import hashlib
import json
from pathlib import Path
import re
from typing import Callable

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover - fallback Python 3.10
    tomllib = None

from core.discovery import (
    detect_plugin_manifest,
    detect_version_source,
    evaluate_project_compliance,
)
from core.io_utils import CHANGELOG_SECTION_RE, run_readonly_cmd, write_utf8

INSTALL_ADAPTED_FILENAMES = {"hooks.json", "mcp_config.json", "sidecar.json"}
INSTALL_IGNORED_DIRS = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache"}
INSTALL_IGNORED_SUFFIXES = (".pyc", ".pyo")


def collect_plugin_tree_hashes(root_dir: Path) -> tuple[dict[str, str], str]:
    """Indexe les empreintes SHA-256 (LF normalisé) des fichiers significatifs d'un plugin."""
    hashes: dict[str, str] = {}
    for file_path in sorted(root_dir.rglob("*"), key=lambda p: p.as_posix()):
        if not file_path.is_file():
            continue
        rel_parts = file_path.relative_to(root_dir).parts
        if any(part in INSTALL_IGNORED_DIRS for part in rel_parts[:-1]):
            continue
        if file_path.name in INSTALL_ADAPTED_FILENAMES or file_path.name.endswith(INSTALL_IGNORED_SUFFIXES):
            continue
        raw = file_path.read_bytes()
        if b"\x00" not in raw:
            raw = raw.replace(b"\r\n", b"\n")
        hashes["/".join(rel_parts)] = hashlib.sha256(raw).hexdigest()

    tree_digest = hashlib.sha256(
        "\n".join(f"{k}:{v}" for k, v in sorted(hashes.items())).encode("utf-8")
    ).hexdigest()
    return hashes, tree_digest


def compare_plugin_dirs(repo_plugin_dir: Path, installed_plugin_dir: Path) -> dict:
    """Compare le contenu d'un plugin dépôt et de sa copie installée hors adaptations OS."""
    if not repo_plugin_dir.is_dir() or not installed_plugin_dir.is_dir():
        return {"compared": False, "in_sync": False, "diff_files": [], "repo_sha256": None, "installed_sha256": None}
    repo_hashes, repo_tree = collect_plugin_tree_hashes(repo_plugin_dir)
    inst_hashes, inst_tree = collect_plugin_tree_hashes(installed_plugin_dir)
    diff_files = sorted(k for k in (set(repo_hashes) | set(inst_hashes)) if repo_hashes.get(k) != inst_hashes.get(k))
    return {
        "compared": True,
        "in_sync": len(diff_files) == 0,
        "diff_files": diff_files,
        "repo_sha256": repo_tree,
        "installed_sha256": inst_tree,
    }


def classify_porcelain_status(code: str) -> str:
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


def parse_porcelain_lines(raw_output: str) -> tuple[list[dict], dict]:
    """Parse `git status --porcelain=v1` en préservant le caractère d'index initial."""
    files: list[dict] = []
    counts = {"modified": 0, "added": 0, "deleted": 0, "untracked": 0, "other": 0, "total": 0}
    for raw_line in raw_output.splitlines():
        line = raw_line.rstrip("\r\n")
        if len(line) < 4:
            continue
        code, rel_path = line[:2], line[3:]
        category = classify_porcelain_status(code)
        counts[category] += 1
        counts["total"] += 1
        files.append({"status": code, "path": rel_path, "category": category})
    return files, counts


def is_runtime_ignored_path(rel_path: str, ignore_prefixes: list[str]) -> bool:
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
            "latest_changelog_version": None, "latest_changelog_date": None, "latest_changelog_excerpt": "",
            "latest_released_changelog_version": None, "latest_released_changelog_date": None,
            "has_unreleased": False, "unreleased_has_content": False,
        }

    has_unreleased, unreleased_has_content, released_idx = False, False, None
    for idx, match in enumerate(matches):
        ver = match.group(1).strip()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[match.end() : end].strip()
        if ver.lower() == "unreleased":
            if not has_unreleased:
                has_unreleased, unreleased_has_content = True, bool(body)
        elif released_idx is None:
            released_idx = idx

    chosen_idx = (
        released_idx
        if matches[0].group(1).strip().lower() == "unreleased" and not unreleased_has_content and released_idx is not None
        else 0
    )
    chosen = matches[chosen_idx]
    chosen_end = matches[chosen_idx + 1].start() if chosen_idx + 1 < len(matches) else len(text)
    raw_lines = [line.rstrip() for line in text[chosen.start() : chosen_end].strip().splitlines()]
    if len(raw_lines) > max_lines:
        raw_lines = raw_lines[:max_lines] + ["... (extrait tronqué)"]

    rel_match = matches[released_idx] if released_idx is not None else None
    return {
        "latest_changelog_version": chosen.group(1).strip(),
        "latest_changelog_date": chosen.group(2).strip() if chosen.group(2) else None,
        "latest_changelog_excerpt": "\n".join(raw_lines),
        "latest_released_changelog_version": rel_match.group(1).strip() if rel_match else None,
        "latest_released_changelog_date": rel_match.group(2).strip() if (rel_match and rel_match.group(2)) else None,
        "has_unreleased": has_unreleased,
        "unreleased_has_content": unreleased_has_content,
    }


def extract_toml_section_value(text: str, section_name: str, key: str) -> str | None:
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


def _load_toml_dict(text: str) -> dict | None:
    if tomllib is None:
        return None
    try:
        data = tomllib.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def parse_version_from_text(
    rel_path: str,
    text: str,
    version_json_path: str | None = None,
) -> dict:
    """Extrait `version`, `name` et `display_name` depuis divers formats standards de manifestes."""
    name = Path(rel_path).name.lower()
    result: dict[str, str | None] = {"version": None, "name": None, "display_name": None}

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
            cur: object = data
            for part in version_json_path.split("."):
                cur = cur.get(part) if isinstance(cur, dict) and part in cur else None
            if isinstance(cur, str) and cur.strip():
                result["version"] = cur.strip()
        elif isinstance(data.get("version"), str) and data["version"].strip():
            result["version"] = data["version"].strip()
        return result

    if name in ("pyproject.toml", "cargo.toml"):
        data = _load_toml_dict(text)
        if data is not None:
            if name == "pyproject.toml":
                proj = data.get("project") if isinstance(data.get("project"), dict) else {}
                poetry = ((data.get("tool") or {}).get("poetry")) if isinstance(data.get("tool"), dict) else {}
                ver = proj.get("version") or (poetry.get("version") if isinstance(poetry, dict) else None)
                pkg_name = proj.get("name") or (poetry.get("name") if isinstance(poetry, dict) else None)
            else:
                pkg = data.get("package") if isinstance(data.get("package"), dict) else {}
                ver, pkg_name = pkg.get("version"), pkg.get("name")
            result["version"] = str(ver).strip() if ver else None
            result["name"] = str(pkg_name).strip() if pkg_name else None
            return result
        sections = ("project", "tool.poetry") if name == "pyproject.toml" else ("package",)
        for field in ("version", "name"):
            for sec in sections:
                val = extract_toml_section_value(text, sec, field)
                if val:
                    result[field] = val
                    break
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

    for line in text.splitlines():
        cleaned = line.strip()
        if cleaned and not cleaned.startswith("#"):
            result["version"] = cleaned
            break
    return result


def git_branch_short_rev(
    repo_dir: Path, branch_name: str, cmd_runner: Callable[..., tuple[int, str, str]] = run_readonly_cmd
) -> str | None:
    """Retourne le hash court d'une branche locale si elle existe."""
    if not branch_name:
        return None
    rc, out, _ = cmd_runner(["git", "-C", str(repo_dir), "rev-parse", "--verify", "--short", branch_name])
    return out.strip() if rc == 0 and out.strip() else None


def git_show_text(
    repo_dir: Path, ref: str, rel_path: str, cmd_runner: Callable[..., tuple[int, str, str]] = run_readonly_cmd
) -> str | None:
    """Lit un fichier suivi depuis une révision Git spécifique en lecture seule."""
    if not ref or not rel_path:
        return None
    rc, out, _ = cmd_runner(["git", "-C", str(repo_dir), "show", f"{ref}:{Path(rel_path).as_posix()}"])
    return out if rc == 0 else None


def git_is_ancestor(
    repo_dir: Path, ancestor_ref: str, descendant_ref: str, cmd_runner: Callable[..., tuple[int, str, str]] = run_readonly_cmd
) -> bool:
    """Retourne True si `ancestor_ref` est contenu dans l'historique de `descendant_ref`."""
    if not ancestor_ref or not descendant_ref:
        return False
    rc, _, _ = cmd_runner(["git", "-C", str(repo_dir), "merge-base", "--is-ancestor", ancestor_ref, descendant_ref])
    return rc == 0


def git_commits_ahead(
    repo_dir: Path,
    base_ref: str,
    head_ref: str,
    *,
    no_merges: bool = False,
    cmd_runner: Callable[..., tuple[int, str, str]] = run_readonly_cmd,
) -> int:
    """Compte les commits présents dans `head_ref` mais absents de `base_ref`."""
    if not base_ref or not head_ref:
        return 0
    cmd = ["git", "-C", str(repo_dir), "rev-list", "--count"]
    if no_merges:
        cmd.append("--no-merges")
    cmd.append(f"{base_ref}..{head_ref}")
    rc, out, _ = cmd_runner(cmd)
    return int(out.strip()) if rc == 0 and out.strip().isdigit() else 0


def read_version_from_ref(
    repo_dir: Path,
    ref: str,
    version_rel: str | None,
    version_json_path: str | None = None,
    cmd_runner: Callable[..., tuple[int, str, str]] = run_readonly_cmd,
) -> str | None:
    """Extrait la version d'un fichier manifeste depuis une révision Git donnée."""
    if not version_rel or not ref:
        return None
    raw = git_show_text(repo_dir, ref, version_rel, cmd_runner=cmd_runner)
    if raw is None:
        return None
    return parse_version_from_text(version_rel, raw, version_json_path=version_json_path).get("version")


def _init_project_snapshot(
    project_cfg: dict,
    repo_dir: Path,
    preset: str,
    main_branch: str,
    dev_branch: str,
) -> dict:
    project_id = str(project_cfg["id"])
    return {
        "id": project_id, "name": project_cfg.get("name", project_id),
        "plugin_name": project_cfg.get("plugin_name"), "role": project_cfg.get("role", ""),
        "preset": preset, "display_path": str(project_cfg["path"]),
        "main_branch": main_branch, "default_dev_branch": dev_branch,
        "path": str(repo_dir), "exists": repo_dir.is_dir(), "is_git_repo": False,
        "stable": {
            "plugin_name": None, "display_name": None, "version": None, "version_source": None,
            "plugin_version": None, "installed_version": None, "installed_enabled": None,
            "install_drift": False, "install_content_compared": False,
            "install_content_drift": False, "install_content_diff_files": [],
            "latest_tag": None, "tags": [], "recent_commits": [],
            "has_changelog": False, "changelog_archive": None, "changelog_sha256": None,
            "latest_changelog_version": None, "latest_changelog_date": None,
            "latest_changelog_excerpt": "", "latest_released_changelog_version": None,
            "latest_released_changelog_date": None, "has_unreleased": False,
            "unreleased_has_content": False, "has_agents_md": False,
            "agents_md_sha256": None, "agents_md_lines": [],
            "compliance": {"ok": False, "issues": ["dépôt introuvable"]},
            "branches": {
                "main_branch": main_branch, "dev_branch": dev_branch, "main_head": None, "dev_head": None,
                "main_tag": None, "main_latest_tag": None, "latest_tag_on_main": True,
                "commits_since_latest_tag": 0, "main_plugin_version": None, "dev_plugin_version": None,
                "main_ahead_of_dev": 0, "dev_ahead_of_main": 0, "branch_drift": False,
            },
        },
        "wip": {
            "branch": None, "head": None, "is_dirty": False, "code_wip_count": 0, "runtime_only_wip": False,
            "counts": {"modified": 0, "added": 0, "deleted": 0, "untracked": 0, "other": 0, "total": 0},
            "files": [],
        },
    }


def _collect_git_metadata(
    snapshot: dict,
    repo_dir: Path,
    main_branch: str,
    dev_branch: str,
    version_rel: str | None,
    version_json_path: str | None,
    ignore_paths: list[str],
    runner: Callable[..., tuple[int, str, str]],
) -> None:
    rc, inside, _ = runner(["git", "-C", str(repo_dir), "rev-parse", "--is-inside-work-tree"])
    if rc != 0 or inside.strip().lower() != "true":
        return
    snapshot["is_git_repo"] = True
    stable = snapshot["stable"]

    rc, tags_out, _ = runner(["git", "-C", str(repo_dir), "tag", "--sort=-v:refname"])
    if rc == 0:
        tags = [t.strip() for t in tags_out.splitlines() if t.strip()][:10]
        stable["tags"] = tags
        stable["latest_tag"] = tags[0] if tags else None

    dev_head = git_branch_short_rev(repo_dir, dev_branch, cmd_runner=runner)
    main_head = git_branch_short_rev(repo_dir, main_branch, cmd_runner=runner)

    log_args = ["git", "-C", str(repo_dir), "log"] + ([dev_branch] if dev_head else []) + ["-n", "10", "--format=%h%x1f%cs%x1f%D%x1f%s"]
    rc, log_out, _ = runner(log_args)
    if rc == 0:
        stable["recent_commits"] = [
            {"hash": p[0], "date": p[1], "refs": p[2], "subject": p[3]}
            for row in log_out.splitlines()
            if len((p := row.split("\x1f"))) == 4
        ]

    main_tag, main_latest_tag = None, None
    if main_head:
        rc, mtag_out, _ = runner(["git", "-C", str(repo_dir), "tag", "--points-at", main_branch, "--sort=-v:refname"])
        if rc == 0:
            mtags = [t.strip() for t in mtag_out.splitlines() if t.strip()]
            main_tag = mtags[0] if mtags else None
        rc, mmerged_out, _ = runner(["git", "-C", str(repo_dir), "tag", "--merged", main_branch, "--sort=-v:refname"])
        if rc == 0:
            merged_tags = [t.strip() for t in mmerged_out.splitlines() if t.strip()]
            main_latest_tag = merged_tags[0] if merged_tags else main_tag
        else:
            main_latest_tag = main_tag

    latest_tag = stable["latest_tag"]
    latest_tag_on_main = git_is_ancestor(repo_dir, latest_tag, main_branch, cmd_runner=runner) if (latest_tag and main_head) else True
    commits_since_latest_tag = git_commits_ahead(repo_dir, latest_tag, dev_branch if dev_head else "HEAD", no_merges=True, cmd_runner=runner) if latest_tag else 0
    main_ver = read_version_from_ref(repo_dir, main_branch if main_head else "", version_rel, version_json_path=version_json_path, cmd_runner=runner)
    dev_ver = read_version_from_ref(repo_dir, dev_branch if dev_head else "", version_rel, version_json_path=version_json_path, cmd_runner=runner)
    if dev_ver is None:
        dev_ver = stable["version"]

    main_ahead_of_dev, dev_ahead_of_main = 0, 0
    if dev_head and main_head and dev_branch != main_branch:
        rc, cnt_out, _ = runner(["git", "-C", str(repo_dir), "rev-list", "--left-right", "--count", f"{main_branch}...{dev_branch}"])
        if rc == 0:
            parts = cnt_out.strip().split()
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                main_ahead_of_dev, dev_ahead_of_main = int(parts[0]), int(parts[1])

    stable["branches"] = {
        "main_branch": main_branch, "dev_branch": dev_branch, "main_head": main_head, "dev_head": dev_head,
        "main_tag": main_tag, "main_latest_tag": main_latest_tag, "latest_tag_on_main": latest_tag_on_main,
        "commits_since_latest_tag": commits_since_latest_tag, "main_plugin_version": main_ver,
        "dev_plugin_version": dev_ver, "main_ahead_of_dev": main_ahead_of_dev,
        "dev_ahead_of_main": dev_ahead_of_main, "branch_drift": (main_ahead_of_dev > 0 or dev_ahead_of_main > 0),
    }

    wip = snapshot["wip"]
    rc, branch_out, _ = runner(["git", "-C", str(repo_dir), "rev-parse", "--abbrev-ref", "HEAD"])
    if rc == 0:
        wip["branch"] = branch_out.strip()
    rc, head_out, _ = runner(["git", "-C", str(repo_dir), "rev-parse", "--short", "HEAD"])
    if rc == 0:
        wip["head"] = head_out.strip()
    rc, status_out, _ = runner(["git", "-C", str(repo_dir), "status", "--porcelain=v1"])
    if rc == 0:
        wip_files, wip_counts = parse_porcelain_lines(status_out)
        code_wip = [f for f in wip_files if not is_runtime_ignored_path(f["path"], ignore_paths)]
        wip.update({
            "files": wip_files, "counts": wip_counts, "is_dirty": wip_counts["total"] > 0,
            "code_wip_count": len(code_wip), "runtime_only_wip": wip_counts["total"] > 0 and len(code_wip) == 0,
        })


def collect_project_snapshot(
    project_cfg: dict,
    base_dir: Path,
    changelogs_dir: Path,
    installed_plugins_map: dict[str, dict] | None = None,
    dry_run: bool = False,
    concept_root: Path | None = None,
    default_preset: str = "generic",
    max_changelog_lines: int = 45,
    cmd_runner: Callable[..., tuple[int, str, str]] | None = None,
) -> dict:
    """Collecte en lecture seule les métadonnées stables, conformité et WIP d'un dépôt suivi."""
    runner = cmd_runner or run_readonly_cmd
    project_id = str(project_cfg["id"])
    raw_path = Path(str(project_cfg["path"]))
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

    snapshot = _init_project_snapshot(project_cfg, repo_dir, preset, main_branch, dev_branch)
    if not snapshot["exists"]:
        return snapshot

    stable = snapshot["stable"]
    stable["compliance"] = evaluate_project_compliance(project_cfg, repo_dir, default_preset=preset)

    version_rel = detect_version_source(project_cfg, repo_dir, default_preset=preset)
    if version_rel and (repo_dir / version_rel).is_file():
        try:
            parsed_ver = parse_version_from_text(
                version_rel,
                (repo_dir / version_rel).read_text(encoding="utf-8-sig", errors="replace"),
                version_json_path=version_json_path,
            )
            stable.update({
                "version": parsed_ver["version"], "version_source": version_rel,
                "plugin_version": parsed_ver["version"], "plugin_name": parsed_ver["name"],
                "display_name": parsed_ver["display_name"],
            })
        except OSError:
            pass

    manifest_rel = detect_plugin_manifest(project_cfg, repo_dir)
    if preset == "antigravity-plugin" and installed_plugins_map:
        installed_info = installed_plugins_map.get(stable["plugin_name"] or project_id) or installed_plugins_map.get(project_id)
        if installed_info:
            inst_ver = installed_info.get("version")
            stable["installed_version"] = inst_ver
            stable["installed_enabled"] = installed_info.get("enabled", True)
            stable["install_drift"] = bool(stable["version"] and inst_ver and stable["version"] != inst_ver)
            inst_path_str, plugin_src_rel = installed_info.get("install_path"), manifest_rel or version_rel
            if plugin_src_rel and inst_path_str:
                cmp_res = compare_plugin_dirs(repo_dir / Path(str(plugin_src_rel)).parent, Path(inst_path_str))
                stable["install_content_compared"] = cmp_res["compared"]
                if cmp_res["compared"]:
                    stable["install_content_drift"] = not cmp_res["in_sync"]
                    stable["install_content_diff_files"] = cmp_res["diff_files"][:10]

    changelog_rel = project_cfg.get("changelog") or ("CHANGELOG.md" if (repo_dir / "CHANGELOG.md").is_file() else None)
    if changelog_rel and (repo_dir / str(changelog_rel)).is_file():
        changelog_text = (repo_dir / str(changelog_rel)).read_text(encoding="utf-8", errors="replace")
        stable["has_changelog"] = True
        stable["changelog_archive"] = f"{archive_rel_prefix}/{project_id}-CHANGELOG.md"
        stable["changelog_sha256"] = hashlib.sha256(changelog_text.encode("utf-8")).hexdigest()
        stable.update(extract_latest_changelog_section(changelog_text, max_lines=max_changelog_lines))
        if not dry_run:
            archive_file = changelogs_dir / f"{project_id}-CHANGELOG.md"
            norm_chg = changelog_text.replace("\r\n", "\n")
            if not archive_file.is_file() or archive_file.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n") != norm_chg:
                write_utf8(archive_file, norm_chg)

    agents_rel = project_cfg.get("agents_file", "AGENTS.md")
    if agents_rel and (repo_dir / str(agents_rel)).is_file():
        agents_text = (repo_dir / str(agents_rel)).read_text(encoding="utf-8", errors="replace")
        stable["has_agents_md"] = True
        stable["agents_md_sha256"] = hashlib.sha256(agents_text.encode("utf-8")).hexdigest()
        stable["agents_md_lines"] = agents_text.splitlines()

    _collect_git_metadata(snapshot, repo_dir, main_branch, dev_branch, version_rel, version_json_path, ignore_paths, runner)
    return snapshot
