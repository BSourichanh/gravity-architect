"""Rendu Markdown des snapshots/deltas et mise à jour des blocs `<!-- AUTO:START/END -->`."""

from __future__ import annotations

from pathlib import Path
import posixpath
import re
import sys

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from _shared.atomic_io import write_text_atomic  # noqa: E402
from core.io_utils import (  # noqa: E402
    collect_path_replacements, compare_cli_versions, format_project_display_path,
    has_install_audit, resolve_public_mode, sanitize_markdown_paths, snapshot_watches_map,
    visible_installed_plugins, visible_orphan_plugin_dirs, write_json_if_changed,
    write_md_if_changed,
)


def format_installed_plugin_badge(plugin_info: dict) -> str:
    """Formate un badge plugin installé en indiquant s'il est désactivé."""
    ver = plugin_info.get("version") or "?"
    suffix = " *(désactivé)*" if plugin_info.get("enabled") is False else ""
    return f"`{plugin_info['name']}@{ver}`{suffix}"


def _format_installed_summary(snapshot: dict, effective_public: bool) -> str:
    installed = visible_installed_plugins(snapshot, effective_public)
    return ", ".join(format_installed_plugin_badge(p) for p in installed) if installed else "aucun"


def format_main_release_cell(proj: dict) -> str:
    """Formate la cellule `Release (main)` d'un projet."""
    if not proj["exists"]:
        return "Dépôt absent"
    stable = proj["stable"]
    branches = stable.get("branches") or {}
    main_tag, main_head, main_ver = (
        branches.get("main_latest_tag") or branches.get("main_tag"),
        branches.get("main_head"),
        branches.get("main_plugin_version"),
    )
    if main_tag and main_head:
        ver_note = f" *(manifest `{main_ver}`)*" if main_ver and main_ver != main_tag.lstrip("v") else ""
        return f"`{main_tag}` (`{main_head}`){ver_note}"
    if main_head:
        return f"`{main_ver or 'n/a'}` (`{main_head}`)"
    tag = stable.get("latest_tag") or stable.get("version") or "n/a"
    return f"`{tag}` (`{(proj.get('wip') or {}).get('head') or '?'}`)"


def format_dev_branch_cell(proj: dict) -> str:
    """Formate la cellule `Branche dev` (version + avance `main` + post-tag)."""
    if not proj["exists"]:
        return "—"
    stable = proj["stable"]
    branches = stable.get("branches") or {}
    dev_ver = branches.get("dev_plugin_version") or stable.get("version") or "n/a"
    main_b, latest_tag = branches.get("main_branch") or "main", stable.get("latest_tag")
    adv, post = branches.get("dev_ahead_of_main", 0), branches.get("commits_since_latest_tag", 0)
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


def format_installed_cell(proj: dict) -> str:
    """Formate la cellule `Installé local` (version + contenu + état activé)."""
    stable = proj["stable"]
    inst = stable.get("installed_version")
    if not inst:
        return "Non installé"
    flags: list[str] = []
    if stable.get("install_drift"):
        flags.append(f"≠ `{stable.get('version') or '?'}`")
    elif stable.get("install_content_drift"):
        flags.append(f"contenu ≠ ({len(stable.get('install_content_diff_files') or [])} f.)")
    else:
        flags.append("aligné")
    if stable.get("installed_enabled") is False:
        flags.append("désactivé")
    return f"`{inst}` *({', '.join(flags)})*"


def format_wip_cell(proj: dict) -> str:
    """Formate la cellule synthétique WIP pour la table `ECOSYSTEM.md`."""
    if not proj["exists"]:
        return "**Absent**"
    wip = proj["wip"]
    code_cnt = wip.get("code_wip_count", 0)
    if code_cnt == 0 and wip.get("runtime_only_wip"):
        return "**Propre** (`?? .agents/`)"
    return "**Propre**" if code_cnt == 0 else f"**{code_cnt} WIP** (`{wip.get('branch') or '?'}`)"


def _is_project_delta_changed(pd: dict) -> bool:
    return bool(
        pd.get("new_tags") or pd.get("manifest_version_changed") or pd.get("changelog_changed")
        or pd.get("agents_md_changed") or pd.get("wip_changed") or pd.get("missing_project_card")
    )


