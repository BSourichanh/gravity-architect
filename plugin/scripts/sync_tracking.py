#!/usr/bin/env python3
"""Moteur générique de collecte lecture seule, delta éditorial et suivi Hot/Cold (façade)."""

from __future__ import annotations

import argparse, contextlib, hashlib, json, os, shutil, subprocess, sys  # noqa: E401
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from _shared.atomic_io import write_json_atomic  # noqa: E402
from _shared.file_lock import exclusive_file_lock  # noqa: E402
from _shared.path_safety import is_symlink_or_junction, safe_home_dir  # noqa: E402
from core.delta import (append_budget_alerts as _append_budget_alerts, build_acked_project_entry as _build_acked_project_entry, build_acked_surface_entry as _build_acked_surface_entry, collect_atelier_hygiene_alerts, collect_project_hygiene_alerts as _collect_project_hygiene_alerts, compute_delta, compute_delta_with_state, compute_unified_diff as _compute_unified_diff, editorial_state_from_snapshot as _editorial_state_from_snapshot, evaluate_hot_budgets, load_editorial_state as _load_editorial_state, stabilize_unchanged_timestamps as _stabilize_unchanged_timestamps)  # noqa: E402
from core.discovery import (REQUIRED_OFFICIAL_PLUGIN_FIELDS, check_agents_doc as _check_agents_doc, derive_validator_script, detect_plugin_manifest, detect_version_source, evaluate_antigravity_plugin_compliance as _evaluate_antigravity_plugin_compliance, evaluate_project_compliance, resolve_project_preset)  # noqa: E402
from core.git_collector import (INSTALL_ADAPTED_FILENAMES, INSTALL_IGNORED_DIRS, INSTALL_IGNORED_SUFFIXES, classify_porcelain_status as _classify_porcelain_status, collect_plugin_tree_hashes as _collect_plugin_tree_hashes, collect_project_snapshot, compare_plugin_dirs, extract_latest_changelog_section, extract_toml_section_value as _extract_toml_section_value, git_branch_short_rev as _git_branch_short_rev, git_commits_ahead as _git_commits_ahead, git_is_ancestor as _git_is_ancestor, git_show_text as _git_show_text, is_runtime_ignored_path as _is_runtime_ignored_path, parse_porcelain_lines as _parse_porcelain_lines, parse_version_from_text, read_version_from_ref as _read_version_from_ref)  # noqa: E402
from core.io_utils import (AUTO_BLOCK_RE, AUTO_DISCOVER_SKIP_DIRS, CHANGELOG_SECTION_RE, DATE_LINE_RE, DEFAULT_HOT_BUDGETS, MACHINE_ABS_PATH_RE, MD_H1_RE, SCHEMA_VERSION, SECTION_RE, SEMVER_RE, STATUS_LINE_RE, SYNC_LINE_RE, TARGET_LINE_RE, clean_md_field as _clean_md_field, collect_concept_artifacts, collect_path_replacements as _collect_path_replacements, compare_cli_versions as _compare_cli_versions, configure_utf8_stdio as _configure_stdio, default_architect_home, editorial_prose_sha256 as _editorial_prose_sha256, format_project_display_path as _format_project_display_path, has_install_audit as _has_install_audit, is_machine_absolute_path as _is_machine_absolute_path, load_config, parse_artifact_file as _parse_artifact_file, parse_semver_tuple as _parse_semver_tuple, read_json_safe as _read_json_safe, resolve_public_mode, resolve_workspace_root, run_readonly_cmd, sanitize_markdown_paths as _sanitize_markdown_paths, scan_md_dir as _scan_md_dir, snapshot_watches_map as _snapshot_watches_map, strip_sync_line as _strip_sync_line, strip_volatile_json as _strip_volatile_json, strip_volatile_md as _strip_volatile_md, tracked_project_keys as _tracked_project_keys, visible_installed_plugins as _visible_installed_plugins, visible_orphan_plugin_dirs as _visible_orphan_plugin_dirs, write_json_if_changed as _write_json_if_changed, write_md_if_changed as _write_md_if_changed, write_utf8 as _write_utf8)  # noqa: E402
from core.renderers import (apply_auto_doc_updates, build_ecosystem_blocks as _build_ecosystem_blocks, format_delta_for_stdout, format_dev_branch_cell as _format_dev_branch_cell, format_installed_cell as _format_installed_cell, format_installed_plugin_badge as _format_installed_plugin_badge, format_main_release_cell as _format_main_release_cell, format_project_tasks_block as _format_project_tasks_block, format_wip_cell as _format_wip_cell, persist_sync_outputs as _persist_sync_outputs, render_delta_markdown, render_ecosystem_snapshot_markdown, replace_auto_block)  # noqa: E402
from core.watches import (DEFAULT_WATCH_KEYWORDS, MD_BULLET_RE, SEPARATOR_RE, SUB_HEADING_RE, VERSION_HEADING_RE, collect_local_antigravity_env, collect_watches as _collect_watches, extract_relevant_antigravity_bullets, fetch_antigravity_changelog, fetch_url_text, normalize_watches_cfg as _normalize_watches_cfg, parse_antigravity_changelog, parse_markdown_changelog_watch, render_surface_markdown, split_top_sections as _split_top_sections)  # noqa: E402


