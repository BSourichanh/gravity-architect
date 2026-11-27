#!/usr/bin/env python3
"""Strict standalone validator for Gravity Architect (delegates to _shared.validator_core)."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT_DEFAULT = SCRIPT_DIR.parent
if str(PLUGIN_ROOT_DEFAULT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT_DEFAULT))

from _shared import validator_core  # noqa: E402
from _shared.validator_core import (  # noqa: E402
    Report,
    ValidatorConfig,
    check_utf8_no_bom_lf,
    has_real_python3,
    validate_plugin_tree,
)

_detect_portable_python_cmd = validator_core._detect_portable_python_cmd
fix_python_cmd = validator_core.fix_python_cmd
FORBIDDEN_MOD_RE = validator_core.FORBIDDEN_MOD_RE
PRIVATE_LEAK_RES = (
    ("archive interne", re.compile(r"BLUE" + r"PRINT-v0\.1", re.IGNORECASE)),
    ("dossier atelier local", re.compile(r"gravity_" + r"projects", re.IGNORECASE)),
)
ARCHITECT_ALLOWED_MODULES = validator_core.ALLOWED_LOCAL_MODULES | frozenset(
    {"scripts", "hooks", "waves", "atelier_status", "pre_invocation_architect", "validate"}
)
REQUIRED_TEMPLATES = (
    "AGENTS.md",
    "ECOSYSTEM.md",
    "projects.json",
    "spec-template.md",
    "task-template.md",
    "project-card-template.md",
    "impact-template.md",
    "audit-code-readme.md",
    "audit-code-template.md",
)


def _extract_markdown_targets(md_text: str) -> list[str]:
    targets: list[str] = []
    in_fence, fence_char, fence_len = False, "", 0
    for line in md_text.splitlines():
        if (fm := validator_core.MD_FENCE_RE.match(line)):
            marker = fm.group(1)
            if not in_fence:
                in_fence, fence_char, fence_len = True, marker[0], len(marker)
                continue
            if marker[0] == fence_char and len(marker) >= fence_len and line.strip() == marker:
                in_fence = False
                continue
        if in_fence:
            continue
        for m in validator_core.MD_LINK_RE.finditer(validator_core.INLINE_CODE_RE.sub("", line)):
            rt = m.group(1).strip()
            t = rt[1 : rt.index(">")].strip() if (rt.startswith("<") and ">" in rt) else (rt.split()[0] if rt else "")
            if t:
                targets.append(t)
    return targets


def _check_markdown_file_links(md_path: Path, label: str, report: Report, *, check_broken: bool) -> None:
    try:
        content = md_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        report.error(f"Impossible de lire {label} : {exc}")
        return
    for target in _extract_markdown_targets(content):
        lower = target.lower()
        if lower.startswith("file:"):
            report.error(f"Lien 'file:' interdit dans {label} : {target!r}")
            continue
        if not check_broken or lower.startswith(validator_core.IGNORED_LINK_PREFIXES):
            continue
        rel = target.split("#", 1)[0].split("?", 1)[0]
        if rel and not (md_path.parent / rel).resolve().exists():
            report.error(f"Lien Markdown relatif cassé dans {label} : {target!r}")


def _check_hooks_extra(root: Path, report: Report) -> None:
    hooks_json = root / "hooks.json"
    if not hooks_json.is_file():
        return
    try:
        raw = hooks_json.read_bytes()
        data = json.loads((raw[3:] if raw.startswith(validator_core.UTF8_BOM) else raw).decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return
    if not isinstance(data, dict):
        return
    allowed = {"enabled", *validator_core.FLAT_HOOK_EVENTS, *validator_core.GROUPED_HOOK_EVENTS}
    for gname, gcfg in data.items():
        if isinstance(gcfg, dict) and (unknown := sorted(set(gcfg.keys()) - allowed)):
            report.error(f"hooks.json ({gname}) : clés inconnues {unknown}")


def _check_templates(root: Path, report: Report) -> None:
    tpl_dir = root / "templates"
    if not tpl_dir.is_dir():
        report.error("Dossier requis manquant : templates/")
        return
    for tpl_name in REQUIRED_TEMPLATES:
        if not (tpl_dir / tpl_name).is_file():
            report.error(f"Template requis manquant : templates/{tpl_name}")
    if (tpl_agents := tpl_dir / "AGENTS.md").is_file():
        check_utf8_no_bom_lf(tpl_agents, "templates/AGENTS.md", report, max_bytes=2500)
    if (tpl_cfg := tpl_dir / "projects.json").is_file():
        try:
            data = json.loads(tpl_cfg.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("schema_version") != 5:
                report.error("templates/projects.json doit définir schema_version=5.")
            else:
                if "privacy" in data:
                    priv = data["privacy"]
                    if not isinstance(priv, dict) or not isinstance(priv.get("public_mode"), bool):
                        report.error("templates/projects.json : 'privacy.public_mode' doit être un booléen.")
                if "post_commit_install_cmd" in data:
                    cmd = data["post_commit_install_cmd"]
                    ok_cmd = cmd is None or (isinstance(cmd, str) and bool(cmd.strip())) or (isinstance(cmd, list) and bool(cmd) and all(isinstance(x, str) and bool(x.strip()) for x in cmd))
                    if not ok_cmd:
                        report.error("templates/projects.json : 'post_commit_install_cmd' doit être str, list[str] ou null.")
                if "verify_commands" in data:
                    vcmds = data["verify_commands"]
                    if not isinstance(vcmds, list) or not all(isinstance(x, str) and bool(x.strip()) for x in vcmds):
                        report.error("templates/projects.json : 'verify_commands' doit être une liste de chaînes non vides.")
        except Exception as exc:
            report.error(f"templates/projects.json invalide : {exc}")


def _run_e2e_dry_run(root: Path, report: Report) -> None:
    init_script, sync_script = root / "scripts" / "init_workspace.py", root / "scripts" / "sync_tracking.py"
    if not init_script.is_file() or not sync_script.is_file():
        report.error("Scripts init_workspace.py ou sync_tracking.py manquants.")
        return
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        demo_repo, ws_dir, arch_home = tmp_path / "demo-app", tmp_path / "atelier", tmp_path / "architect-home"
        demo_repo.mkdir(parents=True)
        (demo_repo / "package.json").write_text('{"name": "demo-app", "version": "1.2.3"}\n', encoding="utf-8")
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "GRAVITY_ARCHITECT_HOME": str(arch_home)}
        env.pop("GRAVITY_ARCHITECT_WORKSPACE", None)
        env.pop("GRAVITY_ARCHITECT_SKIP_REGISTRY", None)
        p_init = subprocess.run([sys.executable, "-B", str(init_script), "--workspace", str(ws_dir), "--name", "Atelier Dry-Run", "--project", f"demo={demo_repo}"], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=10, check=False)
        if p_init.returncode != 0:
            report.error(f"Dry-run init_workspace.py échoué : {p_init.stderr or p_init.stdout}")
            return
        reg_path, reg_raw_before, reg_mtime_before = arch_home / "ateliers.json", None, None
        if reg_path.is_file():
            try:
                reg_raw_before = reg_path.read_text(encoding="utf-8")
                reg_data = json.loads(reg_raw_before)
                reg_mtime_before = reg_path.stat().st_mtime_ns
                reg_paths = [str(it.get("workspace_path") or "") for it in (reg_data.get("ateliers") or []) if isinstance(it, dict)]
                if str(ws_dir.resolve()) not in reg_paths:
                    report.error("Dry-run ateliers.json ne contient pas l'atelier initialisé.")
                    return
            except Exception as exc:
                report.error(f"Dry-run ateliers.json illisible : {exc}")
                return
        p_sync = subprocess.run([sys.executable, "-B", str(sync_script), "--workspace", str(ws_dir), "--offline", "--check", "--print-delta"], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=10, check=False)
        if p_sync.returncode != 0:
            report.error(f"Dry-run sync_tracking.py échoué : {p_sync.stderr or p_sync.stdout}")
            return
        if "EDITORIAL_UPDATE_REQUIRED" not in p_sync.stdout and "NO_EDITORIAL_CHANGES" not in p_sync.stdout:
            report.error(f"Sortie inattendue du dry-run sync_tracking.py : {p_sync.stdout!r}")
        if reg_raw_before is None and reg_path.is_file():
            report.error("Dry-run sync_tracking.py --check a créé ateliers.json.")
        elif reg_raw_before is not None and (reg_path.stat().st_mtime_ns != reg_mtime_before or reg_path.read_text(encoding="utf-8") != reg_raw_before):
            report.error("Dry-run sync_tracking.py --check a modifié ateliers.json.")


def _extra_architect_checks(root: Path, report: Report) -> None:
    if not (root / "README.md").is_file():
        report.error("README.md manquant à la racine du plugin.")
    else:
        _check_markdown_file_links(root / "README.md", "README.md", report, check_broken=False)
    skills_dir = root / "skills"
    if skills_dir.is_dir():
        names = [p.name for p in sorted(skills_dir.iterdir()) if p.is_dir()]
        if names != ["gravity-architect"]:
            report.error(f"skills/ doit contenir uniquement 'gravity-architect/' (trouvé : {names}).")
        skill_md = skills_dir / "gravity-architect" / "SKILL.md"
        if skill_md.is_file():
            _check_markdown_file_links(skill_md, "skills/gravity-architect/SKILL.md", report, check_broken=False)
        refs_dir = skills_dir / "gravity-architect" / "references"
        if not (refs_dir / "workflows-and-hygiene.md").is_file():
            report.error("skills/gravity-architect/references/workflows-and-hygiene.md introuvable.")
        if refs_dir.is_dir():
            for ref_md in sorted(refs_dir.glob("*.md")):
                if ref_md.is_file():
                    lbl = f"skills/gravity-architect/references/{ref_md.name}"
                    check_utf8_no_bom_lf(ref_md, lbl, report, max_bytes=None)
                    _check_markdown_file_links(ref_md, lbl, report, check_broken=True)
    if root.name == "plugin" and (root.parent / "README.md").is_file():
        _check_markdown_file_links(root.parent / "README.md", "../README.md", report, check_broken=True)
    _check_hooks_extra(root, report)
    _check_templates(root, report)
    _run_e2e_dry_run(root, report)


_BASE_CFG = ValidatorConfig(
    plugin_root=PLUGIN_ROOT_DEFAULT,
    expected_plugin_name="gravity-architect",
    expected_module_id="architect",
    required_dirs=("assets", "config", "core", "hooks", "rules", "scripts", "skills", "templates", "_shared"),
    allowed_local_modules=ARCHITECT_ALLOWED_MODULES,
    extra_forbidden_patterns=PRIVATE_LEAK_RES,
    require_module_contract=True,
    require_hooks_config=True,
    require_rules_agents=True,
    rules_warn_bytes=600,
    rules_max_bytes=1000,
    skill_max_bytes=6000,
    repo_agents_max_bytes=2500,
    extra_check_fn=_extra_architect_checks,
)


def validate_plugin(root: Path, report: Report) -> None:
    """Audit plugin structure, manifest, module contract, hooks, templates, stdlib, and leaks."""
    validate_plugin_tree(replace(_BASE_CFG, plugin_root=root), report)


def main(argv: Optional[list[str]] = None) -> int:
    return validator_core.run_cli(_BASE_CFG, argv, description="Gravity Architect strict validator")


if __name__ == "__main__":
    raise SystemExit(main())