def _render_snapshot_project_detail(proj: dict, effective_public: bool) -> list[str]:
    stable, wip = proj["stable"], proj["wip"]
    branches, comp = stable.get("branches") or {}, stable.get("compliance") or {}
    shown_path = format_project_display_path(proj, public_mode=True) if effective_public else proj["path"]
    inst_note = f", installée : `{stable.get('installed_version') or 'n/a'}`" if proj.get("preset") == "antigravity-plugin" else ""
    enabled_note = ", désactivé dans `config.json`" if stable.get("installed_enabled") is False else ""
    ver_src = stable.get("version_source") or "manifeste"

    lines = [
        f"### {proj['name']} (`{proj['id']}`)", "", f"- **Chemin :** `{shown_path}`", f"- **Rôle :** {proj['role']}", "",
        "#### Releases & Historique Git (Stable)",
        f"- **Version (`{ver_src}`) :** `{stable['version'] or 'n/a'}` (`main` : `{branches.get('main_plugin_version') or 'n/a'}`{inst_note}{enabled_note})",
    ]
    if stable.get("install_content_compared"):
        if stable.get("install_content_drift"):
            lines.append(f"- **Contenu installé :** écart détecté (`{', '.join(stable.get('install_content_diff_files') or [])}`)")
        else:
            lines.append("- **Contenu installé :** identique au dépôt (hors adaptations OS)")
    lines.extend([
        f"- **Branches :** `{branches.get('dev_branch', 'dev')}` @ `{branches.get('dev_head') or 'n/a'}` "
        f"vs `{branches.get('main_branch', 'main')}` @ `{branches.get('main_head') or 'n/a'}` "
        f"(tag `main` : `{branches.get('main_latest_tag') or branches.get('main_tag') or 'aucun'}`, post-tag : `{branches.get('commits_since_latest_tag', 0)}`)",
        f"- **Tags :** {', '.join(f'`{t}`' for t in stable['tags']) if stable['tags'] else 'aucun'}",
        f"- **CHANGELOG :** `{stable.get('changelog_path') or 'CHANGELOG.md'}` *(source dépôt)*" if stable.get("has_changelog") else "- **CHANGELOG :** absent dans le dépôt",
    ])
    if not comp.get("ok"):
        lines.append(f"- **Écarts conformité :** {'; '.join(comp.get('issues') or [])}")
    if stable["recent_commits"]:
        lines.append("- **Derniers commits :**")
        for c in stable["recent_commits"][:5]:
            refs = f" *({c['refs']})*" if c["refs"] else ""
            lines.append(f"  - `{c['hash']}` ({c['date']}){refs} — {c['subject']}")
    lines.extend([
        "", "#### État de travail en cours (WIP non commité)",
        f"- **Branche / HEAD :** `{wip['branch'] or 'n/a'}` @ `{wip['head'] or 'n/a'}` (branche dev attendue : `{proj['default_dev_branch']}`)",
    ])
    if wip["files"]:
        lines.append(f"- **Modifications en cours ({wip['counts']['total']}) :**")
        lines.extend(f"  - `{f['status']}` `{f['path']}`" for f in wip["files"])
    else:
        lines.append("- Aucune modification non commitée.")
    lines.append("")
    return lines