def _raw_architect_home(architect_home: Path | None = None, *, env: dict[str, str] | None = None, home_dir: Path | None = None) -> Path:
    if architect_home is not None:
        return architect_home.expanduser()
    env_map = env if env is not None else os.environ
    for key, suffix in (("GRAVITY_ARCHITECT_HOME", None), ("GRAVITY_HOME", "architect")):
        if val := str(env_map.get(key) or "").strip():
            return (Path(val).expanduser() / suffix) if suffix else Path(val).expanduser()
    return (home_dir if home_dir is not None else safe_home_dir()).expanduser() / ".gemini" / "gravity" / "architect"


def resolve_ateliers_registry_path(architect_home: Path | None = None, env: dict[str, str] | None = None, home_dir: Path | None = None) -> Path:
    """Résout le chemin du registre centralisé `<architect_home>/ateliers.json`."""
    return (architect_home.expanduser().resolve() if architect_home is not None else default_architect_home(env=env, home_dir=home_dir)) / "ateliers.json"


def workspace_lock_path(ws_root: Path, *, architect_home: Path | None = None, env: dict[str, str] | None = None, home_dir: Path | None = None) -> Path:
    """Retourne le chemin du verrou exclusif sous `<architect_home>/locks/` (hors dépôt utilisateur)."""
    raw_home = _raw_architect_home(architect_home, env=env, home_dir=home_dir)
    if is_symlink_or_junction(raw_home) or is_symlink_or_junction(raw_home.parent):
        raise ValueError(f"Chemin Architect Home symlink/junction interdit : {raw_home}")
    arch_dir = resolve_ateliers_registry_path(architect_home, env=env, home_dir=home_dir).parent
    return arch_dir / "locks" / f"{hashlib.sha256(str(ws_root.expanduser().resolve()).encode('utf-8')).hexdigest()[:16]}.lock"


def _is_valid_atelier_dir(workspace_dir: Path) -> bool:
    try:
        return not is_symlink_or_junction(workspace_dir) and workspace_dir.is_dir() and all(not is_symlink_or_junction(workspace_dir / f) and (workspace_dir / f).is_file() for f in ("projects.json", "ECOSYSTEM.md"))
    except OSError:
        return False


