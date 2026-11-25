# Plugin Gravity Architect

> ### Démarrage 2 min & Place dans l'écosystème
> - **Place :** **Palier 3 — Multi-projets** *(prérequis : [`gravity`](https://github.com/BSourichanh/gravity) Core)*
> - **Rôle :** Orchestrer un atelier de conception Hot/Cold (`specs/`, `tasks/`, `audits/code/`) et suivre plusieurs dépôts en lecture seule.
> - **Démarrage :** `/gravity-architect init` puis `/gravity-architect sync`
> - **Hub documentaire (`gravity/docs/`) :** [Démarrage rapide](https://github.com/BSourichanh/gravity/blob/main/docs/getting-started.md) · [Parcours utilisateur](https://github.com/BSourichanh/gravity/blob/main/docs/user-journey.md) · [Aide-mémoire commandes](https://github.com/BSourichanh/gravity/blob/main/docs/command-cheatsheet.md) · [Dépannage & cycle de vie](https://github.com/BSourichanh/gravity/blob/main/docs/troubleshooting-and-lifecycle.md)

Plugin Antigravity générique (**100 % bibliothèque standard Python 3**) organisé autour d'un noyau modulaire SRP (`core/`) et de façades CLI rétrocompatibles (`scripts/`) pour piloter un atelier de conception multi-projets, produire des spécifications (`specs/`), préparer des tasks d'exécution autonomes par vagues (`tasks/`), maintenir une couche **Hot / Cold** sous budgets tokens et synchroniser en lecture seule l'état des dépôts suivis.

## Commandes `/gravity-architect`

- `/gravity-architect` *(sans argument)* : hook `PreInvocation` zéro-token lecture seule via `scripts/atelier_status.py` (`0` écriture, `0` capture `gravity-metrics`) ; synthétise specs, tasks actives par vague/statut, alertes d'hygiène (`INT-07`) et actions suggérées (`reprendre`, `/gravity-architect <instruction>`, `/gravity-architect sync` ou `init`).
- `/gravity-architect "<instruction>"` : exécute le cycle structuré en **4 phases** : **Conception** (`research` + `/grill-me` + `/plan`) → **Planification** (ancres `research`, `tasks/` `<= 5` fichiers code, profil `quick`|`standard`, `core/waves.py --check-waves`, 1 checkpoint unique via artefact `RequestFeedback=True` et/ou `ask_question` explicite) → **Production** (compilation neutre `core/waves.py --export-wave <N>` vers `wave_plan_v1` exécutée en `git worktree` isolés via moteur workflow optionnel recommandé ou repli autonome natif sous-agents / `/swarm`, + mini-checkpoint `dev` et `/compact` racine `> 250k`) → **Validation** (`verify_commands` ex. `audit_ecosystem.py --verify-parallel --strict`, commit/push `dev`, archive, docs écosystème, réinstall fin Validation uniquement, récap, `gravity-metrics`).
- `/gravity-architect init [--workspace <dir>] [--name "<Titre>"] [--preset generic|antigravity-plugin]` : initialise un atelier de conception autonome (`AGENTS.md`, `ECOSYSTEM.md`, `projects.json`, `specs/`, `tasks/`, `audits/code/`, `audits/agents/`, `tracking/`, `archives/`) avec nom dérivé du dossier courant hors noms génériques (sauf `--name`), découverte guidée (`init_workspace.py --discover --json`, 1 `ask_question` incluant l'atelier vide `0` projet via `init_workspace.py --workspace . --run-sync --offline` sans `--ack-editorial`, presets `--watch antigravity` / `--watch-url` / `--public-mode`) puis première synchronisation (`ECOSYSTEM.md` oriente vers `/gravity-architect add <chemin>` et `/gravity-architect spec <slug>`).
- `/gravity-architect add [chemin...]` : ajoute de façon incrémentale et *fail-closed* un ou plusieurs dépôts (`<chemin>` ou `id=chemin`) via `init_workspace.py --add`, crée leur fiche `tracking/projects/<id>.md` puis lance la synchronisation éditoriale ; sans argument, propose `../` en 1re option recommandée si `projects.json` référence déjà des dépôts sous `../`.
- `/gravity-architect sync [--offline] [--check] [--full] [--ack-editorial] [--commit]` : si `./projects.json` est absent (hors sous-dossier atelier unique), bascule sur le flux `init` guidé ; sinon synchronise en lecture seule les dépôts déclarés dans `projects.json`, met à jour les blocs `<!-- AUTO:START/END -->` à 0 token (dont le résumé compact des tasks archivées, les alertes hygiène `INT-07` et la comparaison SemVer CLI `en avance` / `écart`), produit un micro-delta compact (avec artefacts actifs groupés par vague) et n'édite que les `Cibles éditoriales LLM` nécessaires (en Plan Mode, un `--check` à `NO_EDITORIAL_CHANGES` sans fichier auto-mis à jour répond directement sans `exit_plan_mode`, `--ack-editorial` reste interdit tant que du WIP non commité subsiste dans les dépôts suivis, et même `--commit` ne fait ni `commit` sur les dépôts suivis ni `git push`).
- `/gravity-architect status` : synthétise l'état courant à partir de `scripts/atelier_status.py` (ou `tracking/snapshots/delta.md` / `ECOSYSTEM.md`) sans relancer de collecte ni écrire sur disque.
- `/gravity-architect spec <slug>` · `/gravity-architect task <projet> <slug>` · `/gravity-architect archive <slug>` : cadrent, découpent par vagues (`core/waves.py --check-waves` : DAG acyclique, `<= 1` task/dépôt/vague, fichiers cibles disjoints, ancres hybrides `::` / `~L`, `<= 5` fichiers code) et clôturent les artefacts de conception (statut explicite `rédigé, non déployé` après création d'une task, proposition d'export `wave_plan_v1` via `--export-wave` ou de repli natif `/swarm` en 1 `ask_question` récapitulatif, puis séquence de clôture : vérifs vertes → `commit`/`push origin dev`/install → archivage + `--ack-editorial` → clôture finale optionnelle `gravity-metrics` selon `workflows-and-hygiene.md` §3, en no-op silencieux si absent).
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

- **Posture Architecte (Code RO & clôture auto sur `dev`) :** le code source des dépôts suivis reste strictement en lecture seule (implémentation en worktree isolé via contrat `wave_plan_v1` ou repli natif sous-agents / `/swarm`) ; après validation d'un plan/spec, vague terminée, revue propre et `100 %` de vérifications vertes (*fail-closed* global), la clôture sur `dev` (`git add`/`commit` sur `dev`, `git push origin dev` sans `--force`, `ecosystem_install.py --update --modules <...> --strict`, archivage atelier et `gravity-metrics`) s'enchaîne automatiquement, tandis que `merge dev -> main`, tag SemVer et release exigent un accord humain explicite (aucun `commit`/`push` automatique sur simple `sync`).
- **Progressive disclosure & hygiène tokens (`skills/gravity-architect/references/workflows-and-hygiene.md`) :** `SKILL.md` (`<= 6 000 o`) renvoie vers cette fiche de référence pour les workflows avancés (contrat `wave_plan_v1`, moteur workflow optionnel et repli natif `/swarm`, routage `quick`/`standard`, `exit_plan_mode` concis, délégation `research`, `/compact` post-tasks et dès `> 250k` tokens racine, et garde `--ack-editorial`).
- **Validation & export des vagues (`core/waves.py --check-waves` / `--export-wave <N>`) :** contrôle *fail-closed* des `tasks/` avant exécution (`wave` entier `>= 1`, `target_project` connu, `workflow_profile` `quick|standard|deep`, `<= 1` task/dépôt/vague, `target_files` disjoints dans la même vague, DAG acyclique avec `wave(dep) < wave(task)`, ancres hybrides `::` / `~L` et plafond `<= 5` fichiers code hors tests/docs) et compilation vers le manifeste neutre `wave_plan_v1` (`repo_root`, `expected_branch` résolus depuis `projects.json`).
- **Contrat module Gravity :** `config/module.json` (`schema_version: 1`, `id: "architect"`) avec résolution centralisée `default_architect_home()` (`$GRAVITY_ARCHITECT_HOME` > `$GRAVITY_HOME/architect` > `~/.gemini/gravity/architect`), sans altérer la précédence atelier (`--workspace` > `$GRAVITY_ARCHITECT_WORKSPACE` > `.`).
- **Registre centralisé (`<architect_home>/ateliers.json`) :** `init_workspace.py` (`init`, `--add`) et `sync_tracking.py` (hors `--check` / `--dry-run`) enregistrent automatiquement l'atelier valide (`projects.json` + `ECOSYSTEM.md`, ordre MRU, max `20` entrées, écriture atomique) dans `ateliers.json` (`schema_version: 1`). Définir `GRAVITY_ARCHITECT_SKIP_REGISTRY=1` pour désactiver l'écriture (ex. tests ou CI).
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