def render_ecosystem_snapshot_markdown(
    snapshot: dict, *, public_mode: bool | None = None, replacements: list[tuple[str, str]] | None = None,
) -> str:
    """Génère la synthèse Markdown séparant l'état stable (`main`), `dev`, et le WIP."""
    effective_public = resolve_public_mode(snapshot) if public_mode is None else public_mode
    env, show_installed = snapshot.get("environment") or {}, has_install_audit(snapshot)
    lines = ["# Snapshot Atelier & Veilles", "", f"- **Synchronisé le :** `{snapshot['synced_at']}`"]
    if env.get("local_agy_version"):
        lines.append(f"- **CLI locale `agy` :** `{env['local_agy_version']}`")
    if show_installed:
        lines.append(f"- **Plugins installés :** {_format_installed_summary(snapshot, effective_public)}")
        orphans = visible_orphan_plugin_dirs(snapshot, effective_public)
        if orphans:
            lines.append(f"- **Dossiers sans `plugin.json` :** {', '.join(f'`{d}`' for d in orphans)}")

    lines.extend(["", "---", "", "## 1. Synthèse Projets (Stable vs WIP)", ""])
    headers = ["Projet", "Release (`main`)", "Branche `dev`"] + (["Installé"] if show_installed else []) + ["Dernier Tag", "Conformité", "État WIP"]
    lines.extend(["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"])

    for proj in snapshot["projects"]:
        stable, wip, comp = proj["stable"], proj["wip"], proj["stable"].get("compliance") or {}
        tag, comp_flag = stable["latest_tag"] or "n/a", "OK" if comp.get("ok") else f"{len(comp.get('issues') or [])} écart(s)"
        if not proj["exists"]:
            wip_summary = "Dépôt absent"
        else:
            c = wip["counts"]
            if wip.get("code_wip_count", c["total"]) == 0 and wip.get("runtime_only_wip"):
                wip_summary = "Propre *(runtime `.agents/` seul)*"
            elif c["total"] == 0:
                wip_summary = "Propre"
            else:
                wip_summary = f"**{wip.get('code_wip_count', c['total'])} code / {c['total']} total** (M:{c['modified']}, A:{c['added']}, D:{c['deleted']}, ??:{c['untracked']})"
        row = [f"**{proj['name']}** (`{proj['id']}`)", format_main_release_cell(proj), format_dev_branch_cell(proj)]
        if show_installed:
            row.append(format_installed_cell(proj))
        row.extend([f"`{tag}`", comp_flag, wip_summary])
        lines.append("| " + " | ".join(row) + " |")

    lines.extend(["", "## 2. Détail par projet", ""])
    for proj in snapshot["projects"]:
        lines.extend(_render_snapshot_project_detail(proj, effective_public))

    watches = snapshot.get("watches") or {}
    if watches:
        lines.extend(["## 3. Veilles configurées", ""])
        for wid, winfo in watches.items():
            lines.append(f"### {winfo.get('name', wid)} (`{winfo.get('fetch_status')}`)")
            if winfo.get("fetch_error"):
                lines.append(f"- **Erreur réseau :** `{winfo['fetch_error']}`")
            lines.extend(["", "| Surface | Dernière version | Versions suivies |", "|---|---|---|"])
            for slug, sinfo in (winfo.get("surfaces") or {}).items():
                vers = ", ".join(f"`{v}`" for v in sinfo.get("versions") or []) or "n/a"
                lines.append(f"| {sinfo.get('heading', slug)} | `{sinfo.get('latest_version') or 'n/a'}` | {vers} |")
            lines.append("")

    rendered = "\n".join(lines).rstrip() + "\n"
    if effective_public:
        rendered = sanitize_markdown_paths(rendered, replacements=replacements if replacements is not None else collect_path_replacements(snapshot))
    return rendered


def _render_active_artifacts_lines(arts: dict) -> list[str]:
    specs = arts.get("specs") or []
    pending_tasks = arts.get("pending_tasks") or []
    if not specs and not pending_tasks:
        return []
    out = ["## Artefacts actifs"]
    if specs:
        out.append("- **Specs actives (`specs/`) :**")
        for s in specs:
            out.append(f"  - `{s.get('filename') or s.get('id', '?')}` (`{s.get('status', 'unknown')}`, cible : `{s.get('target_project') or 'n/a'}`) — *{s.get('title', '')}*")
    if pending_tasks:
        grouped: dict[tuple[int, int], tuple[str, list[dict]]] = {}
        for t in pending_tasks:
            w = t.get("wave")
            if isinstance(w, int) and not isinstance(w, bool) and w >= 1:
                key, label = (0, w), f"Vague {w}"
            else:
                key, label = (1, 0), "Sans vague"
            grouped.setdefault(key, (label, []))[1].append(t)
        for _key, (label, items) in sorted(grouped.items(), key=lambda kv: kv[0]):
            out.append(f"- **{label} (`tasks/`) :**")
            for t in items:
                out.append(f"  - `{t.get('filename') or t.get('id', '?')}` (`{t.get('status', 'unknown')}`, cible : `{t.get('target_project') or 'n/a'}`) — *{t.get('title', '')}*")
    out.append("")
    return out


