#!/usr/bin/env python3
"""Validateur strict du plugin autonome Gravity Architect (100 % stdlib Python 3)."""

from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT_DEFAULT = SCRIPT_DIR.parent

OFFICIAL_PLUGIN_FIELDS = {
    "name",
    "displayName",
    "version",
    "description",
    "logo",
    "suggestedPrompts",
    "author",
    "homepage",
    "repository",
    "disabled",
}
ALLOWED_LOCAL_MODULES = {"sync_tracking", "init_workspace", "validate"}
MODULE_CONTRACT_FIELDS = {
    "schema_version",
    "id",
    "plugin_name",
    "role",
    "storage",
    "commands",
    "capabilities",
    "ui",
    "signals",
}
ALLOWED_UI_MODES = {"none", "core", "native-mcp-app", "transition-sidecar"}

FORBIDDEN_MOD_RE = re.compile(r"\bMod" + r"ule\s+0?\d\b", re.IGNORECASE)
PRIVATE_LEAK_RES = (
    (
        "chemin personnel",
        re.compile(
            r"(?:"
            + r"[A-Za-z]:\\" + r"(?:Users|Documents)\\"
            + r"|[A-Za-z]:\\[^\\\s\"'`]+\\" + r"Documents\\"
            + r"|/Us" + r"ers/[^/\s\"'`]+/"
            + r"|/ho" + r"me/[^/\s\"'`]+/"
            + r")",
            re.IGNORECASE,
        ),
    ),
    ("référence projet frère", re.compile(r"gravity-" + r"metrics", re.IGNORECASE)),
    ("archive interne", re.compile(r"BLUE" + r"PRINT-v0\.1", re.IGNORECASE)),
    ("dossier atelier local", re.compile(r"gravity_" + r"projects", re.IGNORECASE)),
)

REQUIRED_TEMPLATES = (
    "AGENTS.md",
    "ECOSYSTEM.md",
    "projects.json",
    "spec-template.md",
    "handoff-template.md",
    "project-card-template.md",
    "impact-template.md",
    "archives-readme.md",
    "audit-code-readme.md",
    "audit-code-template.md",
)


class Report:
    """Collecteur d'erreurs, d'avertissements et d'informations de validation."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.infos: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def info(self, msg: str) -> None:
        self.infos.append(msg)

    def ok(self, strict: bool) -> bool:
        return len(self.errors) == 0 and (not strict or len(self.warnings) == 0)


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconf = getattr(stream, "reconfigure", None)
        if callable(reconf):
            try:
                reconf(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _check_stdlib_only(py_file: Path, report: Report) -> None:
    stdlib_names_raw = getattr(sys, "stdlib_module_names", None)
    if not stdlib_names_raw:
        report.error("Python 3.10+ requis pour la validation stdlib.")
        return
    allowed = set(stdlib_names_raw) | ALLOWED_LOCAL_MODULES
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    except SyntaxError as exc:
        report.error(f"Syntaxe Python invalide dans {py_file}: {exc}")
        return
    for node in ast.walk(tree):
        mods: list[str] = []
        if isinstance(node, ast.Import):
            mods = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods = [node.module.split(".")[0]]
        for mod in mods:
            if mod not in allowed:
                report.error(f"Import non stdlib {mod!r} détecté dans {py_file}")


def _validate_manifest(root: Path, report: Report) -> None:
    manifest_path = root / "plugin.json"
    if not manifest_path.is_file():
        report.error("plugin.json introuvable à la racine du plugin.")
        return

    raw_bytes = manifest_path.read_bytes()
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        report.error("plugin.json ne doit pas contenir de BOM UTF-8.")

    try:
        manifest = json.loads(raw_bytes.decode("utf-8-sig"))
    except Exception as exc:
        report.error(f"plugin.json invalide : {exc}")
        return

    if not isinstance(manifest, dict):
        report.error("plugin.json doit contenir un objet JSON.")
        return

    unknown_keys = sorted(set(manifest.keys()) - OFFICIAL_PLUGIN_FIELDS)
    if unknown_keys:
        report.error(f"plugin.json : champs non officiels détectés : {unknown_keys}")

    if manifest.get("name") != "gravity-architect":
        report.error(
            f"plugin.json : 'name' doit être 'gravity-architect', obtenu {manifest.get('name')!r}."
        )

    missing_req = [
        k for k in OFFICIAL_PLUGIN_FIELDS - {"disabled"} if k not in manifest
    ]
    if missing_req:
        report.error(f"plugin.json : champs requis manquants : {missing_req}")

    desc = str(manifest.get("description") or "")
    if not desc or len(desc) > 160:
        report.error(f"plugin.json : 'description' vide ou > 160 caractères ({len(desc)}).")

    prompts = manifest.get("suggestedPrompts")
    if (
        not isinstance(prompts, list)
        or len(prompts) != 3
        or not all(isinstance(p, str) and p.strip() for p in prompts)
    ):
        report.error("plugin.json : exactement 3 'suggestedPrompts' non vides sont requis.")

    logo_rel = str(manifest.get("logo") or "")
    logo_path = root / logo_rel
    if not logo_rel or not logo_path.is_file():
        report.error(f"Logo introuvable : {logo_rel!r}")
    elif logo_path.suffix.lower() == ".svg":
        svg = logo_path.read_text(encoding="utf-8", errors="replace")
        vb = re.search(
            r"""viewBox\s*=\s*["']0\s+0\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)["']""",
            svg,
        )
        if not vb or float(vb.group(1)) <= 0 or float(vb.group(1)) != float(vb.group(2)):
            report.error(f"Logo {logo_rel} : viewBox carré 1:1 non détecté.")


