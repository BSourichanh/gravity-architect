#!/usr/bin/env python3
"""Read-only SPI-1 Gravity Architect Hot/Cold atelier & code audits dashboard provider (100% stdlib)."""

from __future__ import annotations

import argparse, hashlib, json, os, re, sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from _shared.path_safety import ensure_no_symlink_or_junction_under, is_symlink_or_junction, is_within_root, safe_home_dir  # noqa: E402
from core.io_utils import (  # noqa: E402
    BRANCH_LINE_RE, DEPS_LINE_RE, EMPTY_FIELD_TOKENS, MD_H1_RE, PROFILE_LINE_RE,
    SPEC_SOURCE_RE, STATUS_LINE_RE, TARGET_LINE_RE, WAVE_LINE_RE,
    clean_md_field, configure_utf8_stdio, default_architect_home,
)

MAX_PAYLOAD_BYTES, MAX_HEAD_BYTES, MAX_ECOSYSTEM_BYTES = 450_000, 32_768, 65_536
ATELIERS_REGISTRY_FILENAME = "ateliers.json"
_HYGIENE_BLOCK_RE = re.compile(r"<!--\s*AUTO:START:ecosystem-hygiene\s*-->(.*?)<!--\s*AUTO:END:ecosystem-hygiene\s*-->", re.DOTALL | re.IGNORECASE)
_PROJECTS_BLOCK_RE = re.compile(r"<!--\s*AUTO:START:ecosystem-projects\s*-->(.*?)<!--\s*AUTO:END:ecosystem-projects\s*-->", re.DOTALL | re.IGNORECASE)
_HYGIENE_HEADING_RE = re.compile(r"(?:^|\n)#{2,3}\s+(?:Alertes(?:\s+(?:d'|de\s+)?)?hygi[eè]ne|Hygiene\s+alerts?)[^\n]*\n(.*?)(?=\n#{1,3}\s+|\Z)", re.DOTALL | re.IGNORECASE)
_NO_HYGIENE_ALERT_RE = re.compile(r"(?:aucune\s+alerte\s+d'hygi[eè]ne|no\s+hygiene\s+alerts?)", re.IGNORECASE)
_DELTA_DATE_RE = re.compile(r"^\s*-\s*\*\*(?:Date|Synced\s+at)\s*:\*\*\s*`?([^`\n]+)`?", re.MULTILINE | re.IGNORECASE)
_DELTA_STATUS_RE = re.compile(r"^\s*-\s*\*\*(?:Statut\s+[ée]ditorial|Editorial\s+status)\s*:\*\*\s*`?([^`\n]+)`?", re.MULTILINE | re.IGNORECASE)
_DELTA_WATCHES_RE = re.compile(r"^\s*-\s*\*\*(?:Veilles|Watches)\s*:\*\*\s*`?([^`\n]+)`?", re.MULTILINE | re.IGNORECASE)
_DELTA_TARGETS_RE = re.compile(r"^\s*-\s*\*\*(?:Cibles\s+[ée]ditoriales\s+LLM|LLM\s+editorial\s+targets)\s*:\*\*\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
_AUDIT_TARGET_RE = re.compile(r"^\s*-\s*\*\*(?:D[ée]p[ôo]t\s+cible|Target(?:\s+(?:project|repo(?:sitory)?))?|Projets?\s+impact[ée]s?|Impacted\s+projects?|Cible)(?:\s*:\*\*|\*\*\s*:)\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\b")
_VERDICT_LINE_RE = re.compile(r"(?:^|\n)\s*(?:[-*]\s+)?(?:\*\*|__)?(?:Verdict(?:\s+global)?|Statut(?:\s+global)?|Status|Conclusion|R[ée]sultat|Result)(?:\*\*|__)?\s*[:：]\s*(?:\*\*|__)?\s*(.+)", re.IGNORECASE)
_VERDICT_HEADING_RE = re.compile(r"(?:^|\n)\s*#{1,4}\s+(?:Verdict(?:\s+global)?|Conclusion|Statut(?:\s+global)?|Status)\s*\n+([^\n#]+)", re.IGNORECASE)
_CANONICAL_VERDICT_RE = re.compile(r"\b(NON[\s-]+BLOQUANT|BLOQUANT|PASS|PARTIAL|PARTIEL|FAIL|UNTESTED|WARN(?:ING)?|OK|KO)\b", re.IGNORECASE)

def _clean_inline(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[*_`]+", "", text or "").strip())

def _truncate_preview(text: str, max_chars: int = 160) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    return cleaned if len(cleaned) <= max_chars else (cleaned[:max_chars] if max_chars <= 3 else cleaned[: max_chars - 3].rstrip() + "...")

def _stat_token(path: Optional[Path]) -> str:
    if path is None:
        return "missing"
    if is_symlink_or_junction(path):
        return "symlink"
    try:
        st = path.stat()
        return f"{st.st_mtime_ns}:{st.st_size}"
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "error"

def _file_uri_if_exists(path: Path) -> str:
    try:
        return path.resolve().as_uri() if (not is_symlink_or_junction(path) and path.is_file()) else ""
    except OSError:
        return ""

def _read_head_text_ro(path: Path, max_bytes: int = MAX_HEAD_BYTES) -> Optional[tuple[str, int, str]]:
    try:
        if is_symlink_or_junction(path) or not path.is_file():
            return None
        st = path.stat()
        with path.open("rb") as fh:
            raw = fh.read(max_bytes)
    except OSError:
        return None
    return raw.decode("utf-8", errors="replace").lstrip("\ufeff"), int(st.st_size), datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _read_json_ro(path: Path, warnings: list[str]) -> Any:
    if is_symlink_or_junction(path):
        warnings.append(f"Ignored symlink or junction JSON: {path.name}.")
        return None
    try:
        raw = path.read_bytes()
    except OSError as exc:
        warnings.append(f"Failed to read {path.name}: {exc}")
        return None
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
        warnings.append(f"UTF-8 BOM detected in {path.name}.")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        warnings.append(f"Invalid JSON in {path.name}: {exc}")
        return None

def _has_atelier_markers(candidate: Path, *, require_both: bool = False) -> bool:
    try:
        if is_symlink_or_junction(candidate) or not candidate.is_dir():
            return False
        eco, proj = candidate / "ECOSYSTEM.md", candidate / "projects.json"
        has_eco, has_proj = (not is_symlink_or_junction(eco) and eco.is_file()), (not is_symlink_or_junction(proj) and proj.is_file())
        return (has_eco and has_proj) if require_both else (has_eco or has_proj)
    except OSError:
        return False

def _norm_path_key(path: Path) -> str:
    try:
        return os.path.normcase(str(path.resolve()))
    except OSError:
        return os.path.normcase(str(path))

def _resolve_raw_architect_home(*, gravity_home: Optional[Path], architect_home: Optional[Path]) -> Path:
    if architect_home is not None:
        return Path(architect_home).expanduser()
    if env_arch := os.environ.get("GRAVITY_ARCHITECT_HOME", "").strip():
        return Path(env_arch).expanduser()
    return (Path(gravity_home).expanduser() / "architect") if gravity_home is not None else default_architect_home(home_dir=safe_home_dir())

def _load_registered_ateliers_ro(reg_path: Path, warnings: list[str]) -> list[dict[str, Any]]:
    try:
        if is_symlink_or_junction(reg_path.parent) or is_symlink_or_junction(reg_path):
            warnings.append(f"Ignored symlinked or junction ateliers registry: {reg_path}.")
            return []
        if not reg_path.is_file():
            return []
    except OSError:
        return []
    data = _read_json_ro(reg_path, warnings)
    if not isinstance(data, dict):
        if data is not None:
            warnings.append("Invalid structure in ateliers.json: expected JSON object.")
        return []
    if not isinstance(entries := data.get("ateliers"), list):
        warnings.append("Invalid 'ateliers' field in ateliers.json: expected list.")
        return []
    collected = []
    for raw in entries:
        if isinstance(raw, dict) and (raw_ws := str(raw.get("workspace_path") or "").strip()) and _has_atelier_markers(cand := Path(raw_ws).expanduser(), require_both=True):
            res = cand.resolve()
            collected.append({"workspace_path": str(res), "workspace_name": str(raw.get("workspace_name") or "").strip() or res.name, "updated_at": str(raw.get("updated_at") or "").strip(), "source": "architect_registry"})
    collected.sort(key=lambda item: (str(item.get("updated_at") or ""), str(item.get("workspace_path") or "")), reverse=True)
    deduped, seen = [], set()
    for item in collected:
        if (key := _norm_path_key(Path(item["workspace_path"]))) not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped

def _resolve_atelier_root(
    *, atelier: str, ws: str, gravity_home: Optional[Path], architect_home: Optional[Path],
    architect_workspace: Optional[Path], registry_ateliers: list[dict[str, Any]], warnings: list[str],
) -> tuple[Path, str, bool]:
    if architect_workspace is not None:
        cand = Path(architect_workspace).expanduser()
        if is_symlink_or_junction(cand):
            warnings.append(f"Refused symlink or junction architect_workspace: {cand}.")
            return cand, "arg_workspace", True
        return cand.resolve(), "arg_workspace", False
    if selected := atelier.strip():
        cand = Path(selected).expanduser()
        if _has_atelier_markers(cand, require_both=True):
            return cand.resolve(), "selected_atelier", False
        if not is_symlink_or_junction(cand):
            cand_key = _norm_path_key(cand)
            for known in registry_ateliers:
                if _norm_path_key(kp := Path(str(known.get("workspace_path") or ""))) == cand_key and _has_atelier_markers(kp, require_both=True):
                    return kp.resolve(), "selected_atelier", False
        warnings.append(f"Invalid, symlink/junction, or incomplete atelier selected: {selected!r}.")
        return cand, "selected_atelier", True
    if env_ws := os.environ.get("GRAVITY_ARCHITECT_WORKSPACE", "").strip():
        cand = Path(env_ws).expanduser()
        if is_symlink_or_junction(cand):
            warnings.append(f"Refused symlink or junction GRAVITY_ARCHITECT_WORKSPACE: {cand}.")
            return cand, "env_workspace", True
        return cand.resolve(), "env_workspace", False
    if architect_home is not None and _has_atelier_markers(arch_raw := Path(architect_home).expanduser(), require_both=False):
        return arch_raw.resolve(), "architect_home", False
    if (env_arch := os.environ.get("GRAVITY_ARCHITECT_HOME", "").strip()) and _has_atelier_markers(arch_env := Path(env_arch).expanduser(), require_both=False):
        return arch_env.resolve(), "env_architect_home", False
    if (ws_hint := ws.strip()) and _has_atelier_markers(ws_cand := Path(ws_hint).expanduser(), require_both=True):
        return ws_cand.resolve(), "ws_hint", False
    if registry_ateliers:
        return Path(registry_ateliers[0]["workspace_path"]), "architect_registry", False
    if architect_home is not None:
        return Path(architect_home).expanduser().resolve(), "module_home", False
    env_map = {**os.environ, "GRAVITY_HOME": str(gravity_home)} if gravity_home is not None else None
    return default_architect_home(env=env_map, home_dir=safe_home_dir()), "module_home", False

def _extract_bullet_alerts(block: str) -> list[str]:
    return [
        _truncate_preview(cleaned, 200) for raw_line in block.splitlines()
        if (line := raw_line.strip()).startswith(("-", "*")) and (cleaned := _clean_inline(line[1:].strip())) and not _NO_HYGIENE_ALERT_RE.search(cleaned)
    ]

def _parse_ecosystem_projects_table(text: str) -> dict[str, dict[str, str]]:
    if not (m_block := _PROJECTS_BLOCK_RE.search(text)):
        return {}
    out: dict[str, dict[str, str]] = {}
    for raw_line in m_block.group(1).splitlines():
        if not (line := raw_line.strip()).startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5 or all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in cells if c):
            continue
        first_clean = _clean_inline(cells[0])
        if (first_low := first_clean.lower()) in ("projet", "project"):
            continue
        pid = m_id.group(1).strip() if (m_id := re.search(r"\(\s*(?:\.\./)?([A-Za-z0-9._-]+)\s*\)", first_clean)) else (m_card.group(1).strip() if len(cells) >= 6 and (m_card := re.search(r"([A-Za-z0-9._-]+)\.md", cells[5])) else re.sub(r"[^a-z0-9._-]+", "-", first_low).strip("-"))
        if pid:
            out[pid] = {"id": pid, "label": _clean_inline(re.sub(r"\([^)]*\)", "", cells[0])).strip() or pid, "release_main": _clean_inline(cells[1]), "dev_status": _clean_inline(cells[2]), "installed_version": _clean_inline(cells[3]), "wip_status": _clean_inline(cells[4])}
    return out

def _read_ecosystem_ro(eco_path: Path, budget_bytes: Optional[int]) -> dict[str, Any]:
    uri = _file_uri_if_exists(eco_path)
    if (loaded := _read_head_text_ro(eco_path, MAX_ECOSYSTEM_BYTES)) is None:
        return {"exists": False, "size_bytes": 0, "budget_bytes": budget_bytes, "over_budget": False, "updated_at": "", "uri": "", "alerts": [], "projects_status": {}}
    text, size_bytes, updated_at = loaded
    m_block = _HYGIENE_BLOCK_RE.search(text) or _HYGIENE_HEADING_RE.search(text)
    return {
        "exists": True, "size_bytes": size_bytes, "budget_bytes": budget_bytes,
        "over_budget": bool(budget_bytes and size_bytes > budget_bytes), "updated_at": updated_at,
        "uri": uri, "alerts": _extract_bullet_alerts(m_block.group(1)) if m_block else [], "projects_status": _parse_ecosystem_projects_table(text),
    }

def _read_delta_ro(delta_path: Path) -> dict[str, Any]:
    uri = _file_uri_if_exists(delta_path)
    if (loaded := _read_head_text_ro(delta_path, MAX_HEAD_BYTES)) is None:
        return {"exists": False, "date": "", "editorial_status": "", "watches_status": "", "editorial_targets": [], "hygiene_alerts": [], "uri": ""}
    text, _, _ = loaded
    date_m, stat_m, watch_m, tgt_m, hyg_m = _DELTA_DATE_RE.search(text), _DELTA_STATUS_RE.search(text), _DELTA_WATCHES_RE.search(text), _DELTA_TARGETS_RE.search(text), _HYGIENE_HEADING_RE.search(text)
    targets = [t.strip() for t in raw_t.split(",") if t.strip()] if (tgt_m and (raw_t := _clean_inline(tgt_m.group(1))) and raw_t.lower() not in EMPTY_FIELD_TOKENS) else []
    return {
        "exists": True, "date": date_m.group(1).strip() if date_m else "",
        "editorial_status": stat_m.group(1).strip() if stat_m else "", "watches_status": watch_m.group(1).strip() if watch_m else "",
        "editorial_targets": targets, "hygiene_alerts": _extract_bullet_alerts(hyg_m.group(1)) if hyg_m else [], "uri": uri,
    }

def _read_projects_ro(projects_path: Path, atelier_root: Path, warnings: list[str]) -> tuple[bool, str, bool, dict[str, int], int, list[dict[str, Any]]]:
    if is_symlink_or_junction(projects_path) or not projects_path.is_file():
        return False, "", False, {}, 0, []
    data = _read_json_ro(projects_path, warnings)
    if not isinstance(data, dict):
        if data is not None:
            warnings.append("Invalid structure in projects.json: expected JSON object.")
        return False, "", False, {}, 0, []
    ws_name = str(data.get("workspace_name") or "").strip()
    privacy = data.get("privacy") if isinstance(data.get("privacy"), dict) else {}
    public_mode = bool(privacy.get("public_mode", data.get("public_mode", False)))
    hot_budgets = {k: v for k, v in (data.get("hot_budgets") if isinstance(data.get("hot_budgets"), dict) else {}).items() if isinstance(k, str) and isinstance(v, int)}
    card_budget, watches_count, projects_out = hot_budgets.get("project_card_max_bytes"), (len(data["watches"]) if isinstance(data.get("watches"), list) else 0), []
    for raw in data.get("projects") or []:
        if not isinstance(raw, dict) or not (pid := str(raw.get("id") or "").strip()):
            continue
        card_path = atelier_root / "tracking" / "projects" / f"{pid}.md"
        try:
            card_bytes = int(card_path.stat().st_size) if (not is_symlink_or_junction(card_path) and card_path.is_file()) else 0
        except OSError:
            card_bytes = 0
        dev_branch = str(raw.get("default_dev_branch") or raw.get("dev_branch") or "dev")
        projects_out.append({"id": pid, "name": str(raw.get("name") or pid), "path": str(raw.get("path") or raw.get("repo_path") or ""), "role": str(raw.get("role") or ""), "main_branch": str(raw.get("main_branch") or raw.get("branch") or "main"), "default_dev_branch": dev_branch, "dev_branch": dev_branch, "card_uri": _file_uri_if_exists(card_path), "card_bytes": card_bytes, "over_budget": bool(card_budget and card_bytes > card_budget)})
    return True, ws_name, public_mode, hot_budgets, watches_count, projects_out

def _normalize_status_code(status_val: str) -> str:
    low = status_val.strip().lower()
    if not low or low == "unknown":
        return "unknown"
    cand = re.sub(r"^\d{4}-\d{2}-\d{2}\s*(?:[—–-]|/)?\s*", "", low).strip() or low
    for code in ("ready", "validated", "draft", "backlog", "in_progress", "in-progress", "running", "blocked", "done", "completed", "archived", "pending"):
        if re.search(rf"\b{re.escape(code)}\b", cand):
            return code.replace("-", "_")
    return m.group(1) if (m := re.match(r"([a-z0-9_-]+)", cand)) else "unknown"

def _parse_dependencies_list(raw: str) -> list[str]:
    cleaned = _clean_inline(re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", raw))
    return [] if cleaned.lower() in EMPTY_FIELD_TOKENS else [tok.strip() for tok in re.split(r"[,|;]+", cleaned) if tok.strip() and tok.strip().lower() not in EMPTY_FIELD_TOKENS]

def _scan_flat_artifacts_ro(directory: Path, atelier_root: Path) -> list[dict[str, Any]]:
    if is_symlink_or_junction(directory) or not directory.is_dir():
        return []
    try:
        candidates = sorted(directory.iterdir(), key=lambda p: p.name, reverse=True)
    except OSError:
        return []
    root_res, items = atelier_root.resolve(), []
    for fpath in candidates:
        if is_symlink_or_junction(fpath) or not fpath.is_file() or fpath.suffix.lower() != ".md" or fpath.name.startswith("_") or not is_within_root(root_res, fpath) or (loaded := _read_head_text_ro(fpath, MAX_HEAD_BYTES)) is None:
            continue
        text, size_bytes, updated_at = loaded
        status_m, target_m = STATUS_LINE_RE.search(text), (TARGET_LINE_RE.search(text) or _AUDIT_TARGET_RE.search(text))
        wave_m, deps_m, profile_m, spec_src_m, branch_m = WAVE_LINE_RE.search(text), DEPS_LINE_RE.search(text), PROFILE_LINE_RE.search(text), SPEC_SOURCE_RE.search(text), BRANCH_LINE_RE.search(text)
        status_val = _clean_inline(status_m.group(1)) if status_m else "unknown"
        target_val = _clean_inline(re.sub(r"\*?\([^)]*\)\*?", "", target_m.group(1)).strip()) if target_m else ""
        wave_val = int(wd.group(0)) if (wave_m and (wd := re.search(r"\d+", clean_md_field(wave_m.group(1))))) else None
        spec_source = (lm.group(1).strip() if (lm := re.search(r"\[[^\]]*\]\(([^)]+)\)", raw_spec := spec_src_m.group(1).strip())) else clean_md_field(raw_spec)) if spec_src_m else ""
        resolved_f, title_m, date_m = fpath.resolve(), MD_H1_RE.search(text[:8_192]), _DATE_PREFIX_RE.match(fpath.name)
        items.append({
            "filename": fpath.name, "rel_path": resolved_f.relative_to(root_res).as_posix(),
            "title": _clean_inline(title_m.group(1)) if title_m and _clean_inline(title_m.group(1)) else fpath.stem,
            "date": date_m.group(1) if date_m else updated_at[:10], "status": status_val, "status_code": _normalize_status_code(status_val),
            "target_project": target_val, "wave": wave_val, "dependencies": _parse_dependencies_list(deps_m.group(1)) if deps_m else [],
            "workflow_profile": clean_md_field(profile_m.group(1)) if profile_m else "", "spec_source": spec_source,
            "expected_branch": clean_md_field(branch_m.group(1)) if branch_m else "", "size_bytes": size_bytes, "updated_at": updated_at, "uri": resolved_f.as_uri(),
        })
    return items

def _classify_verdict_tone(verdict_text: str) -> str:
    up = verdict_text.upper()
    if re.search(r"\bUNTESTED\b", up):
        return "neutral"
    if re.search(r"(?<!NON[\s-])\bBLOQUANT\b", up) or any(t in up for t in ("FAIL", "REJECT", "REFUS", "CRITIQUE", "ERROR")) or re.search(r"\bKO\b", up):
        return "danger"
    if any(t in up for t in ("PARTIAL", "PARTIEL", "WARN", "ATTENTION", "CORRIGER", "CONDITIONAL", "MITIG")):
        return "warn"
    if "NON BLOQUANT" in up or "NON-BLOQUANT" in up or any(t in up for t in ("PASS", "VALID", "APPROUV", "APPROVED", "CLEAN", "SUCC")) or re.search(r"\bOK\b", up):
        return "ok"
    return "neutral"

def _extract_verdict(text: str) -> tuple[str, str]:
    if not (m := _VERDICT_LINE_RE.search(text[:16_384]) or _VERDICT_HEADING_RE.search(text[:16_384])):
        return "", "neutral"
    cleaned = _clean_inline(m.group(1))
    prefix = re.split(r"\s*(?:\||—|–|\s-\s)\s*", cleaned, maxsplit=1)[0].strip() or cleaned
    val = (re.sub(r"\s+", " ", cm.group(1).upper()).replace("WARNING", "WARN") if (cm := _CANONICAL_VERDICT_RE.search(prefix)) else (prefix if len(prefix) <= 40 else prefix[:37].rstrip() + "..."))
    return val, _classify_verdict_tone(val) if val else "neutral"

def _extract_excerpt(text: str, max_chars: int = 160) -> str:
    for line in text[:4_096].splitlines():
        if (s := line.strip()) and not s.startswith(("#", "---", "|", "<!--")) and len(cleaned := _clean_inline(s)) >= 12:
            return _truncate_preview(cleaned, max_chars)
    return ""

def _is_agents_audit_path(code_dir_resolved: Path, file_path: Path, resolved_file: Path) -> bool:
    for candidate in (file_path, resolved_file):
        try:
            if any(part.lower() == "agents" for part in candidate.relative_to(code_dir_resolved).parts[:-1]):
                return True
        except ValueError:
            return True
    dir_parts = [part.lower() for part in resolved_file.parts[:-1]]
    return any(dir_parts[i] == "audits" and dir_parts[i + 1] == "agents" for i in range(len(dir_parts) - 1))

def _scan_code_audits_ro(atelier_root: Path) -> tuple[list[dict[str, Any]], Optional[dict[str, Any]], list[dict[str, Any]], list[tuple[str, str]]]:
    code_dir = atelier_root / "audits" / "code"
    if is_symlink_or_junction(atelier_root / "audits") or is_symlink_or_junction(code_dir) or not code_dir.is_dir():
        return [], None, [], []
    code_resolved = code_dir.resolve()
    try:
        candidates = sorted(code_resolved.rglob("*"))
    except OSError:
        return [], None, [], []
    regular, index_audits, sig_tokens = [], [], []
    for fpath in candidates:
        if not fpath.is_file() or fpath.suffix.lower() != ".md" or fpath.name.startswith("_"):
            continue
        try:
            ensure_no_symlink_or_junction_under(code_resolved, fpath)
            resolved_file = fpath.resolve()
            if resolved_file.name.startswith("_") or not is_within_root(code_resolved, resolved_file) or _is_agents_audit_path(code_resolved, fpath, resolved_file):
                continue
            rel_posix = resolved_file.relative_to(code_resolved).as_posix()
        except (OSError, ValueError):
            continue
        if (loaded := _read_head_text_ro(resolved_file, MAX_HEAD_BYTES)) is None:
            continue
        text, size_bytes, updated_at = loaded
        sig_tokens.append((rel_posix, _stat_token(resolved_file)))
        date_m, target_m, title_m = _DATE_PREFIX_RE.match(resolved_file.name), _AUDIT_TARGET_RE.search(text), MD_H1_RE.search(text[:8_192])
        verdict, verdict_tone = _extract_verdict(text)
        entry = {
            "audit_id": f"code:{rel_posix}", "rel_path": rel_posix,
            "title": _clean_inline(title_m.group(1)) if title_m and _clean_inline(title_m.group(1)) else resolved_file.stem,
            "verdict": verdict, "verdict_tone": verdict_tone, "target": _clean_inline(target_m.group(1)) if target_m else "",
            "date": date_m.group(1) if date_m else updated_at[:10], "updated_at": updated_at,
            "size_bytes": size_bytes, "excerpt": _extract_excerpt(text), "uri": resolved_file.as_uri(),
        }
        (index_audits if rel_posix.lower() == "readme.md" else regular).append(entry)
    index_audits.sort(key=lambda a: str(a.get("rel_path") or "").casefold())
    regular.sort(key=lambda a: (str(a.get("date") or ""), str(a.get("updated_at") or ""), str(a.get("rel_path") or "")), reverse=True)
    return regular, (index_audits[0] if index_audits else None), index_audits, sig_tokens

def _dir_md_tokens(directory: Path) -> list[tuple[str, str]]:
    if is_symlink_or_junction(directory) or not directory.is_dir():
        return []
    try:
        return [(p.name, _stat_token(p)) for p in sorted(directory.iterdir(), key=lambda x: x.name) if not is_symlink_or_junction(p) and p.is_file() and p.suffix.lower() == ".md" and not p.name.startswith("_")]
    except OSError:
        return []

def _merge_ateliers(registry_ateliers: list[dict[str, Any]], *, current_root: Path, current_available: bool, current_name: str, current_updated_at: str, current_source: str) -> list[dict[str, Any]]:
    merged, seen = [], set()
    for item in registry_ateliers:
        if (raw_p := str(item.get("workspace_path") or "").strip()) and (key := _norm_path_key(Path(raw_p))) not in seen:
            seen.add(key)
            merged.append(dict(item))
    if current_available and _norm_path_key(current_root) not in seen:
        merged.append({"workspace_path": str(current_root), "workspace_name": current_name or current_root.name, "updated_at": current_updated_at, "source": current_source})
    return merged

def _target_mentions_project(target_str: str, pid: str, pname: str) -> bool:
    tokens = {tok.strip().casefold() for tok in re.split(r"[|,;/()]+", target_str) if tok.strip()} if target_str else set()
    return bool(tokens) and ((bool(pid) and pid.casefold() in tokens) or (bool(pname) and pname.casefold() in tokens))

def _enrich_projects_ro(projects: list[dict[str, Any]], ecosystem: dict[str, Any], specs: list[dict[str, Any]], tasks: list[dict[str, Any]], audits: list[dict[str, Any]]) -> None:
    eco_map = ecosystem.get("projects_status") if isinstance(ecosystem.get("projects_status"), dict) else {}
    eco_by_cf = {str(k).casefold(): v for k, v in eco_map.items() if isinstance(v, dict)}
    for proj in projects:
        pid, pname = str(proj.get("id") or ""), str(proj.get("name") or "")
        path_name = Path(str(proj.get("path") or "")).name if proj.get("path") else ""
        eco = eco_by_cf.get(pid.casefold()) or (eco_by_cf.get(path_name.casefold()) if path_name else None) or {}
        proj.update({
            "release_main": str(eco.get("release_main") or ""), "dev_status": str(eco.get("dev_status") or ""),
            "installed_version": str(eco.get("installed_version") or ""), "wip_status": str(eco.get("wip_status") or ""),
            "specs_count": sum(1 for s in specs if _target_mentions_project(str(s.get("target_project") or ""), pid, pname)),
            "tasks_count": sum(1 for t in tasks if _target_mentions_project(str(t.get("target_project") or ""), pid, pname)),
            "audits_count": sum(1 for a in audits if _target_mentions_project(str(a.get("target") or ""), pid, pname)),
        })

def _build_waves_summary(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    by_wave: dict[Optional[int], list[dict[str, Any]]] = {}
    for task in tasks:
        by_wave.setdefault(w if isinstance(w := task.get("wave"), int) else None, []).append(task)
    ordered = sorted(k for k in by_wave if k is not None) + ([None] if None in by_wave else [])
    waves = []
    for w_num in ordered:
        w_tasks, status_counts, projs = by_wave[w_num], {}, set()
        for wt in w_tasks:
            sc = str(wt.get("status_code") or "unknown")
            status_counts[sc] = status_counts.get(sc, 0) + 1
            projs.update(tok.strip() for tok in re.split(r"[|,;/]+", str(wt.get("target_project") or "").strip()) if tok.strip())
        waves.append({"wave": w_num, "tasks_count": len(w_tasks), "projects": sorted(projs), "status_counts": status_counts, "filenames": [str(wt.get("filename") or "") for wt in w_tasks]})
    return {"total_tasks": len(tasks), "waves_count": len([k for k in ordered if k is not None]), "waves": waves}

def _enforce_payload_budget(payload: dict[str, Any], list_keys: Sequence[str], max_bytes: int = MAX_PAYLOAD_BYTES) -> dict[str, Any]:
    def _size() -> int:
        return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    if _size() < max_bytes:
        return payload
    payload["truncated"] = True
    for key in list_keys:
        items = payload.get(key)
        while _size() >= max_bytes and isinstance(items, list) and items:
            items = items[: max(0, len(items) // 2)]
            payload[key] = items
    return payload


def get_architect_view(
    since_signature: str = "", *, atelier: str = "", ws: str = "",
    gravity_home: Optional[Path] = None, architect_home: Optional[Path] = None, architect_workspace: Optional[Path] = None,
) -> dict[str, Any]:
    """Return read-only Gravity Architect atelier state, specs, tasks, and `audits/code/`."""
    warnings: list[str] = []
    reg_path = _resolve_raw_architect_home(gravity_home=gravity_home, architect_home=architect_home) / ATELIERS_REGISTRY_FILENAME
    registry_ateliers = _load_registered_ateliers_ro(reg_path, warnings)
    atelier_root, discovery_source, blocked = _resolve_atelier_root(
        atelier=atelier, ws=ws, gravity_home=gravity_home, architect_home=architect_home,
        architect_workspace=architect_workspace, registry_ateliers=registry_ateliers, warnings=warnings,
    )
    reg_sig = "symlink" if (is_symlink_or_junction(reg_path.parent) or is_symlink_or_junction(reg_path)) else _stat_token(reg_path)
    known_paths = [str(item.get("workspace_path") or "") for item in registry_ateliers]
    base_payload: dict[str, Any] = {
        "changed": True, "unchanged": False, "signature": "", "available": False, "atelier_root": str(atelier_root),
        "discovery_source": discovery_source, "workspace_name": atelier_root.name, "public_mode": False, "truncated": False, "ateliers": [],
        "ecosystem": {"exists": False, "size_bytes": 0, "budget_bytes": None, "over_budget": False, "updated_at": "", "uri": "", "alerts": [], "projects_status": {}},
        "delta": {"exists": False, "date": "", "editorial_status": "", "watches_status": "", "editorial_targets": [], "hygiene_alerts": [], "uri": ""},
        "hot_budgets": {}, "watches_count": 0, "projects": [], "specs": [], "tasks": [], "waves_summary": {"total_tasks": 0, "waves_count": 0, "waves": []},
        "archived_specs_count": 0, "archived_tasks_count": 0, "audits": [], "index_audit": None, "index_audits": [], "warnings": warnings,
    }
    if blocked:
        sig = hashlib.sha256("|".join(str(p) for p in [atelier.strip(), ws.strip(), atelier_root, discovery_source, "blocked", reg_sig, *known_paths]).encode("utf-8")).hexdigest()[:12]
        if since_signature and since_signature == sig:
            return {"changed": False, "unchanged": True, "signature": sig}
        base_payload.update({"signature": sig, "ateliers": _merge_ateliers(registry_ateliers, current_root=atelier_root, current_available=False, current_name="", current_updated_at="", current_source=discovery_source)})
        return _enforce_payload_budget(base_payload, ("audits", "tasks", "specs", "projects", "ateliers"))

    eco_path, delta_path, projects_path = atelier_root / "ECOSYSTEM.md", atelier_root / "tracking" / "snapshots" / "delta.md", atelier_root / "projects.json"
    specs_dir, tasks_dir = atelier_root / "specs", atelier_root / "tasks"
    active_tasks_dir = atelier_root / "handoffs" if not tasks_dir.exists() and not is_symlink_or_junction(tasks_dir) else tasks_dir
    audits, index_audit, index_audits, audit_tokens = _scan_code_audits_ro(atelier_root)
    arch_specs_tokens, arch_tasks_tokens = _dir_md_tokens(specs_dir / "archive"), _dir_md_tokens(active_tasks_dir / "archive")
    sig_parts = [atelier.strip(), ws.strip(), atelier_root, discovery_source, reg_sig, *known_paths, _stat_token(eco_path), _stat_token(delta_path), _stat_token(projects_path), *_dir_md_tokens(specs_dir), *_dir_md_tokens(active_tasks_dir), *arch_specs_tokens, *arch_tasks_tokens, *audit_tokens]
    sig = hashlib.sha256("|".join(str(p) for p in sig_parts).encode("utf-8")).hexdigest()[:12]
    if since_signature and since_signature == sig:
        return {"changed": False, "unchanged": True, "signature": sig}

    proj_exists, ws_name, public_mode, hot_budgets, watches_count, projects = _read_projects_ro(projects_path, atelier_root, warnings)
    ecosystem, delta = _read_ecosystem_ro(eco_path, hot_budgets.get("ECOSYSTEM.md")), _read_delta_ro(delta_path)
    specs, tasks = _scan_flat_artifacts_ro(specs_dir, atelier_root), _scan_flat_artifacts_ro(active_tasks_dir, atelier_root)
    _enrich_projects_ro(projects, ecosystem, specs, tasks, audits)
    available = bool(atelier_root.is_dir() and (ecosystem["exists"] or proj_exists or delta["exists"] or specs or tasks or audits or index_audit is not None))
    base_payload.update({
        "signature": sig, "available": available, "workspace_name": ws_name or atelier_root.name, "public_mode": public_mode,
        "ateliers": _merge_ateliers(registry_ateliers, current_root=atelier_root, current_available=available, current_name=ws_name or atelier_root.name, current_updated_at=delta.get("date") or ecosystem.get("updated_at") or "", current_source=discovery_source),
        "ecosystem": ecosystem, "delta": delta, "hot_budgets": hot_budgets, "watches_count": watches_count, "projects": projects,
        "specs": specs, "tasks": tasks, "waves_summary": _build_waves_summary(tasks),
        "archived_specs_count": len(arch_specs_tokens), "archived_tasks_count": len(arch_tasks_tokens), "audits": audits, "index_audit": index_audit, "index_audits": index_audits,
    })
    return _enforce_payload_budget(base_payload, ("audits", "tasks", "specs", "projects", "ateliers"))


def main(argv: Optional[list[str]] = None) -> int:
    configure_utf8_stdio()
    p = argparse.ArgumentParser(description="Read-only SPI-1 Gravity Architect dashboard provider.")
    p.add_argument("--view", choices=("architect",), default="architect")
    p.add_argument("--since-signature", default="")
    p.add_argument("--atelier", default="")
    p.add_argument("--ws", default="")
    p.add_argument("--action", default="")
    p.add_argument("--json", action="store_true")
    p.add_argument("--gravity-home", type=Path, default=None)
    p.add_argument("--architect-home", type=Path, default=None)
    p.add_argument("--architect-workspace", type=Path, default=None)
    args = p.parse_args(argv)
    if args.action:
        sys.stdout.write(json.dumps({"ok": False, "error": f"Unsupported action for module 'architect': {args.action}"}, ensure_ascii=False) + "\n")
        return 1
    params, ctx = {}, {}
    try:
        if sys.stdin is not None and not sys.stdin.isatty() and (raw := sys.stdin.read().strip()):
            data = json.loads(raw)
            if isinstance(data, dict):
                params = data.get("params") if isinstance(data.get("params"), dict) else {}
                ctx = data.get("context") if isinstance(data.get("context"), dict) else {}
    except (OSError, ValueError):
        pass
    def _opt(v: Any) -> Optional[Path]:
        return v if isinstance(v, Path) else (Path(v.strip()) if isinstance(v, str) and v.strip() else None)
    payload = get_architect_view(
        since_signature=args.since_signature or str(params.get("since_signature") or ""),
        atelier=args.atelier or str(params.get("atelier") or ""),
        ws=args.ws or str(params.get("ws") or ctx.get("ws") or ""),
        gravity_home=args.gravity_home or _opt(ctx.get("gravity_home")),
        architect_home=args.architect_home or _opt(ctx.get("architect_home")),
        architect_workspace=args.architect_workspace or _opt(ctx.get("architect_workspace")),
    )
    sys.stdout.write(json.dumps(payload, indent=None if args.json else 2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