def render_delta_markdown(
    delta: dict, dry_run: bool = False, *, artifacts: dict | None = None, replacements: list[tuple[str, str]] | None = None,
) -> str:
    """Formate le micro-delta ultra-compact pour consommation LLM à coût minimal."""
    status = "EDITORIAL_UPDATE_REQUIRED" if delta.get("needs_editorial_update") else "NO_EDITORIAL_CHANGES"
    auto_files, targets, alerts = delta.get("auto_updated_files") or [], delta.get("editorial_targets") or [], delta.get("hygiene_alerts") or []
    lines = [
        f"# Gravity Architect — Delta de synchronisation{' [DRY-RUN]' if dry_run else ''}", "",
        f"- **Date :** `{delta['synced_at']}`",
        f"- **Statut éditorial :** `{status}`",
        f"- **Veilles :** `{delta.get('fetch_status')}`",
        f"- **Fichiers auto-mis à jour (0 token) :** {', '.join(f'`{f}`' for f in auto_files) if auto_files else 'aucun'}",
        f"- **Cibles éditoriales LLM :** {', '.join(f'`{t}`' for t in targets) if targets else 'aucune'}", "",
    ]
    if alerts:
        lines.extend(["## Alertes hygiène", *(f"- {a}" for a in alerts), ""])

    changed_projects = [pd for pd in (delta.get("projects") or {}).values() if _is_project_delta_changed(pd)]
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
                lines.extend(["", "```markdown", pd["latest_changelog_excerpt"], "```"])
            if pd["agents_md_diff"]:
                lines.extend(["", "```diff", *pd["agents_md_diff"], "```"])
            lines.append("")

    watch_changes = [
        sinfo for wdelta in (delta.get("watches") or {}).values()
        for sinfo in (wdelta.get("surfaces") or {}).values() if sinfo.get("new_releases")
    ]
    if watch_changes:
        lines.append("## Nouvelles releases (veilles)")
        char_budget, used_chars = 1200, 0
        for info in watch_changes:
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

    arts = artifacts if artifacts is not None else (delta.get("artifacts") or {})
    lines.extend(_render_active_artifacts_lines(arts))

    rendered = "\n".join(lines).rstrip() + "\n"
    if delta.get("public_mode"):
        rendered = sanitize_markdown_paths(rendered, replacements=replacements if replacements is not None else collect_path_replacements())
    return rendered


def format_delta_for_stdout(
    delta: dict, delta_md: str, *, max_stdout_bytes: int = 8192, dry_run: bool = False,
    delta_rel_path: str = "tracking/snapshots/delta.md", replacements: list[tuple[str, str]] | None = None,
) -> str:
    """Retourne `delta_md` si <= `max_stdout_bytes` (ou <= 0), sinon un résumé compact sous le seuil."""
    if max_stdout_bytes <= 0:
        return delta_md
    raw_bytes = delta_md.encode("utf-8")
    if len(raw_bytes) <= max_stdout_bytes:
        return delta_md

    status = "EDITORIAL_UPDATE_REQUIRED" if delta.get("needs_editorial_update") else "NO_EDITORIAL_CHANGES"
    targets, alerts, auto_files = delta.get("editorial_targets") or [], delta.get("hygiene_alerts") or [], delta.get("auto_updated_files") or []
    changed_ids = [pd["id"] for pd in (delta.get("projects") or {}).values() if _is_project_delta_changed(pd)]
    watch_updates = sum(len(sinfo.get("new_releases") or []) for wd in (delta.get("watches") or {}).values() for sinfo in (wd.get("surfaces") or {}).values())
    mode_label = " [DRY-RUN]" if dry_run else ""
    targets_str = ", ".join(f"`{t}`" for t in targets) if targets else "aucune"
    auto_str = ", ".join(f"`{f}`" for f in auto_files) if auto_files else "aucun"
    changed_str = ", ".join(f"`{pid}`" for pid in changed_ids) if changed_ids else "aucun"

    def _sanitize(text: str) -> str:
        return sanitize_markdown_paths(text, replacements=replacements if replacements is not None else collect_path_replacements()) if delta.get("public_mode") else text

    candidates = [
        "\n".join([
            f"# Gravity Architect — Delta compact{mode_label}", "",
            f"- **Date :** `{delta.get('synced_at', '')}`", f"- **Statut éditorial :** `{status}`",
            f"- **Veilles :** `{delta.get('fetch_status')}` ({watch_updates} release(s))",
            f"- **Fichiers auto-mis à jour (0 token) :** {auto_str}", f"- **Cibles éditoriales LLM :** {targets_str}",
            f"- **Statistiques :** {len(changed_ids)} projet(s) modifié(s) ({changed_str}), {len(alerts)} alerte(s) hygiène, {len(raw_bytes)} o complets.",
            f"- **Delta complet :** `{delta_rel_path}` (tronqué pour stdout <= {max_stdout_bytes} o)", "",
        ]),
        "\n".join([
            f"# Gravity Architect — Delta compact{mode_label}", f"- **Statut éditorial :** `{status}`",
            f"- **Cibles éditoriales LLM :** {targets_str}",
            f"- **Stats :** projets={len(changed_ids)}, alertes={len(alerts)}, veilles={watch_updates}, taille={len(raw_bytes)} o",
            f"- **Delta complet :** `{delta_rel_path}`", "",
        ]),
        "\n".join([
            f"# Delta compact{mode_label}", f"- **Statut éditorial :** `{status}`",
            f"- **Cibles éditoriales LLM :** {len(targets)} ({targets[0]}...)" if targets else "- **Cibles éditoriales LLM :** aucune",
            f"- **Stats :** p={len(changed_ids)}, a={len(alerts)}, v={watch_updates}", f"- **Delta complet :** `{delta_rel_path}`", "",
        ]),
    ]
    for cand in candidates:
        sanitized = _sanitize(cand)
        if len(sanitized.encode("utf-8")) <= max_stdout_bytes:
            return sanitized
    minimal = _sanitize(f"{status} | Cibles éditoriales LLM: {len(targets)} | {delta_rel_path}\n")
    encoded = minimal.encode("utf-8")
    if len(encoded) <= max_stdout_bytes:
        return minimal
    return encoded[: max(0, max_stdout_bytes - 1)].decode("utf-8", errors="ignore") + ("\n" if max_stdout_bytes >= 1 else "")