def register_atelier(
    workspace_root: Path, *, workspace_name: str = "", architect_home: Path | None = None,
    env: dict[str, str] | None = None, home_dir: Path | None = None, timeout_s: float = 5.0,
) -> bool:
    """Enregistre l'atelier courant (MRU, max 20) dans `<architect_home>/ateliers.json` sous verrou exclusif."""
    env_map = env if env is not None else os.environ
    if str(env_map.get("GRAVITY_ARCHITECT_SKIP_REGISTRY") or "").strip() == "1":
        return False
    try:
        if not _is_valid_atelier_dir(ws_raw := workspace_root.expanduser()):
            return False
        ws_canon = ws_raw.resolve()
        raw_home = _raw_architect_home(architect_home, env=env_map, home_dir=home_dir)
        reg_path = resolve_ateliers_registry_path(architect_home, env=env_map, home_dir=home_dir)
        if any(is_symlink_or_junction(p) for p in (raw_home / "ateliers.json", raw_home, raw_home.parent, reg_path)) or (reg_path.exists() and not reg_path.is_file()):
            return False
        resolved_name = str(workspace_name or "").strip() or str((_read_json_safe(ws_canon / "projects.json") or {}).get("workspace_name") or "").strip()
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with exclusive_file_lock(reg_path.parent / "ateliers.lock", timeout_s=timeout_s):
            entries = [{"workspace_path": str(ws_canon), "workspace_name": resolved_name, "updated_at": now_utc}]
            seen = {os.path.normcase(str(ws_canon))}
            for item in ((_read_json_safe(reg_path) or {}).get("ateliers") or []):
                if len(entries) >= 20:
                    break
                raw_p = str(item.get("workspace_path") or "").strip() if isinstance(item, dict) else ""
                if raw_p and _is_valid_atelier_dir(cand_raw := Path(raw_p).expanduser()) and (ck := os.path.normcase(str(cand_c := cand_raw.resolve()))) not in seen:
                    seen.add(ck)
                    entries.append({"workspace_path": str(cand_c), "workspace_name": str(item.get("workspace_name") or "").strip(), "updated_at": str(item.get("updated_at") or "").strip()})
            write_json_atomic(reg_path, {"schema_version": 1, "ateliers": entries[:20]})
        return True
    except (OSError, ValueError, TypeError, TimeoutError):
        return False


