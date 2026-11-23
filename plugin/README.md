# Plugin Gravity Architect

Plugin Antigravity générique (**100 % bibliothèque standard Python 3**) pour piloter un atelier de conception multi-projets, produire des spécifications (`specs/`), préparer des briefs d'exécution autonomes (`handoffs/`), maintenir une couche **Hot / Cold** sous budgets tokens et synchroniser en lecture seule l'état des dépôts suivis.

## Commandes `/gravity-architect`

- `/gravity-architect init [--workspace <dir>] [--name "<Titre>"] [--preset generic|antigravity-plugin]` : initialise un atelier de conception autonome (`AGENTS.md`, `ECOSYSTEM.md`, `projects.json`, `specs/`, `handoffs/`, `audits/code/`, `audits/agents/`, `tracking/`, `archives/`) via découverte guidée (`init_workspace.py --discover --json`, `ask_question`, presets `--watch antigravity` / `--watch-url` / `--public-mode`) puis première synchronisation.
- `/gravity-architect add <chemin...>` : ajoute de façon incrémentale et *fail-closed* un ou plusieurs dépôts (`<chemin>` ou `id=chemin`) via `init_workspace.py --add`, crée leur fiche `tracking/projects/<id>.md` puis lance la synchronisation éditoriale.
- `/gravity-architect [sync] [--offline] [--check] [--full] [--ack-editorial] [--commit]` : synchronise en lecture seule les dépôts déclarés dans `projects.json`, met à jour les blocs `<!-- AUTO:START/END -->` à 0 token (dont le résumé compact des handoffs archivés et la comparaison SemVer CLI `en avance` / `écart`), produit un micro-delta compact et n'édite que les `Cibles éditoriales LLM` nécessaires.
- `/gravity-architect status` : synthétise l'état courant à partir de `tracking/snapshots/delta.md` (ou `ECOSYSTEM.md`) sans relancer de collecte.
- `/gravity-architect spec <slug>` · `/gravity-architect handoff <projet> <slug>` · `/gravity-architect archive <slug>` : cadrent, découpent et clôturent les artefacts de conception.
- `/gravity-architect audit [projet|all]` : exécute un audit **Code & Architecture** en lecture seule absolue sur le ou les dépôts suivis (sans audit agent ni métriques), produit `audits/code/<YYYY-MM-DD>-audit-code-<cible>.md` depuis `audits/code/_TEMPLATE.md` (`CODE-XX-N` `P0`/`P1`/`P2`) et met à jour le journal `audits/code/README.md` (strictement séparé d'`audits/agents/`).

### Options CLI d'initialisation (`scripts/init_workspace.py`)
- `--discover [--scan-dir <dir>] [--json]` : liste en lecture seule (profondeur 1, hors `.xxx` et dossier atelier) les dépôts Git candidats avec auto-détection complète (`id`, `name`, `path`, `preset`, `plugin_manifest`, `validator_script`, `main_branch`, `default_dev_branch`, `role`, `has_changelog`, `has_agents`).
- `--project <chemin|id=chemin>` : accepte un chemin nu avec auto-détection complète ou `id=chemin` ; `--preset` devient optionnel (surcharge explicite sinon auto-détecté par projet).
- `--add <chemin|id=chemin>` *(répétable)* : ajoute des projets à un atelier existant (`projects.json` requis, refus *fail-closed* des doublons d'`id` ou de chemin résolu).
- `--watch antigravity` / `--watch-url id=url` / `--public-mode` / `--run-sync [--offline]` : presets de veille (avec `tracking/antigravity/IMPACT.md` généré depuis `templates/impact-template.md`), mode confidentiel et synchronisation opt-in.
- **Garde-fou dépôt produit (`--force` / `--json`) :** `init_workspace.py` refuse d'initialiser un nouvel atelier dans un dépôt contenant `.git` et un manifeste code/plugin sans `projects.json` existant, sauf avec `--force`.

### Options CLI de synchronisation (`scripts/sync_tracking.py`)
- **Repli centralisé :** après `--config` > `--workspace` > `$GRAVITY_ARCHITECT_WORKSPACE` > `cwd` > sous-dossier atelier unique, `resolve_workspace_root()` se replie sur `default_architect_home()` si `projects.json` y existe.
- `--max-stdout-bytes <N>` *(défaut `8192`, `0` = illimité)* : évite la troncature `stdout` lors de `--print-delta` en imprimant un résumé compact (statut exact, `Cibles éditoriales LLM`, statistiques, chemin `tracking/snapshots/delta.md`) sous le seuil.
- `--max-changelog-lines <N>` *(défaut `45`)* : borne le nombre de lignes extraites par section `CHANGELOG.md`.

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