def _validate_module_contract(root: Path, report: Report) -> None:
    """Valide le contrat module Gravity `config/module.json` (schema_version 1)."""
    module_path = root / "config" / "module.json"
    if not module_path.is_file():
        report.error("config/module.json introuvable.")
        return

    raw_bytes = module_path.read_bytes()
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        report.error("config/module.json ne doit pas contenir de BOM UTF-8.")

    try:
        mod = json.loads(raw_bytes.decode("utf-8-sig"))
    except Exception as exc:
        report.error(f"config/module.json invalide : {exc}")
        return

    if not isinstance(mod, dict):
        report.error("config/module.json doit contenir un objet JSON.")
        return

    unknown_keys = sorted(set(mod.keys()) - MODULE_CONTRACT_FIELDS)
    if unknown_keys:
        report.error(f"config/module.json : champs non reconnus : {unknown_keys}")

    missing_keys = sorted(MODULE_CONTRACT_FIELDS - set(mod.keys()))
    if missing_keys:
        report.error(f"config/module.json : champs requis manquants : {missing_keys}")

    sv = mod.get("schema_version")
    if isinstance(sv, bool) or sv != 1:
        report.error(f"config/module.json : 'schema_version' doit valoir 1 (obtenu {sv!r}).")

    mod_id = mod.get("id")
    if not isinstance(mod_id, str) or not re.match(r"^[a-z0-9][a-z0-9-]{0,31}$", mod_id):
        report.error(f"config/module.json : 'id' invalide ({mod_id!r}).")

    plugin_name = mod.get("plugin_name")
    if not isinstance(plugin_name, str) or plugin_name != "gravity-architect":
        report.error(
            f"config/module.json : 'plugin_name' doit être 'gravity-architect' (obtenu {plugin_name!r})."
        )

    role = mod.get("role")
    if not isinstance(role, str) or not role.strip():
        report.error("config/module.json : 'role' doit être une chaîne non vide.")

    storage = mod.get("storage")
    if not isinstance(storage, dict):
        report.error("config/module.json : 'storage' doit être un objet JSON.")
    else:
        for sk in ("subdir", "env_override"):
            val = storage.get(sk)
            if not isinstance(val, str) or not val.strip():
                report.error(f"config/module.json : 'storage.{sk}' doit être une chaîne non vide.")

    for list_field in ("commands", "capabilities"):
        vals = mod.get(list_field)
        if (
            not isinstance(vals, list)
            or not vals
            or not all(isinstance(x, str) and x.strip() for x in vals)
        ):
            report.error(f"config/module.json : '{list_field}' doit être une liste non vide de chaînes.")
        elif list_field == "commands" and not all(x.startswith("/") for x in vals):
            report.error("config/module.json : chaque entrée de 'commands' doit commencer par '/'.")

    ui = mod.get("ui")
    if not isinstance(ui, dict):
        report.error("config/module.json : 'ui' doit être un objet JSON.")
    else:
        if ui.get("mode") not in ALLOWED_UI_MODES:
            report.error(f"config/module.json : 'ui.mode' invalide ({ui.get('mode')!r}).")
        if not isinstance(ui.get("target"), str) or not ui["target"].strip():
            report.error("config/module.json : 'ui.target' doit être une chaîne non vide.")

    signals = mod.get("signals")
    if not isinstance(signals, dict):
        report.error("config/module.json : 'signals' doit être un objet JSON.")
    else:
        for sig_key in ("produces", "consumes"):
            svals = signals.get(sig_key)
            if not isinstance(svals, list) or not all(
                isinstance(x, str) and x.strip() for x in svals
            ):
                report.error(
                    f"config/module.json : 'signals.{sig_key}' doit être une liste de chaînes."
                )


