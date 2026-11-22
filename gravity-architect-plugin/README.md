# Plugin Gravity Architect

Plugin Antigravity générique (**100 % bibliothèque standard Python 3**) pour piloter un atelier de conception multi-projets, produire des spécifications (`specs/`), préparer des briefs d'exécution autonomes (`handoffs/`), maintenir une couche **Hot / Cold** sous budgets tokens et synchroniser en lecture seule l'état des dépôts suivis.

## Commandes `/gravity-architect`

- `/gravity-architect init [--workspace <dir>] [--preset generic|antigravity-plugin]` : initialise un atelier de conception autonome (`AGENTS.md`, `ECOSYSTEM.md`, `projects.json`, `specs/`, `handoffs/`, `tracking/`, `archives/`).
- `/gravity-architect [sync] [--offline] [--check] [--full] [--ack-editorial] [--commit]` : synchronise en lecture seule les dépôts déclarés dans `projects.json`, met à jour les blocs `<!-- AUTO:START/END -->` à 0 token, produit un micro-delta compact et n'édite que les `Cibles éditoriales LLM` nécessaires.
- `/gravity-architect status` : synthétise l'état courant à partir de `tracking/snapshots/delta.md` (ou `ECOSYSTEM.md`) sans relancer de collecte.
- `/gravity-architect spec <slug>` · `/gravity-architect handoff <projet> <slug>` · `/gravity-architect archive <slug>` : cadrent, découpent et clôturent les artefacts de conception.

## Suivi multi-projets & formats supportés

- **Détection automatique d'atelier :** `--config`, `--workspace`, `$GRAVITY_ARCHITECT_WORKSPACE`, `.` (`projects.json` à la racine) ou sous-dossier unique contenant `projects.json` et `ECOSYSTEM.md`.
- **Versions multi-formats :** `plugin.json`, `package.json`, `pyproject.toml`, `Cargo.toml`, `setup.cfg`, `VERSION` / `.txt` ou clé JSON personnalisée (`version_json_path`).
- **Git branch-aware :** suivi `main` vs `dev`, dernier tag sur `main`, commits non tagués hors merges (`--no-merges`), `[Unreleased]` vs dernière release dans `CHANGELOG.md`, et WIP hors chemins runtime ignorés.
- **Options activables par configuration (`projects.json`) :**
  - Règles de conformité personnalisées (`compliance`) ou preset `antigravity-plugin` (audit `plugin.json` 9 champs, `config.json` `enabled`, empreinte du contenu installé hors adaptations OS).
  - Veilles technologiques (`watches`) de type `markdown-changelog` ou `antigravity-changelog`.
