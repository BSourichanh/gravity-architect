"""Calcul du delta éditorial Hot/Cold, gestion de `editorial_state.json` et budgets tokens."""

from __future__ import annotations

import difflib
import json
from pathlib import Path

from core.io_utils import (
    DEFAULT_HOT_BUDGETS,
    SCHEMA_VERSION,
    collect_path_replacements,
    compare_cli_versions,
    editorial_prose_sha256,
    has_install_audit,
    resolve_public_mode,
    sanitize_markdown_paths,
    snapshot_watches_map,
    strip_volatile_json,
    visible_orphan_plugin_dirs,
)


def compute_unified_diff(
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


def build_acked_project_entry(proj: dict) -> dict:
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


def build_acked_surface_entry(info: dict) -> dict:
    """Construit la baseline éditoriale acquittée pour une surface de veille."""
    return {"versions": list(info.get("versions") or [])}


def editorial_state_from_snapshot(snapshot: dict | None) -> dict | None:
    """Dérive une baseline éditoriale depuis un snapshot existant (migration v3/v4 -> v5)."""
    if not isinstance(snapshot, dict):
        return None
    projects_map: dict[str, dict] = {}
    for proj in snapshot.get("projects") or []:
        if isinstance(proj, dict) and proj.get("id"):
            projects_map[str(proj["id"])] = build_acked_project_entry(proj)

    watches_map: dict[str, dict] = {}
    for wid, winfo in snapshot_watches_map(snapshot).items():
        if not isinstance(winfo, dict):
            continue
        watches_map[str(wid)] = {
            slug: build_acked_surface_entry(sinfo)
            for slug, sinfo in (winfo.get("surfaces") or {}).items()
            if isinstance(sinfo, dict)
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "acked_at": snapshot.get("synced_at"),
        "projects": projects_map,
        "watches": watches_map,
        "pending_editorial": {},
    }


def load_editorial_state(state_path: Path, prev_snapshot: dict | None) -> dict | None:
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
    return editorial_state_from_snapshot(prev_snapshot)


def collect_project_hygiene_alerts(proj: dict, curr_branch: str | None) -> list[str]:
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
        m_ref = branches.get("main_latest_tag") or branches.get("main_tag") or branches.get("main_head") or "?"
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
        alerts.append(f"`{pid}` : dernier tag release `{latest_tag}` absent de `{branches['main_branch']}`.")

    post_tag = branches.get("commits_since_latest_tag", 0)
    if post_tag > 0 and latest_tag:
        unrel_note = " (`[Unreleased]`)" if stable.get("unreleased_has_content") else ""
        alerts.append(
            f"`{pid}` : {post_tag} commit(s) non tagué(s) sur `{branches['dev_branch']}` "
            f"après `{latest_tag}`{unrel_note}."
        )
    if curr_ver and latest_tag and curr_ver.lstrip("v") != latest_tag.lstrip("v"):
        alerts.append(f"`{pid}` : version (`{curr_ver}`) ≠ dernier tag (`{latest_tag}`).")

    rel_chg_ver = stable.get("latest_released_changelog_version")
    if curr_ver and rel_chg_ver and curr_ver.lstrip("v") != rel_chg_ver.lstrip("v"):
        alerts.append(f"`{pid}` : version (`{curr_ver}`) ≠ dernière release CHANGELOG (`{rel_chg_ver}`).")

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
        alerts.append(f"`{pid}` : {wip['code_wip_count']} fichier(s) de code en WIP non commité sur `{curr_branch or '?'}`.")
    if not comp.get("ok") and comp.get("issues"):
        alerts.append(f"`{pid}` : conformité dépôt — {'; '.join(comp['issues'])}.")
    return alerts


def _compute_single_project_delta(
    proj: dict,
    prev_snap: dict | None,
    prev_base: dict | None,
    pending_entry: dict | None,
    concept_root: Path,
    ack_editorial: bool,
) -> tuple[dict, str | None, dict | None, dict | None]:
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

    if prev_snap is None:
        head_changed = bool(curr_head)
        branch_changed = False
        wip_changed = bool(wip.get("code_wip_count", 0) > 0)
    else:
        prev_wip = prev_snap.get("wip") or {}
        head_changed = curr_head != prev_wip.get("head")
        branch_changed = curr_branch != prev_wip.get("branch")
        wip_changed = curr_wip_pairs != sorted((f["status"], f["path"]) for f in prev_wip.get("files") or [])

    curr_prose_sha = editorial_prose_sha256(concept_root / card_rel)
    auto_acked_prose = bool(
        pending_entry is not None and curr_prose_sha != pending_entry.get("prose_sha256_at_trigger")
    )
    is_acked = ack_editorial or auto_acked_prose

    if is_acked:
        new_tags, manifest_changed, main_tag_changed, main_manifest_changed = [], False, False, False
        changelog_changed, agents_changed, agents_diff, missing_card_flag = False, False, [], False
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
        main_tag_changed = bool(prev_main_tag is not None and curr_main_tag != prev_main_tag)
        prev_main_ver = prev_base.get("main_plugin_version")
        main_manifest_changed = bool(prev_main_ver is not None and curr_main_ver != prev_main_ver)

        prev_chg_sha = prev_base.get("changelog_sha256")
        changelog_changed = bool(new_tags or manifest_changed) if prev_chg_sha is None else (curr_chg_sha != prev_chg_sha)

        prev_agents_sha = prev_base.get("agents_md_sha256")
        if prev_agents_sha is None:
            agents_changed, agents_diff = False, []
        else:
            agents_changed = curr_agents_sha != prev_agents_sha
            agents_diff = (
                compute_unified_diff(list(prev_base.get("agents_md_lines") or []), list(stable.get("agents_md_lines") or []), pid)
                if agents_changed
                else []
            )
        missing_card_flag = missing_card

    needs_card = proj["exists"] and any(
        (new_tags, manifest_changed, main_tag_changed, main_manifest_changed, changelog_changed, agents_changed, missing_card_flag)
    )
    pending_out: dict | None = None
    next_base_out: dict | None = None
    target_out: str | None = None
    if needs_card:
        target_out = card_rel
        trig_sha = pending_entry["prose_sha256_at_trigger"] if pending_entry is not None else curr_prose_sha
        pending_out = {"prose_sha256_at_trigger": trig_sha}
        if prev_base is not None:
            next_base_out = prev_base
    elif proj["exists"]:
        next_base_out = build_acked_project_entry(proj)

    delta_entry = {
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
        "install_content_diff_files": list(stable.get("install_content_diff_files") or []),
        "head_changed": head_changed,
        "branch_changed": branch_changed,
        "changelog_changed": changelog_changed,
        "latest_changelog_excerpt": stable.get("latest_changelog_excerpt", "") if changelog_changed else "",
        "agents_md_changed": agents_changed,
        "agents_md_diff": agents_diff,
        "wip_changed": wip_changed,
        "code_wip_count": wip.get("code_wip_count", 0),
        "runtime_only_wip": bool(wip.get("runtime_only_wip")),
        "branch_drift": bool(branches.get("branch_drift")),
        "compliance": comp,
        "missing_project_card": missing_card_flag,
    }
    return delta_entry, target_out, pending_out, next_base_out


def _compute_single_watch_delta(
    wid: str,
    winfo: dict,
    base_state: dict | None,
    base_w_surfaces: dict,
    pending_w: dict | None,
    concept_root: Path,
    ack_editorial: bool,
    env: dict,
) -> tuple[dict, dict, str | None, dict | None, bool, str | None]:
    impact_rel = str(winfo.get("impact_file") or "")
    curr_imp_prose = editorial_prose_sha256(concept_root / impact_rel) if impact_rel else None
    auto_acked_w = bool(pending_w is not None and curr_imp_prose != pending_w.get("prose_sha256_at_trigger"))
    w_acked = ack_editorial or auto_acked_w
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
                {"version": v, "title": titles.get(v, ""), "digest": digests.get(v, [])}
                for v in new_releases
            ],
        }
        if new_releases:
            any_new = True

    missing_impact = bool(impact_rel and winfo.get("fetch_status") == "ok" and not (concept_root / impact_rel).is_file())
    target_out: str | None = None
    pending_out: dict | None = None
    if impact_rel and not w_acked and (any_new or missing_impact):
        target_out = impact_rel
        trig_w_sha = pending_w["prose_sha256_at_trigger"] if pending_w is not None else curr_imp_prose
        pending_out = {"prose_sha256_at_trigger": trig_w_sha}
        for slug in winfo.get("surfaces") or {}:
            if slug in base_w_surfaces:
                next_w_surfaces[slug] = base_w_surfaces[slug]
    else:
        for slug, sinfo in (winfo.get("surfaces") or {}).items():
            next_w_surfaces[slug] = build_acked_surface_entry(sinfo)

    cli_alert: str | None = None
    cli_check = winfo.get("local_cli_check")
    if isinstance(cli_check, dict):
        cmd_name = str(cli_check.get("cmd") or "agy")
        surf_slug = str(cli_check.get("surface_slug") or "cli")
        local_cli_ver = env.get("local_agy_version") if cmd_name == "agy" else None
        surf_latest = ((winfo.get("surfaces") or {}).get(surf_slug) or {}).get("latest_version")
        if local_cli_ver and surf_latest and compare_cli_versions(str(local_cli_ver), str(surf_latest)) == "behind":
            cli_alert = f"`{cmd_name}` local (`{local_cli_ver}`) en retrait par rapport à {winfo.get('name', wid)} CLI (`{surf_latest}`)."

    wdelta = {
        "id": wid,
        "name": winfo.get("name", wid),
        "fetch_status": winfo.get("fetch_status"),
        "surfaces": w_surf_deltas,
    }
    return wdelta, next_w_surfaces, target_out, pending_out, auto_acked_w, cli_alert


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
    effective_public = resolve_public_mode(curr_snapshot) if public_mode is None else public_mode
    prev_projects_wip = {
        str(p["id"]): p
        for p in (prev_snapshot.get("projects", []) if isinstance(prev_snapshot, dict) else [])
        if isinstance(p, dict) and p.get("id")
    }

    base_state = editorial_state if editorial_state is not None else editorial_state_from_snapshot(prev_snapshot)
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
        card_rel = f"tracking/projects/{pid}.md"
        p_delta, target_rel, pending_obj, next_base = _compute_single_project_delta(
            proj,
            prev_projects_wip.get(pid),
            base_projects.get(pid),
            base_pending.get(card_rel),
            concept_root,
            ack_editorial,
        )
        project_deltas[pid] = p_delta
        if target_rel and target_rel not in editorial_targets:
            editorial_targets.append(target_rel)
        if pending_obj is not None:
            next_pending[card_rel] = pending_obj
        if next_base is not None:
            next_projects[pid] = next_base
        if proj["exists"]:
            hygiene_alerts.extend(collect_project_hygiene_alerts(proj, (proj.get("wip") or {}).get("branch")))

    watches_curr = snapshot_watches_map(curr_snapshot)
    watch_deltas: dict[str, dict] = {}
    any_watch_auto_acked = False
    env = curr_snapshot.get("environment") or {}

    for wid, winfo in watches_curr.items():
        impact_rel = str(winfo.get("impact_file") or "")
        wdelta, next_w_surfaces, w_target, w_pending, auto_ack_w, cli_alert = _compute_single_watch_delta(
            wid,
            winfo,
            base_state,
            base_watches.get(wid) or {},
            base_pending.get(impact_rel) if impact_rel else None,
            concept_root,
            ack_editorial,
            env,
        )
        if auto_ack_w:
            any_watch_auto_acked = True
        next_watches[wid] = next_w_surfaces
        watch_deltas[wid] = wdelta
        if w_target and w_target not in editorial_targets:
            editorial_targets.append(w_target)
        if impact_rel and w_pending is not None:
            next_pending[impact_rel] = w_pending
        if cli_alert:
            hygiene_alerts.append(cli_alert)

    if has_install_audit(curr_snapshot):
        orphan_dirs = visible_orphan_plugin_dirs(curr_snapshot, effective_public)
        if orphan_dirs:
            hygiene_alerts.append(
                f"Plugins locaux : dossier(s) sans `plugin.json` ({', '.join(f'`{d}`' for d in orphan_dirs)})."
            )

    if effective_public:
        mask_pairs = replacements if replacements is not None else collect_path_replacements(curr_snapshot, concept_root=concept_root)
        hygiene_alerts = [sanitize_markdown_paths(alert, replacements=mask_pairs) for alert in hygiene_alerts]

    ag_watch = watch_deltas.get("antigravity") or {}
    fetch_status_summary = (
        ag_watch.get("fetch_status")
        if ag_watch
        else (next(iter(watch_deltas.values())).get("fetch_status") if watch_deltas else "none")
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
        "artifacts": curr_snapshot.get("artifacts") or {},
    }

    any_project_auto_acked = any(
        base_pending.get(f"tracking/projects/{p['id']}.md") is not None
        and editorial_prose_sha256(concept_root / f"tracking/projects/{p['id']}.md")
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
            report[rel_path] = {"bytes": size, "budget": limit, "over_budget": size > limit}

    card_limit = int(merged.get("project_card_max_bytes", 3500))
    for pid in project_ids:
        rel_path = f"tracking/projects/{pid}.md"
        fpath = concept_root / rel_path
        if fpath.is_file():
            size = fpath.stat().st_size
            report[rel_path] = {"bytes": size, "budget": card_limit, "over_budget": size > card_limit}
    return report


def append_budget_alerts(delta: dict, hot_budgets: dict[str, dict]) -> None:
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


def stabilize_unchanged_timestamps(
    prev_snapshot: dict | None,
    full_snapshot: dict,
    prev_editorial_state: dict | None,
    next_editorial_state: dict,
    prev_delta: dict | None,
    delta: dict,
    *,
    ack_editorial: bool,
) -> None:
    """Préserve les horodatages précédents lorsque rien n'a changé (0 churn disque)."""
    if prev_snapshot is None or ack_editorial:
        return
    prev_no_budgets = {k: v for k, v in prev_snapshot.items() if k != "hot_budgets"}
    curr_no_budgets = {k: v for k, v in full_snapshot.items() if k != "hot_budgets"}
    same_snapshot = strip_volatile_json(prev_no_budgets) == strip_volatile_json(curr_no_budgets)
    same_state = (
        prev_editorial_state is not None
        and strip_volatile_json(prev_editorial_state) == strip_volatile_json(next_editorial_state)
    )
    same_delta_core = (
        isinstance(prev_delta, dict)
        and prev_delta.get("hygiene_alerts") == delta.get("hygiene_alerts")
        and prev_delta.get("editorial_targets") == delta.get("editorial_targets")
    )
    if same_snapshot and same_state and same_delta_core:
        stable_ts = prev_snapshot.get("synced_at") or full_snapshot["synced_at"]
        full_snapshot["synced_at"] = stable_ts
        for wobj in full_snapshot["watches"].values():
            wobj["synced_at"] = stable_ts
        delta["synced_at"] = stable_ts
        if prev_editorial_state and prev_editorial_state.get("acked_at"):
            next_editorial_state["acked_at"] = prev_editorial_state["acked_at"]
