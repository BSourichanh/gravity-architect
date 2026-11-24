#!/usr/bin/env python3
"""Moteur générique de collecte lecture seule, delta éditorial et suivi Hot/Cold (façade)."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil  # noqa: F401 - conservé pour compatibilité tests/patches
import sys

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from core.delta import (  # noqa: E402
    append_budget_alerts as _append_budget_alerts, build_acked_project_entry as _build_acked_project_entry,
    build_acked_surface_entry as _build_acked_surface_entry, collect_project_hygiene_alerts as _collect_project_hygiene_alerts,
    compute_delta, compute_delta_with_state, compute_unified_diff as _compute_unified_diff,
    editorial_state_from_snapshot as _editorial_state_from_snapshot, evaluate_hot_budgets,
    load_editorial_state as _load_editorial_state, stabilize_unchanged_timestamps as _stabilize_unchanged_timestamps,
)
from core.discovery import (  # noqa: E402
    REQUIRED_OFFICIAL_PLUGIN_FIELDS, check_agents_doc as _check_agents_doc,
    derive_validator_script, detect_plugin_manifest, detect_version_source,
    evaluate_antigravity_plugin_compliance as _evaluate_antigravity_plugin_compliance,
    evaluate_project_compliance, resolve_project_preset,
)
from core.git_collector import (  # noqa: E402
    INSTALL_ADAPTED_FILENAMES, INSTALL_IGNORED_DIRS, INSTALL_IGNORED_SUFFIXES,
    classify_porcelain_status as _classify_porcelain_status, collect_plugin_tree_hashes as _collect_plugin_tree_hashes,
    collect_project_snapshot, compare_plugin_dirs, extract_latest_changelog_section,
    extract_toml_section_value as _extract_toml_section_value, git_branch_short_rev as _git_branch_short_rev,
    git_commits_ahead as _git_commits_ahead, git_is_ancestor as _git_is_ancestor, git_show_text as _git_show_text,
    is_runtime_ignored_path as _is_runtime_ignored_path, parse_porcelain_lines as _parse_porcelain_lines,
    parse_version_from_text, read_version_from_ref as _read_version_from_ref,
)
from core.io_utils import (  # noqa: E402
    AUTO_BLOCK_RE, AUTO_DISCOVER_SKIP_DIRS, CHANGELOG_SECTION_RE, DATE_LINE_RE, DEFAULT_HOT_BUDGETS,
    MACHINE_ABS_PATH_RE, MD_H1_RE, SCHEMA_VERSION, SECTION_RE, SEMVER_RE, STATUS_LINE_RE, SYNC_LINE_RE, TARGET_LINE_RE,
    clean_md_field as _clean_md_field, collect_concept_artifacts, collect_path_replacements as _collect_path_replacements,
    compare_cli_versions as _compare_cli_versions, configure_utf8_stdio as _configure_utf8_stdio, default_architect_home,
    editorial_prose_sha256 as _editorial_prose_sha256, format_project_display_path as _format_project_display_path,
    has_install_audit as _has_install_audit, is_machine_absolute_path as _is_machine_absolute_path, load_config,
    parse_artifact_file as _parse_artifact_file, parse_semver_tuple as _parse_semver_tuple,
    read_json_safe as _read_json_safe, register_atelier, resolve_public_mode, resolve_workspace_root, run_readonly_cmd,
    sanitize_markdown_paths as _sanitize_markdown_paths, scan_md_dir as _scan_md_dir,
    snapshot_watches_map as _snapshot_watches_map, strip_sync_line as _strip_sync_line,
    strip_volatile_json as _strip_volatile_json, strip_volatile_md as _strip_volatile_md,
    tracked_project_keys as _tracked_project_keys, visible_installed_plugins as _visible_installed_plugins,
    visible_orphan_plugin_dirs as _visible_orphan_plugin_dirs, write_json_if_changed as _write_json_if_changed,
    write_md_if_changed as _write_md_if_changed, write_utf8 as _write_utf8,
)
from core.renderers import (  # noqa: E402
    apply_auto_doc_updates, build_ecosystem_blocks as _build_ecosystem_blocks, format_delta_for_stdout,
    format_dev_branch_cell as _format_dev_branch_cell, format_installed_cell as _format_installed_cell,
    format_installed_plugin_badge as _format_installed_plugin_badge, format_main_release_cell as _format_main_release_cell,
    format_project_handoffs_block as _format_project_handoffs_block, format_wip_cell as _format_wip_cell,
    persist_sync_outputs as _persist_sync_outputs, render_delta_markdown, render_ecosystem_snapshot_markdown,
    replace_auto_block,
)
from core.watches import (  # noqa: E402
    DEFAULT_WATCH_KEYWORDS, MD_BULLET_RE, SEPARATOR_RE, SUB_HEADING_RE, VERSION_HEADING_RE,
    collect_local_antigravity_env, collect_watches as _collect_watches, extract_relevant_antigravity_bullets,
    fetch_antigravity_changelog, fetch_url_text, normalize_watches_cfg as _normalize_watches_cfg,
    parse_antigravity_changelog, parse_markdown_changelog_watch, render_surface_markdown,
    split_top_sections as _split_top_sections,
)


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

    changelogs_dir, snapshots_dir = resolved_concept_root / "archives" / "changelogs", resolved_out_dir / "snapshots"
    if not dry_run:
        changelogs_dir.mkdir(parents=True, exist_ok=True)
        snapshots_dir.mkdir(parents=True, exist_ok=True)

    prev_snapshot = _read_json_safe(snapshots_dir / "ecosystem_snapshot.json")
    editorial_state_path = snapshots_dir / "editorial_state.json"
    prev_editorial_state = _load_editorial_state(editorial_state_path, prev_snapshot)
    prev_delta = _read_json_safe(snapshots_dir / "delta.json")

    projects_cfg = [p for p in (cfg.get("projects") or []) if isinstance(p, dict)]
    default_preset = str(cfg.get("default_preset") or "generic").strip().lower()
    watches_cfg = _normalize_watches_cfg(cfg)

    needs_local_env = any(resolve_project_preset(p, cfg) == "antigravity-plugin" for p in projects_cfg) or any(
        isinstance(w.get("local_cli_check"), dict) for w in watches_cfg
    )
    env_data = (
        collect_local_antigravity_env(gemini_home=gemini_home, cmd_runner=run_readonly_cmd)
        if needs_local_env
        else {"agy_path": None, "local_agy_version": None, "plugins_dir": None, "installed_plugins": [], "orphan_plugin_dirs": []}
    )
    installed_map = {p["name"]: p for p in env_data.get("installed_plugins") or [] if p.get("name")}
    for p in env_data.get("installed_plugins") or []:
        if p.get("dir") and p["dir"] not in installed_map:
            installed_map[p["dir"]] = p

    projects_data = [
        collect_project_snapshot(
            proj, base_dir=base_dir, changelogs_dir=changelogs_dir, installed_plugins_map=installed_map,
            dry_run=dry_run, concept_root=resolved_concept_root, default_preset=default_preset,
            max_changelog_lines=max_changelog_lines, cmd_runner=run_readonly_cmd,
        )
        for proj in projects_cfg
    ]
    watches_data = _collect_watches(
        watches_cfg=watches_cfg, out_dir=resolved_out_dir, concept_root=resolved_concept_root,
        releases_override=releases_override, offline=offline, save_raw=save_raw,
        dry_run=dry_run, synced_at=synced_at, fetch_fn=fetch_antigravity_changelog,
    )
    artifacts_data = collect_concept_artifacts(resolved_concept_root)
    project_ids = [p["id"] for p in projects_data]
    watch_impacts = [str(w["impact_file"]) for w in watches_data.values() if w.get("impact_file")]
    budgets_cfg = cfg.get("hot_budgets")

    full_snapshot: dict = {
        "schema_version": SCHEMA_VERSION, "synced_at": synced_at, "public_mode": effective_public,
        "environment": env_data, "projects": projects_data, "watches": watches_data,
        "artifacts": artifacts_data, "hot_budgets": {},
    }
    if "antigravity" in watches_data:
        full_snapshot["antigravity"] = watches_data["antigravity"]

    mask_pairs = _collect_path_replacements(full_snapshot, concept_root=resolved_concept_root, gemini_home=gemini_home) if effective_public else None
    delta, next_editorial_state = compute_delta_with_state(
        prev_snapshot, full_snapshot, resolved_concept_root, editorial_state=prev_editorial_state,
        ack_editorial=ack_editorial, public_mode=effective_public, replacements=mask_pairs,
    )
    _append_budget_alerts(delta, evaluate_hot_budgets(resolved_concept_root, budgets_cfg, project_ids, watch_impact_files=watch_impacts))
    _stabilize_unchanged_timestamps(
        prev_snapshot, full_snapshot, prev_editorial_state, next_editorial_state, prev_delta, delta, ack_editorial=ack_editorial
    )

    if apply_docs:
        delta["auto_updated_files"] = apply_auto_doc_updates(
            resolved_concept_root, full_snapshot, delta, dry_run=dry_run, public_mode=effective_public, replacements=mask_pairs
        )

    post_budgets = evaluate_hot_budgets(resolved_concept_root, budgets_cfg, project_ids, watch_impact_files=watch_impacts)
    full_snapshot["hot_budgets"] = post_budgets
    before_alerts = list(delta["hygiene_alerts"])
    _append_budget_alerts(delta, post_budgets)
    if apply_docs and not dry_run and delta["hygiene_alerts"] != before_alerts:
        for item in apply_auto_doc_updates(
            resolved_concept_root, full_snapshot, delta, dry_run=False, public_mode=effective_public, replacements=mask_pairs
        ):
            if item not in delta["auto_updated_files"]:
                delta["auto_updated_files"].append(item)

    delta_md = render_delta_markdown(delta, dry_run=dry_run, replacements=mask_pairs)
    if not dry_run:
        _persist_sync_outputs(
            resolved_concept_root, snapshots_dir, editorial_state_path, watches_data,
            full_snapshot, delta, delta_md, next_editorial_state, effective_public=effective_public, mask_pairs=mask_pairs,
        )
        register_atelier(resolved_concept_root, workspace_name=str(cfg.get("workspace_name") or ""))
    return full_snapshot, delta


def build_parser() -> argparse.ArgumentParser:
    """Construit le parseur CLI pour `sync_tracking.py`."""
    parser = argparse.ArgumentParser(description="Synchronise en lecture seule les dépôts d'un atelier Gravity Architect.")
    parser.add_argument("--workspace", type=Path, default=None, help="Racine de l'atelier (détectée automatiquement par défaut via ./projects.json ou sous-dossier unique)")
    parser.add_argument("--config", type=Path, default=None, help="Chemin explicite vers projects.json")
    parser.add_argument("--out-dir", type=Path, default=None, help="Répertoire de sortie tracking/ (défaut : <atelier>/tracking)")
    parser.add_argument("--concept-root", type=Path, default=None, help="Racine de l'atelier de conception (défaut : répertoire parent de projects.json)")
    parser.add_argument("--releases", type=int, default=None, help="Nombre de releases à extraire par veille")
    parser.add_argument("--offline", "--skip-antigravity", dest="offline", action="store_true", help="Ignore la récupération réseau des veilles configurées")
    parser.add_argument("--save-raw", action="store_true", help="Enregistre la copie brute complète des veilles dans <watch>/raw/changelog.md")
    parser.add_argument("--check", "--dry-run", dest="dry_run", action="store_true", help="Collecte et calcule le delta sans écrire sur disque")
    parser.add_argument("--no-apply-docs", action="store_true", help="Désactive la mise à jour des blocs <!-- AUTO:START/END -->")
    parser.add_argument("--ack-editorial", action="store_true", help="Acquitte explicitement les cibles éditoriales après édition des fiches")
    parser.add_argument("--print-delta", action="store_true", help="Affiche le delta Markdown compact sur stdout")
    parser.add_argument("--max-stdout-bytes", type=int, default=8192, help="Seuil maximal en octets sur stdout pour --print-delta (défaut : 8192, 0 = illimité)")
    parser.add_argument("--max-changelog-lines", type=int, default=45, help="Nombre maximal de lignes par extrait CHANGELOG.md (défaut : 45)")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Point d'entrée CLI."""
    _configure_utf8_stdio()
    args = build_parser().parse_args(argv)
    try:
        if args.max_stdout_bytes < 0:
            raise ValueError("--max-stdout-bytes doit être >= 0.")
        detected_root, config_path = resolve_workspace_root(config_arg=args.config, workspace_arg=args.workspace)
        concept_root = args.concept_root if args.concept_root is not None else detected_root
        out_dir = args.out_dir if args.out_dir is not None else (concept_root / "tracking")
        snapshot, delta = run_sync(
            config_path=config_path, out_dir=out_dir, releases_override=args.releases,
            offline=args.offline, save_raw=args.save_raw, concept_root=concept_root,
            dry_run=args.dry_run, apply_docs=not args.no_apply_docs,
            ack_editorial=args.ack_editorial, max_changelog_lines=args.max_changelog_lines,
        )
    except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
        print(f"[erreur] Synchronisation impossible : {exc}", file=sys.stderr)
        return 1

    if args.print_delta:
        delta_masks = _collect_path_replacements(snapshot, concept_root=concept_root) if snapshot.get("public_mode") else None
        delta_md = render_delta_markdown(delta, dry_run=args.dry_run, replacements=delta_masks)
        try:
            delta_rel = (out_dir.resolve() / "snapshots" / "delta.md").relative_to(concept_root.resolve()).as_posix()
        except ValueError:
            delta_rel = "tracking/snapshots/delta.md"
        sys.stdout.write(
            format_delta_for_stdout(
                delta, delta_md, max_stdout_bytes=args.max_stdout_bytes,
                dry_run=args.dry_run, delta_rel_path=delta_rel, replacements=delta_masks,
            )
        )
    else:
        prefix = "[dry-run] " if args.dry_run else ""
        print(
            f"{prefix}Synchronisation terminée ({snapshot['synced_at']}) — "
            f"{len(snapshot['projects'])} projet(s), veilles: {delta.get('fetch_status')}, "
            f"éditorial: {'requis' if delta['needs_editorial_update'] else 'à jour'}."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