def run_sync(
    config_path: Path, out_dir: Path | None = None, releases_override: int | None = None,
    offline: bool = False, save_raw: bool = False, gemini_home: Path | None = None,
    concept_root: Path | None = None, dry_run: bool = False, apply_docs: bool = True,
    ack_editorial: bool = False, public_mode: bool | None = None, max_changelog_lines: int = 45,
) -> tuple[dict, dict]:
    """Exécute la synchronisation complète et retourne `(snapshot, delta)`."""
    if max_changelog_lines < 1:
        raise ValueError("--max-changelog-lines doit être >= 1.")
    cfg = load_config(config_path)
    effective_public = resolve_public_mode(cfg) if public_mode is None else public_mode
    base_dir = config_path.resolve().parent
    resolved_concept_root = concept_root.resolve() if concept_root is not None else base_dir
    resolved_out_dir = out_dir.resolve() if out_dir is not None else (resolved_concept_root / "tracking")
    synced_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    snapshots_dir = resolved_out_dir / "snapshots"

    lock_ctx = contextlib.nullcontext() if dry_run else exclusive_file_lock(workspace_lock_path(resolved_concept_root), timeout_s=5.0)
    with lock_ctx:
        if not dry_run:
            snapshots_dir.mkdir(parents=True, exist_ok=True)
        editorial_state_path = snapshots_dir / "editorial_state.json"
        prev_snapshot, prev_delta = _read_json_safe(snapshots_dir / "ecosystem_snapshot.json"), _read_json_safe(snapshots_dir / "delta.json")
        prev_editorial_state = _load_editorial_state(editorial_state_path, prev_snapshot)
        projects_cfg, default_preset, watches_cfg = [p for p in (cfg.get("projects") or []) if isinstance(p, dict)], str(cfg.get("default_preset") or "generic").strip().lower(), _normalize_watches_cfg(cfg)
        needs_local_env = any(resolve_project_preset(p, cfg) == "antigravity-plugin" for p in projects_cfg) or any(isinstance(w.get("local_cli_check"), dict) for w in watches_cfg)
        env_data = collect_local_antigravity_env(gemini_home=gemini_home, cmd_runner=run_readonly_cmd) if needs_local_env else {"agy_path": None, "local_agy_version": None, "plugins_dir": None, "installed_plugins": [], "orphan_plugin_dirs": []}
        installed_map = {p["name"]: p for p in env_data.get("installed_plugins") or [] if p.get("name")}
        for p in env_data.get("installed_plugins") or []:
            if p.get("dir") and p["dir"] not in installed_map:
                installed_map[p["dir"]] = p

        projects_data = [collect_project_snapshot(proj, base_dir=base_dir, installed_plugins_map=installed_map, dry_run=dry_run, concept_root=resolved_concept_root, default_preset=default_preset, max_changelog_lines=max_changelog_lines, cmd_runner=run_readonly_cmd) for proj in projects_cfg]
        watches_data = _collect_watches(watches_cfg=watches_cfg, out_dir=resolved_out_dir, concept_root=resolved_concept_root, releases_override=releases_override, offline=offline, save_raw=save_raw, dry_run=dry_run, synced_at=synced_at, fetch_fn=fetch_antigravity_changelog)
        artifacts_data = collect_concept_artifacts(resolved_concept_root)
        project_ids, watch_impacts, budgets_cfg = [p["id"] for p in projects_data], [str(w["impact_file"]) for w in watches_data.values() if w.get("impact_file")], cfg.get("hot_budgets")
        full_snapshot: dict = {"schema_version": SCHEMA_VERSION, "synced_at": synced_at, "public_mode": effective_public, "environment": env_data, "projects": projects_data, "watches": watches_data, "artifacts": artifacts_data, "hot_budgets": {}}
        if "antigravity" in watches_data:
            full_snapshot["antigravity"] = watches_data["antigravity"]

        mask_pairs = _collect_path_replacements(full_snapshot, concept_root=resolved_concept_root, gemini_home=gemini_home) if effective_public else None
        delta, next_editorial_state = compute_delta_with_state(prev_snapshot, full_snapshot, resolved_concept_root, editorial_state=prev_editorial_state, ack_editorial=ack_editorial, public_mode=effective_public, replacements=mask_pairs)
        pending_gen = {"tracking/snapshots/ecosystem_snapshot.md"} if not dry_run else None

        def _merge_atelier_alerts() -> None:
            for alert in collect_atelier_hygiene_alerts(resolved_concept_root, hot_budgets={}, ignore_missing_targets=pending_gen):
                clean = _sanitize_markdown_paths(alert, replacements=mask_pairs) if effective_public else alert
                if clean not in delta["hygiene_alerts"]:
                    delta["hygiene_alerts"].append(clean)

        _append_budget_alerts(delta, evaluate_hot_budgets(resolved_concept_root, budgets_cfg, project_ids, watch_impact_files=watch_impacts))
        _merge_atelier_alerts()
        _stabilize_unchanged_timestamps(prev_snapshot, full_snapshot, prev_editorial_state, next_editorial_state, prev_delta, delta, ack_editorial=ack_editorial)

        if apply_docs:
            delta["auto_updated_files"] = apply_auto_doc_updates(resolved_concept_root, full_snapshot, delta, dry_run=dry_run, public_mode=effective_public, replacements=mask_pairs)
        post_budgets = evaluate_hot_budgets(resolved_concept_root, budgets_cfg, project_ids, watch_impact_files=watch_impacts)
        full_snapshot["hot_budgets"] = post_budgets
        before_alerts = list(delta["hygiene_alerts"])
        _append_budget_alerts(delta, post_budgets)
        if apply_docs and not dry_run:
            _merge_atelier_alerts()
        if apply_docs and not dry_run and delta["hygiene_alerts"] != before_alerts:
            for item in apply_auto_doc_updates(resolved_concept_root, full_snapshot, delta, dry_run=False, public_mode=effective_public, replacements=mask_pairs):
                if item not in delta["auto_updated_files"]:
                    delta["auto_updated_files"].append(item)

        delta_md = render_delta_markdown(delta, dry_run=dry_run, replacements=mask_pairs)
        if not dry_run:
            _persist_sync_outputs(resolved_concept_root, snapshots_dir, editorial_state_path, watches_data, full_snapshot, delta, delta_md, next_editorial_state, effective_public=effective_public, mask_pairs=mask_pairs)
    if not dry_run:
        register_atelier(resolved_concept_root, workspace_name=str(cfg.get("workspace_name") or ""))
        if ack_editorial:
            _maybe_close_gravity_metrics(resolved_concept_root, projects_data, gemini_home=gemini_home)
    return full_snapshot, delta