def replace_auto_block(text: str, block_id: str, new_body: str) -> tuple[str, bool]:
    """Remplace strictement le corps entre `<!-- AUTO:START:<id> -->` et `<!-- AUTO:END:<id> -->`."""
    start_marker, end_marker = f"<!-- AUTO:START:{block_id} -->", f"<!-- AUTO:END:{block_id} -->"
    pattern = re.compile(re.escape(start_marker) + r".*?" + re.escape(end_marker), re.DOTALL)
    if not pattern.search(text):
        return text, False
    replacement = f"{start_marker}\n{new_body.strip(chr(13) + chr(10))}\n{end_marker}"
    updated = pattern.sub(lambda _m: replacement, text, count=1)
    return updated, updated.replace("\r\n", "\n") != text.replace("\r\n", "\n")


def format_project_tasks_block(pid: str, artifacts: dict) -> str:
    """Formate le bloc `project-tasks:<id>` avec plafond compact sur l'historique archivé."""
    target_re = re.compile(rf"(?<![a-z0-9-]){re.escape(pid.lower())}(?![a-z0-9-])")

    def _matches(item: dict) -> bool:
        target = (item.get("target_project") or "").lower()
        return bool(target_re.search(target)) if target else (f"-{pid.lower()}-" in item["filename"].lower())

    pending = [t for t in artifacts.get("pending_tasks", []) if _matches(t)]
    archived = [t for t in artifacts.get("archived_tasks", []) if _matches(t)]
    lines = (
        ["- **Tasks en attente (`tasks/`) :**", *(f"  - [`{t['filename']}`](../../{t['rel_path']}) (`{t['status']}`) — *{t['title']}*" for t in pending)]
        if pending
        else ["- **Tasks en attente (`tasks/`) :** aucune."]
    )
    if archived:
        lines.append("- **Tasks archivées (`tasks/archive/`) :**")
        lines.extend(f"  - [`{t['filename']}`](../../{t['rel_path']}) (`{t['status']}`)" for t in archived[-3:])
        if len(archived) > 3:
            lines.append(f"  - *(+{len(archived) - 3} plus anciennes dans `tasks/archive/`)*")
    return "\n".join(lines)