def _validate_skills(root: Path, report: Report) -> None:
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        report.error("Dossier requis manquant : skills/gravity-architect/")
        return

    names = [p.name for p in sorted(skills_dir.iterdir()) if p.is_dir()]
    if names != ["gravity-architect"]:
        report.error(f"skills/ doit contenir uniquement 'gravity-architect/' (trouvé : {names}).")
        return

    skill_md = skills_dir / "gravity-architect" / "SKILL.md"
    if not skill_md.is_file():
        report.error("skills/gravity-architect/SKILL.md introuvable.")
        return

    raw_bytes = _check_markdown_hygiene(
        skill_md, "skills/gravity-architect/SKILL.md", 6000, report
    )
    txt = raw_bytes.decode("utf-8", errors="replace")
    fm_match = re.match(r"^\s*---\r?\n(.*?)\r?\n---\r?\n", txt, re.DOTALL)
    if not fm_match:
        report.error("skills/gravity-architect/SKILL.md : frontmatter YAML manquant.")
        return
    fm = fm_match.group(1)
    if not re.search(r"^name:\s*gravity-architect\s*$", fm, re.MULTILINE):
        report.error("skills/gravity-architect/SKILL.md : 'name: gravity-architect' manquant.")
    desc_m = re.search(r"^description:\s*(.+)$", fm, re.MULTILINE)
    if not desc_m or not desc_m.group(1).strip():
        report.error("skills/gravity-architect/SKILL.md : 'description' manquante ou vide.")


def _check_markdown_hygiene(
    path: Path, label: str, max_bytes: int, report: Report
) -> bytes:
    """Vérifie UTF-8 sans BOM, LF et le budget octets maximal d'un fichier Markdown."""
    raw_bytes = path.read_bytes()
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        report.error(f"{label} ne doit pas contenir de BOM UTF-8.")
    if b"\r\n" in raw_bytes:
        report.error(f"{label} doit utiliser des fins de ligne LF (\\n), CRLF détecté.")
    if len(raw_bytes) > max_bytes:
        report.error(f"{label} dépasse {max_bytes} octets ({len(raw_bytes)}).")
    return raw_bytes