def _resolve_metrics_cid(store_dir: Path, workspace_name: str) -> str:
    if env_cid := str(os.environ.get("ANTIGRAVITY_CONVERSATION_ID") or "").strip():
        return env_cid
    cap_path = store_dir / "active_captures.json"
    if is_symlink_or_junction(cap_path) or not cap_path.is_file() or not isinstance(caps := (_read_json_safe(cap_path) or {}).get("captures"), dict):
        return ""
    valid = [(k.strip(), v) for k, v in caps.items() if isinstance(k, str) and k.strip() and isinstance(v, dict)]
    pool = [(k, v) for k, v in valid if str(v.get("project") or "").strip() == workspace_name] or (valid if len(valid) == 1 else [])
    return max(pool, key=lambda kv: (str(kv[1].get("updated_at") or kv[1].get("started_at") or ""), kv[0]))[0] if pool else ""


def _is_cid_sealed(store_dir: Path, cid: str) -> bool:
    hist_path = store_dir / "history.jsonl"
    if is_symlink_or_junction(hist_path) or not hist_path.is_file():
        return False
    with contextlib.suppress(OSError):
        for line in hist_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            with contextlib.suppress(ValueError):
                if line.strip() and isinstance(obj := json.loads(line), dict) and obj.get("conversation_id") == cid and str(obj.get("status") or "archived").strip().lower() == "archived":
                    return True
    return False


def _maybe_close_gravity_metrics(concept_root: Path, projects_data: list[dict], *, gemini_home: Path | None = None) -> bool:
    """Clôture best-effort silencieuse de gravity-metrics sur --ack-editorial quand le WIP est propre."""
    if any(isinstance(w := p.get("wip"), dict) and (w.get("code_wip_count", 0) > 0 or (w.get("is_dirty") and not w.get("runtime_only_wip"))) for p in projects_data if isinstance(p, dict)):
        return False
    g_home = gemini_home if gemini_home is not None else (safe_home_dir() / ".gemini")
    cli_path = g_home / "config" / "plugins" / "gravity-metrics" / "scripts" / "cli.py"
    if is_symlink_or_junction(cli_path) or not cli_path.is_file():
        return False
    env_mh = str(os.environ.get("GRAVITY_METRICS_HOME") or "").strip()
    env_gh = str(os.environ.get("GRAVITY_HOME") or "").strip() if gemini_home is None else ""
    store_dir = Path(env_mh).expanduser() if env_mh else (Path(env_gh).expanduser() / "metrics" if env_gh else (g_home / "gravity" / "metrics"))
    if not (cid := _resolve_metrics_cid(store_dir, concept_root.name)):
        return False
    cmd = [sys.executable, "-B", str(cli_path), "archive", cid, "--workspace", str(concept_root)]
    if _is_cid_sealed(store_dir, cid):
        cmd.append("--update-sealed")
    with contextlib.suppress(OSError, subprocess.SubprocessError, ValueError):
        return subprocess.run(cmd, shell=False, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10, check=False).returncode == 0
    return False