def build_ecosystem_blocks(
    snapshot: dict, delta: dict, concept_root: Path, *,
    public_mode: bool | None = None, replacements: list[tuple[str, str]] | None = None,
) -> dict[str, str]:
    """Construit les dictionnaires de blocs AUTO pour `ECOSYSTEM.md`."""
    effective_public = resolve_public_mode(snapshot) if public_mode is None else public_mode
    sync_date, env, show_installed = snapshot["synced_at"][:10], snapshot.get("environment") or {}, has_install_audit(snapshot)
    meta_lines = [
        "- **Espace de conception :** atelier courant *(lecture seule stricte sur les dépôts suivis)*",
        f"- **Dernier snapshot :** [`tracking/snapshots/ecosystem_snapshot.md`](tracking/snapshots/ecosystem_snapshot.md) *({sync_date})*",
    ]
    if show_installed:
        meta_lines.append(f"- **CLI locale `agy` :** `{env.get('local_agy_version') or 'non détectée'}` · **Plugins installés :** {_format_installed_summary(snapshot, effective_public)}")
    meta_lines.append("- **Charte :** [`AGENTS.md`](AGENTS.md)")

    headers = ["Projet", "Release (`main`)", "Branche `dev`"] + (["Installé local"] if show_installed else []) + ["WIP", "Fiche"]
    proj_lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for proj in snapshot["projects"]:
        pid = proj["id"]
        rel_path, card_rel = format_project_display_path(proj, public_mode=effective_public), f"tracking/projects/{pid}.md"
        card_cell = f"[`{pid}.md`]({card_rel})" if (concept_root / card_rel).is_file() else "*(absente)*"
        row = [f"**{proj['name']}** (`{rel_path}`)", format_main_release_cell(proj), format_dev_branch_cell(proj)]
        if show_installed:
            row.append(format_installed_cell(proj))
        row.extend([format_wip_cell(proj), card_cell])
        proj_lines.append("| " + " | ".join(row) + " |")

    watches_map = snapshot_watches_map(snapshot)
    watch_lines: list[str] = []
    if watches_map:
        watch_lines.extend(["| Surface | Dernière release | Versions archivées | Détails |", "|---|---|---|---|"])
        for wid, winfo in watches_map.items():
            w_out = str(winfo.get("out_dir") or f"tracking/watches/{wid}").rstrip("/")
            for slug, sinfo in (winfo.get("surfaces") or {}).items():
                vers = ", ".join(f"`{v}`" for v in sinfo.get("versions") or []) or "n/a"
                watch_lines.append(f"| **{sinfo.get('heading', slug)}** | `{sinfo.get('latest_version') or 'n/a'}` | {vers} | [`{w_out}/releases/{slug}.md`]({w_out}/releases/{slug}.md) |")
    else:
        watch_lines.append("- Aucune veille configurée dans `projects.json`.")

    artifacts = snapshot.get("artifacts") or {"specs": [], "archived_specs": [], "pending_tasks": [], "archived_tasks": []}
    art_lines: list[str] = []
    for key, label, tpl in (("specs", "Spécifications actives (`specs/`)", "specs/_TEMPLATE.md"), ("pending_tasks", "Tasks en attente (`tasks/`)", "tasks/_TEMPLATE.md")):
        items = artifacts.get(key) or []
        if items:
            art_lines.append(f"- **{label} :**")
            art_lines.extend(f"  - [`{x['filename']}`]({x['rel_path']}) (`{x['status']}`, cible : `{x['target_project'] or 'n/a'}`) — *{x['title']}*" for x in items)
        else:
            art_lines.append(f"- **{label} :** aucune *(modèle : [`{tpl}`]({tpl}))*.")
        if key == "specs" and artifacts.get("archived_specs"):
            last_s = artifacts["archived_specs"][-1]
            art_lines.append(f"- **Spécifications archivées (`specs/archive/`) :** {len(artifacts['archived_specs'])} *(ex. [`{last_s['filename']}`]({last_s['rel_path']}))*")
    archived_tasks = artifacts.get("archived_tasks") or []
    art_lines.append(
        f"- **Tasks archivées (`tasks/archive/`) :** {len(archived_tasks)} *(dernière : [`{archived_tasks[-1]['filename']}`]({archived_tasks[-1]['rel_path']}))*"
        if archived_tasks
        else "- **Tasks archivées (`tasks/archive/`) :** aucune pour le moment."
    )

    alerts = delta.get("hygiene_alerts") or []
    watch_body = "\n".join(watch_lines)
    blocks = {
        "ecosystem-meta": "\n".join(meta_lines),
        "ecosystem-projects": "\n".join(proj_lines),
        "ecosystem-watches": watch_body,
        "ecosystem-antigravity": watch_body,
        "ecosystem-artifacts": "\n".join(art_lines),
        "ecosystem-hygiene": "\n".join(f"- {a}" for a in alerts) if alerts else "- Aucune alerte d'hygiène détectée.",
    }
    if effective_public:
        mask_pairs = replacements if replacements is not None else collect_path_replacements(snapshot, concept_root=concept_root)
        blocks = {k: sanitize_markdown_paths(v, replacements=mask_pairs) for k, v in blocks.items()}
    return blocks


