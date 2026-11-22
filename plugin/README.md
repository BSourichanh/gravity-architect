# Plugin Gravity Architect

Plugin Antigravity générique (**100 % bibliothèque standard Python 3**) pour piloter un atelier de conception multi-projets, produire des spécifications (`specs/`), préparer des briefs d'exécution autonomes (`handoffs/`), maintenir une couche **Hot / Cold** sous budgets tokens et synchroniser en lecture seule l'état des dépôts suivis.

## Commandes `/gravity-architect`

- `/gravity-architect init [--workspace <dir>] [--preset generic|antigravity-plugin]` : initialise un atelier de conception autonome (`AGENTS.md`, `ECOSYSTEM.md`, `projects.json`, `specs/`, `handoffs/`, `tracking/`, `archives/`).
- `/gravity-architect [sync] [--offline] [--check] [--full] [--ack-editorial] [--commit]` : synchronise en lecture seule les dépôts déclarés dans `projects.json`, met à jour les blocs `<!-- AUTO:START/END -->` à 0 token, produit un micro-delta compact et n'édite que les `Cibles éditoriales LLM` nécessaires.
- `/gravity-architect status` : synthétise l'état courant à partir de `tracking/snapshots/delta.md` (ou `ECOSYSTEM.md`) sans relancer de collecte.
- `/gravity-architect spec <slug>` · `/gravity-architect handoff <projet> <slug>` · `/gravity-architect archive <slug>` : cadrent, découpent et clôturent les artefacts de conception.

## Suivi multi-projets, contrat module & mode public

- **Contrat module Gravity :** `config/module.json` (`schema_version: 1`, `id: "architect"`) avec résolution centralisée `default_architect_home()` (`$GRAVITY_ARCHITECT_HOME` > `$GRAVITY_HOME/architect` > `~/.gemini/gravity/architect`), sans altérer la précédence atelier (`--workspace` > `$GRAVITY_ARCHITECT_WORKSPACE` > `.`).
- **Auto-détection manifeste plugin :** `plugin/plugin.json` d'abord, puis `{project_id}-plugin/plugin.json`, puis `plugin.json` (avec dérivation automatique de `validator_script`).
- **Versions multi-formats :** `plugin.json`, `package.json`, `pyproject.toml`, `Cargo.toml`, `setup.cfg`, `VERSION` / `.txt` ou clé JSON personnalisée (`version_json_path`).
- **Git branch-aware :** suivi `main` vs `dev`, dernier tag sur `main`, commits non tagués hors merges (`--no-merges`), `[Unreleased]` vs dernière release dans `CHANGELOG.md`, et WIP hors chemins runtime ignorés.
- **Mode public (`privacy.public_mode`) :** opt-in (`false` par défaut) dans `projects.json` ; lorsqu'il est à `true`, `ECOSYSTEM.md` ne liste que les plugins installés des projets suivis, n'émet pas d'alertes `orphan_plugin_dirs` pour les répertoires tiers, et masque/omet les chemins absolus machine (`home`, `agy_path`, `plugins_dir`, `install_path`, chemins dépôts) dans `ECOSYSTEM.md`, `tracking/projects/*.md`, `ecosystem_snapshot.md` et `delta.md`.
- **Options activables par configuration (`projects.json`) :**
  - Règles de conformité personnalisées (`compliance`) ou preset `antigravity-plugin` (audit `plugin.json` 9 champs, `config.json` `enabled`, empreinte du contenu installé hors adaptations OS).
  - Veilles technologiques (`watches`) de type `markdown-changelog` ou `antigravity-changelog`.

Exemple minimal de projet plugin et mode public dans `projects.json` :

```json
{
  "schema_version": 5,
  "default_preset": "antigravity-plugin",
  "privacy": { "public_mode": false },
  "projects": [
    {
      "id": "mon-plugin",
      "path": "../mon-plugin",
      "plugin_manifest": "plugin/plugin.json",
      "validator_script": "plugin/scripts/validate.py"
    }
  ]
}
```