def build_parser() -> argparse.ArgumentParser:
    """Construit le parseur CLI pour `sync_tracking.py`."""
    p = argparse.ArgumentParser(description="Synchronise en lecture seule les dépôts d'un atelier Gravity Architect.")
    for flags, kw in (
        (("--workspace",), {"type": Path, "default": None, "help": "Racine de l'atelier"}), (("--config",), {"type": Path, "default": None, "help": "Chemin vers projects.json"}),
        (("--out-dir",), {"type": Path, "default": None, "help": "Répertoire tracking/"}), (("--concept-root",), {"type": Path, "default": None, "help": "Racine de l'atelier"}),
        (("--releases",), {"type": int, "default": None, "help": "Releases par veille"}), (("--offline", "--skip-antigravity"), {"dest": "offline", "action": "store_true", "help": "Ignore la veille réseau"}),
        (("--save-raw",), {"action": "store_true", "help": "Enregistre raw/changelog.md"}), (("--check", "--dry-run"), {"dest": "dry_run", "action": "store_true", "help": "Dry-run sans écriture"}),
        (("--no-apply-docs",), {"action": "store_true", "help": "Désactive les blocs AUTO"}), (("--ack-editorial",), {"action": "store_true", "help": "Acquitte les cibles éditoriales"}),
        (("--print-delta",), {"action": "store_true", "help": "Affiche delta Markdown"}), (("--max-stdout-bytes",), {"type": int, "default": 8192, "help": "Seuil stdout --print-delta"}),
        (("--max-changelog-lines",), {"type": int, "default": 45, "help": "Lignes max CHANGELOG.md"}),
    ):
        p.add_argument(*flags, **kw)
    return p


def main(argv: list[str] | None = None) -> int:
    """Point d'entrée CLI."""
    _configure_stdio()
    args = build_parser().parse_args(argv)
    try:
        if args.max_stdout_bytes < 0: raise ValueError("--max-stdout-bytes doit être >= 0.")
        detected_root, config_path = resolve_workspace_root(config_arg=args.config, workspace_arg=args.workspace)
        concept_root = args.concept_root if args.concept_root is not None else detected_root
        out_dir = args.out_dir if args.out_dir is not None else (concept_root / "tracking")
        snapshot, delta = run_sync(config_path=config_path, out_dir=out_dir, releases_override=args.releases, offline=args.offline, save_raw=args.save_raw, concept_root=concept_root, dry_run=args.dry_run, apply_docs=not args.no_apply_docs, ack_editorial=args.ack_editorial, max_changelog_lines=args.max_changelog_lines)
    except (OSError, json.JSONDecodeError, ValueError, KeyError, TimeoutError) as exc:
        print(f"[erreur] Synchronisation impossible : {exc}", file=sys.stderr)
        return 1
    if args.print_delta:
        masks = _collect_path_replacements(snapshot, concept_root=concept_root) if snapshot.get("public_mode") else None
        out_snap = out_dir.resolve() / "snapshots" / "delta.md"
        rel = out_snap.relative_to(concept_root.resolve()).as_posix() if out_snap.is_relative_to(concept_root.resolve()) else "tracking/snapshots/delta.md"
        sys.stdout.write(format_delta_for_stdout(delta, render_delta_markdown(delta, dry_run=args.dry_run, replacements=masks), max_stdout_bytes=args.max_stdout_bytes, dry_run=args.dry_run, delta_rel_path=rel, replacements=masks))
    else:
        print(f"{'[dry-run] ' if args.dry_run else ''}Synchronisation terminée ({snapshot['synced_at']}) — {len(snapshot['projects'])} projet(s), veilles: {delta.get('fetch_status')}, éditorial: {'requis' if delta['needs_editorial_update'] else 'à jour'}.")
    return 0
if __name__ == "__main__": raise SystemExit(main())