def _format_project_changelog_link(proj: dict, effective_public: bool) -> str:
    stable = proj["stable"]
    if not stable.get("has_changelog"):
        return "**Absent**"
    chg_rel = str(stable.get("changelog_path") or proj.get("changelog") or "CHANGELOG.md").replace("\\", "/").lstrip("/")
    raw_path = str(proj.get("path") or "").replace("\\", "/").strip()
    if effective_public or not raw_path or raw_path.startswith("/") or (len(raw_path) >= 2 and raw_path[1] == ":"):
        return f"`{chg_rel}`"
    target = posixpath.normpath(f"../../{raw_path.rstrip('/')}/{chg_rel}")
    return f"[`{chg_rel}`]({target})"


def _build_project_card_meta_body(proj: dict, sync_date: str, effective_public: bool) -> str:
    pid, stable, wip = proj["id"], proj["stable"], proj["wip"]
    branches = stable.get("branches") or {}
    dev_b, main_b = branches.get("dev_branch") or proj.get("default_dev_branch") or "dev", branches.get("main_branch") or "main"
    display_path = format_project_display_path(proj, public_mode=effective_public)
    chg_link = _format_project_changelog_link(proj, effective_public)

    if not proj["exists"]:
        release_line, branch_line, wip_line = "dépôt introuvable", "dépôt introuvable", "Dépôt absent"
    else:
        main_tag, main_head = branches.get("main_latest_tag") or branches.get("main_tag"), branches.get("main_head")
        dev_head, latest_tag = branches.get("dev_head") or wip.get("head"), stable.get("latest_tag")
        dev_ver = branches.get("dev_plugin_version") or stable.get("version") or "n/a"
        adv, post = branches.get("dev_ahead_of_main", 0), branches.get("commits_since_latest_tag", 0)
        tag_dev_note = f" *(tag `{latest_tag}` sur `{dev_b}`)*" if (latest_tag and not branches.get("latest_tag_on_main", True)) else ""
        release_line = f"`{main_tag or 'aucune'}` (`{main_head or '?'}`) — {chg_link}{tag_dev_note}"
        if branches.get("branch_drift") or post > 0:
            post_note = f", +{post} post-`{latest_tag}`" if (post > 0 and latest_tag) else ""
            branch_line = f"`{dev_head or '?'}` (`+{adv}` vs `{main_b}`{post_note}), manifeste `{dev_ver}`"
        else:
            branch_line = f"alignée sur `{main_b}` (`{dev_head or '?'}`), manifeste `{dev_ver}`"
        if wip.get("code_wip_count", 0) == 0 and wip.get("runtime_only_wip"):
            wip_line = "Propre *(runtime `.agents/` uniquement)*"
        else:
            wip_line = "Propre (`0` fichier)" if wip.get("code_wip_count", 0) == 0 else f"**{wip['code_wip_count']} fichier(s) code WIP**"

    meta_lines = [
        f"- **Dépôt :** `{display_path}`", f"- **Rôle :** {proj['role']}",
        f"- **Release (`{main_b}`) :** {release_line}", f"- **Branche `{dev_b}` :** {branch_line}",
    ]
    if proj.get("preset") == "antigravity-plugin":
        meta_lines.append(f"- **Installé local :** {format_installed_cell(proj)}")
    meta_lines.extend([f"- **WIP en cours :** {wip_line}", f"- **Dernière synchro :** `{sync_date}`"])
    return "\n".join(meta_lines)


def _build_watch_impact_body(winfo: dict, env: dict, sync_date: str) -> str:
    cli_check = winfo.get("local_cli_check") or {}
    local_agy = env.get("local_agy_version") or "non détectée"
    meta_lines = [
        f"- **Dernière synchro :** `{sync_date}`", f"- **Source officielle :** `{winfo.get('source_url')}`", "",
        "| Surface | Dernière version officielle | Versions suivies | Écart local |", "|---|---|---|---|",
    ]
    for slug, sinfo in (winfo.get("surfaces") or {}).items():
        latest = sinfo.get("latest_version") or "n/a"
        vers = ", ".join(f"`{v}`" for v in sinfo.get("versions") or []) or "n/a"
        if isinstance(cli_check, dict) and slug == cli_check.get("surface_slug"):
            if local_agy == "non détectée":
                gap = f"`{local_agy}` local"
            else:
                cmp_state = compare_cli_versions(str(local_agy), str(latest))
                gap = f"**`{local_agy}` local** *(écart)*" if cmp_state == "behind" else (f"`{local_agy}` local *(en avance)*" if cmp_state == "ahead" else f"`{local_agy}` local")
        else:
            gap = "—"
        meta_lines.append(f"| **{sinfo.get('heading', slug)}** | `{latest}` | {vers} | {gap} |")
    return "\n".join(meta_lines)