def _validate_rules_and_templates(root: Path, report: Report) -> None:
    rules_file = root / "rules" / "AGENTS.md"
    if not rules_file.is_file():
        report.error("rules/AGENTS.md introuvable.")
    else:
        raw_bytes = _check_markdown_hygiene(
            rules_file, "rules/AGENTS.md", 1000, report
        )
        if 600 < len(raw_bytes) <= 1000:
            report.warn(
                f"rules/AGENTS.md pèse {len(raw_bytes)} octets (cible recommandée : <= 600 octets)."
            )
        rules_txt = raw_bytes.decode("utf-8", errors="replace")
        if rules_txt.lstrip().startswith("---"):
            report.error("rules/AGENTS.md ne doit pas contenir de frontmatter YAML.")

    if root.name == "plugin" and (root.parent / "AGENTS.md").is_file():
        _check_markdown_hygiene(
            root.parent / "AGENTS.md", "AGENTS.md (racine)", 2500, report
        )

    templates_dir = root / "templates"
    if not templates_dir.is_dir():
        report.error("Dossier requis manquant : templates/")
        return

    for tpl_name in REQUIRED_TEMPLATES:
        if not (templates_dir / tpl_name).is_file():
            report.error(f"Template requis manquant : templates/{tpl_name}")

    tpl_agents = templates_dir / "AGENTS.md"
    if tpl_agents.is_file():
        _check_markdown_hygiene(tpl_agents, "templates/AGENTS.md", 2500, report)

    tpl_cfg = templates_dir / "projects.json"
    if tpl_cfg.is_file():
        try:
            data = json.loads(tpl_cfg.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("schema_version") != 5:
                report.error("templates/projects.json doit définir schema_version=5.")
            elif "privacy" in data:
                priv = data["privacy"]
                if not isinstance(priv, dict) or not isinstance(priv.get("public_mode"), bool):
                    report.error("templates/projects.json : 'privacy.public_mode' doit être un booléen.")
        except Exception as exc:
            report.error(f"templates/projects.json invalide : {exc}")


def _run_e2e_dry_run(root: Path, report: Report) -> None:
    init_script = root / "scripts" / "init_workspace.py"
    sync_script = root / "scripts" / "sync_tracking.py"
    if not init_script.is_file() or not sync_script.is_file():
        report.error("Scripts init_workspace.py ou sync_tracking.py manquants.")
        return

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        demo_repo = tmp_path / "demo-app"
        demo_repo.mkdir(parents=True)
        (demo_repo / "package.json").write_text(
            '{"name": "demo-app", "version": "1.2.3"}\n', encoding="utf-8"
        )
        ws_dir = tmp_path / "atelier"

        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env.pop("GRAVITY_ARCHITECT_WORKSPACE", None)

        p_init = subprocess.run(
            [
                sys.executable,
                "-B",
                str(init_script),
                "--workspace",
                str(ws_dir),
                "--name",
                "Atelier Dry-Run",
                "--project",
                f"demo={demo_repo}",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=10,
            check=False,
        )
        if p_init.returncode != 0:
            report.error(f"Dry-run init_workspace.py échoué : {p_init.stderr or p_init.stdout}")
            return

        p_sync = subprocess.run(
            [
                sys.executable,
                "-B",
                str(sync_script),
                "--workspace",
                str(ws_dir),
                "--offline",
                "--check",
                "--print-delta",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=10,
            check=False,
        )
        if p_sync.returncode != 0:
            report.error(f"Dry-run sync_tracking.py échoué : {p_sync.stderr or p_sync.stdout}")
            return
        if "EDITORIAL_UPDATE_REQUIRED" not in p_sync.stdout and "NO_EDITORIAL_CHANGES" not in p_sync.stdout:
            report.error(f"Sortie inattendue du dry-run sync_tracking.py : {p_sync.stdout!r}")


def validate_plugin(root: Path, report: Report) -> None:
    """Audite la structure, le manifeste, le contrat module, les templates, la stdlib et l'absence de fuites."""
    _validate_manifest(root, report)
    _validate_module_contract(root, report)
    _validate_skills(root, report)
    _validate_rules_and_templates(root, report)

    for sub in ("assets", "config", "rules", "scripts", "skills", "templates"):
        if not (root / sub).is_dir():
            report.error(f"Dossier requis manquant : {sub}/")

    if not (root / "README.md").is_file():
        report.error("README.md manquant à la racine du plugin.")

    for py_file in sorted(root.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        _check_stdlib_only(py_file, report)

    for fpath in sorted(root.rglob("*")):
        if not fpath.is_file() or "__pycache__" in fpath.parts:
            continue
        if fpath.suffix.lower() not in (".py", ".md", ".json", ".svg"):
            continue
        content = fpath.read_text(encoding="utf-8", errors="replace")
        if FORBIDDEN_MOD_RE.search(content):
            report.error(f"Jargon interdit détecté dans {fpath}")
        for label, rx in PRIVATE_LEAK_RES:
            if rx.search(content):
                report.error(f"Fuite spécifique détectée ({label}) dans {fpath}")

    _run_e2e_dry_run(root, report)


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="Validateur Gravity Architect")
    parser.add_argument("--strict", action="store_true", help="Échoue également sur les avertissements.")
    parser.add_argument(
        "--plugin-root",
        type=Path,
        default=PLUGIN_ROOT_DEFAULT,
        help="Racine du plugin gravity-architect à auditer.",
    )
    args = parser.parse_args(argv)
    plugin_root = args.plugin_root.expanduser().resolve()

    report = Report()
    validate_plugin(plugin_root, report)

    for info in report.infos:
        print(f"[INFO]  {info}")
    for err in report.errors:
        print(f"[ERROR] {err}")
    for warn in report.warnings:
        print(f"[WARN]  {warn}")

    if report.ok(args.strict):
        print(f"[PASS] Validation Plugin réussie (0 erreur, {len(report.warnings)} avertissement).")
        return 0
    print(
        f"[FAIL] Validation Plugin échouée ({len(report.errors)} erreur(s), {len(report.warnings)} avertissement(s))."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