def apply_auto_doc_updates(
    concept_root: Path, snapshot: dict, delta: dict, dry_run: bool = False, *,
    public_mode: bool | None = None, replacements: list[tuple[str, str]] | None = None,
) -> list[str]:
    """Met à jour les blocs `<!-- AUTO:START/END -->` des fiches vivantes existantes."""
    effective_public = resolve_public_mode(snapshot) if public_mode is None else public_mode
    mask_pairs = (replacements if replacements is not None else collect_path_replacements(snapshot, concept_root=concept_root)) if effective_public else None
    updated_files: list[str] = []
    sync_date, artifacts = snapshot["synced_at"][:10], snapshot.get("artifacts") or {}

    eco_path = concept_root / "ECOSYSTEM.md"
    if eco_path.is_file():
        current, any_changed = eco_path.read_text(encoding="utf-8", errors="replace"), False
        for block_id, body in build_ecosystem_blocks(snapshot, delta, concept_root, public_mode=effective_public, replacements=mask_pairs).items():
            current, changed = replace_auto_block(current, block_id, body)
            any_changed = any_changed or changed
        if any_changed:
            if not dry_run:
                write_text_atomic(eco_path, current)
            updated_files.append("ECOSYSTEM.md")

    for proj in snapshot["projects"]:
        pid = proj["id"]
        rel = f"tracking/projects/{pid}.md"
        card_path = concept_root / rel
        if not card_path.is_file():
            continue
        meta_body = _build_project_card_meta_body(proj, sync_date, effective_public)
        tasks_body = format_project_tasks_block(pid, artifacts)
        if effective_public:
            meta_body = sanitize_markdown_paths(meta_body, replacements=mask_pairs)
            tasks_body = sanitize_markdown_paths(tasks_body, replacements=mask_pairs)
        current, ch1 = replace_auto_block(card_path.read_text(encoding="utf-8", errors="replace"), f"project-meta:{pid}", meta_body)
        current, ch2 = replace_auto_block(current, f"project-tasks:{pid}", tasks_body)
        if ch1 or ch2:
            if not dry_run:
                write_text_atomic(card_path, current)
            updated_files.append(rel)

    env = snapshot.get("environment") or {}
    for wid, winfo in snapshot_watches_map(snapshot).items():
        impact_rel = winfo.get("impact_file")
        if not impact_rel or not (impact_path := concept_root / str(impact_rel)).is_file():
            continue
        body = _build_watch_impact_body(winfo, env, sync_date)
        if effective_public:
            body = sanitize_markdown_paths(body, replacements=mask_pairs)
        current, ch = replace_auto_block(impact_path.read_text(encoding="utf-8", errors="replace"), f"watch-meta:{wid}", body)
        if not ch and wid == "antigravity":
            current, ch = replace_auto_block(current, "antigravity-meta", body)
        if ch:
            if not dry_run:
                write_text_atomic(impact_path, current)
            if str(impact_rel) not in updated_files:
                updated_files.append(str(impact_rel))

    return updated_files


def persist_sync_outputs(
    resolved_concept_root: Path, snapshots_dir: Path, editorial_state_path: Path,
    watches_data: dict[str, dict], full_snapshot: dict, delta: dict, delta_md: str,
    next_editorial_state: dict, *, effective_public: bool, mask_pairs: list[tuple[str, str]] | None,
) -> None:
    """Écrit sur disque les artefacts JSON/Markdown de synchronisation sans churn inutile."""
    for wid, wobj in watches_data.items():
        wdir = (resolved_concept_root / str(wobj.get("out_dir") or f"tracking/watches/{wid}")).resolve()
        write_json_if_changed(wdir / "summary.json", wobj)
    write_json_if_changed(snapshots_dir / "ecosystem_snapshot.json", full_snapshot)
    write_md_if_changed(snapshots_dir / "ecosystem_snapshot.md", render_ecosystem_snapshot_markdown(full_snapshot, public_mode=effective_public, replacements=mask_pairs))
    write_json_if_changed(snapshots_dir / "delta.json", delta)
    write_md_if_changed(snapshots_dir / "delta.md", delta_md)
    write_json_if_changed(editorial_state_path, next_editorial_state)
