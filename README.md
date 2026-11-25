# Gravity Architect

> ### Démarrage 2 min & Place dans l'écosystème
> - **Place :** **Palier 3 — Multi-projets** *(prérequis : [`gravity`](https://github.com/BSourichanh/gravity) Core)*
> - **Rôle :** Orchestrer un atelier de conception Hot/Cold (`specs/`, `tasks/`, `audits/code/`) et suivre plusieurs dépôts en lecture seule.
> - **Démarrage :** `/gravity-architect init` puis `/gravity-architect sync`
> - **Hub documentaire (`gravity/docs/`) :** [Démarrage rapide](https://github.com/BSourichanh/gravity/blob/main/docs/getting-started.md) · [Parcours utilisateur](https://github.com/BSourichanh/gravity/blob/main/docs/user-journey.md) · [Aide-mémoire commandes](https://github.com/BSourichanh/gravity/blob/main/docs/command-cheatsheet.md) · [Dépannage & cycle de vie](https://github.com/BSourichanh/gravity/blob/main/docs/troubleshooting-and-lifecycle.md)

> Plugin Antigravity générique (**100 % bibliothèque standard Python 3.10+**) de l'écosystème [Gravity](https://github.com/BSourichanh/gravity) (aux côtés de [Gravity Metrics](https://github.com/BSourichanh/gravity-metrics)) dédié au cadrage d'architecture, au brainstorming multi-projets, à la production de spécifications (`specs/`) et de tasks d'exécution autonomes par vagues (`tasks/`), avec gestion **Hot / Cold**, mode confidentiel (`privacy.public_mode`) et synchronisation lecture seule des dépôts suivis.

---

## Arborescence

```text
gravity-architect/
├── AGENTS.md                        # Charte développeur du plugin (≤ 2 500 o)
├── CHANGELOG.md                     # Historique des releases (Keep a Changelog / SemVer)
├── LICENSE                          # Licence MIT
├── README.md                        # Documentation du dépôt plugin
├── install.py                       # Installeur / désinstalleur cross-platform
├── plugin/                          # Plugin Antigravity autonome
│   ├── plugin.json                  # Manifeste officiel (9 champs)
│   ├── config/module.json           # Contrat module Gravity (schema_version: 1)
│   ├── README.md                    # Guide utilisateur du plugin
│   ├── assets/logo.svg              # Logo carré 1:1
│   ├── hooks.json                   # Hook PreInvocation 0-token (/gravity-architect vide)
│   ├── hooks/                       # pre_invocation_architect.py
│   ├── rules/AGENTS.md              # Règle légère d'activation
│   ├── skills/gravity-architect/    # Skill /gravity-architect & references/workflows-and-hygiene.md
│   ├── templates/                   # Modèles d'ateliers Hot/Cold
│   ├── core/                        # Noyau SRP (io_utils, discovery, git_collector, watches, delta, renderers, waves)
│   └── scripts/                     # Façades CLI (atelier_status.py, sync_tracking.py, init_workspace.py) & validate.py
└── tests/                           # Tests unitaires (unittest)
```

---

## Installation

> Prérequis : **Python 3.10+** (100 % bibliothèque standard, zéro dépendance externe).

### Option 1 — Installeur automatique (Recommandé, Windows / macOS / Linux)

```bash
git clone https://github.com/BSourichanh/gravity-architect.git
cd gravity-architect
python install.py
```

[`install.py`](install.py) copie [`plugin/`](plugin/) vers `~/.gemini/config/plugins/gravity-architect/`, règle les permissions exécutables POSIX (`0755`) et exécute `validate.py --strict` sur une copie temporaire avant installation.

Commandes utiles :

```powershell
python install.py --check                                 # Vérifier l'environnement et l'état installé
python install.py --dry-run                               # Prévisualiser les opérations sans écrire
python install.py --force                                 # Mettre à jour ou réinstaller
python install.py --scope workspace --workspace <chemin>  # Installer dans un projet cible (.agents/plugins/)
python install.py --uninstall                             # Désinstaller proprement
```

### Option 2 — Antigravity CLI (`agy`)

```bash
python install.py --method agy
# ou directement :
agy plugin validate ./plugin --strict
agy plugin install ./plugin
```

---

## Utilisation rapide

Dans un atelier cible (initialisé via `/gravity-architect init` ou `init_workspace.py`) :

```powershell
python plugin/scripts/init_workspace.py --workspace ./mon-atelier --discover --json
python plugin/scripts/init_workspace.py --workspace ./mon-atelier --project ../mon-app --watch antigravity
python plugin/scripts/init_workspace.py --workspace ./mon-atelier --add ../autre-projet
python plugin/scripts/sync_tracking.py --workspace ./mon-atelier --print-delta
python plugin/scripts/sync_tracking.py --workspace ./mon-atelier --offline --ack-editorial --print-delta
```

Dans Antigravity, utilisez ensuite `/gravity-architect [init|add|sync|status|spec|task|archive|audit]` (voir [`plugin/README.md`](plugin/README.md)).

### Wave 2 : `atelier_status.py`, hook `PreInvocation` 0-token, hygiène `INT-07`, validateur `INT-01/03/06` & cycle 4 phases natif (`Unreleased`)
- **État consultatif 0-token (`plugin/scripts/atelier_status.py` + `plugin/hooks.json` / `plugin/hooks/pre_invocation_architect.py`) :** `/gravity-architect` sans argument s'exécute en `PreInvocation` lecture seule (`0` écriture disque, `0` capture `gravity-metrics`) : résout l'atelier (`resolve_workspace_root`), liste specs et tasks actives par vague/statut, collecte les alertes d'hygiène (`INT-07`) et propose les actions suggérées.
- **Cycle 4 phases 100 % natif & checkpoint hybride :** `/gravity-architect "<instruction>"` formalise Conception (`research` + `/grill-me` + `/plan`) → Planification (ancres `research`, `tasks/` `<= 5` fichiers code, profil `quick`|`standard`, `core/waves.py --check-waves`, 1 checkpoint unique via artefact `RequestFeedback=True` et/ou `ask_question` explicite) → Production (exécution par défaut via outil natif `swarm` / `/swarm` optimisé en `git worktree` isolés depuis `wave_plan_v1`, ou `run_workflow` en opt-in explicite, + mini-checkpoint `dev` et `/compact` racine `> 250k`) → Validation (`verify_commands` ex. `audit_ecosystem.py --verify-parallel --strict`, commit/push `dev`, archive, docs écosystème, réinstall fin Validation uniquement, récap, `gravity-metrics`).
- **Hygiène `INT-07` (`core/delta.py` + `sync_tracking.py`) :** `collect_atelier_hygiene_alerts()` signale de façon non bloquante les dérives `*_TEMPLATE.md`, les liens Markdown relatifs cassés ou `file:` dans les fichiers Hot / `audits/*/README.md` et les dépassements de budgets `AGENTS.md` / `ECOSYSTEM.md`.
- **Validateur `INT-01/03/06` & portabilité Windows (`validate.py` + `install.py`) :** validation SemVer stricte, `plugin.json` 9 champs, `config/module.json` (`schema_version: 1`), `suggestedPrompts` (`/cmd — résumé` `<= 100` car.), `hooks.json` et scripts `.py`, BOM/LF sur tout `.py/.md/.json/.svg`, liens relatifs/`file:` dans `README.md`/`SKILL.md`/`references/*.md`, et `--fix-python-cmd` automatique lors de `install.py` sur Windows sans `python3` réel.

### Wave 1 : `tasks/`, validation DAG/vagues (`core/waves.py`), posture & modularité (`Unreleased`)
- **Unification `tasks/` & validation des vagues (`plugin/core/waves.py`) :** remplacement de `handoffs/` par `tasks/` (`plugin/templates/task-template.md`, bloc `project-tasks:<id>`, `pending_tasks`/`archived_tasks`), enrichissement de `parse_artifact_file()` (`id`, `wave`, `wave_raw`, `dependencies`, `workflow_profile`, `target_files`, `anchors` hybrides `::` / `~L`), exposition de `artifacts` dans `delta` et rendu `## Artefacts actifs` par vague dans `render_delta_markdown()`, et validateur CLI `core/waves.py --check-waves` (*fail-closed* : `wave >= 1`, `<= 1` task/dépôt/vague, fichiers cibles disjoints, DAG acyclique 3 couleurs, ancres hybrides et `<= 5` fichiers code).
- **Posture Architecte (Code RO + clôture auto sur `dev` *fail-closed*) :** `plugin/rules/AGENTS.md`, `plugin/skills/gravity-architect/SKILL.md` et `plugin/templates/AGENTS.md` distinguent strictement la lecture seule sur le code source des dépôts suivis (implémentation en worktree isolé via `/swarm` par défaut depuis `wave_plan_v1`, ou `run_workflow` en opt-in) de la clôture automatique sur `dev` (après plan/spec validé, vague terminée, revue propre et `100 %` de vérifs vertes — *fail-closed* global : `git add`/`commit` sur `dev`, `git push origin dev` sans `--force`, `ecosystem_install.py --update --modules <...> --strict`, archivage atelier et `gravity-metrics`). `merge dev -> main`, tag SemVer et release restent sur accord humain explicite, et un simple `/gravity-architect sync` (même `--commit`) ne fait ni `commit` suivi ni `git push`.
- **Registre centralisé (`<architect_home>/ateliers.json`) :** `init_workspace.py` (`init`, `--add`) et `sync_tracking.py` (hors `--check` / `--dry-run` et `--discover`) enregistrent automatiquement chaque atelier valide (`projects.json` + `ECOSYSTEM.md`, ordre MRU, max `20`, écriture atomique) dans `<architect_home>/ateliers.json` (`$GRAVITY_ARCHITECT_HOME` > `$GRAVITY_HOME/architect` > `~/.gemini/gravity/architect`) sans écrire dans le workspace cible. Opt-out via `GRAVITY_ARCHITECT_SKIP_REGISTRY=1` ; `resolve_workspace_root()` reste inchangé.
- **Architecture SRP/DRY (`plugin/core/` v0.5.1+) :** noyau modulaire sous `plugin/core/` (`io_utils.py`, `discovery.py`, `git_collector.py`, `watches.py`, `delta.py`, `renderers.py`, `waves.py`, tous ≤ 650 L, 100 % stdlib Python 3.10+, écriture atomique UTF-8 sans BOM / LF) et façades `plugin/scripts/sync_tracking.py` (≤ 250 L) / `init_workspace.py` (≤ 450 L).
- **Hygiène tokens, exécution native & `references/` :** compactage de `plugin/skills/gravity-architect/SKILL.md` (`<= 6 000 o`) avec déport des procédures détaillées dans `plugin/skills/gravity-architect/references/workflows-and-hygiene.md` (statut `rédigé, non déployé`, lancement par défaut `/swarm` optimisé avec `run_workflow` en opt-in explicite, routage `quick`/`standard`, no-op Plan Mode sans `exit_plan_mode`, délégation `research`, `/compact` post-tasks et `> 250k` tokens racine, garde WIP sur `--ack-editorial`, clôture via `ecosystem_install.py --update --modules <...> --strict`, et proposition `../` sur `/gravity-architect add`), contrôlé par `plugin/scripts/validate.py --strict`.
- **Onboarding fluide sur workspace vide :** sur dossier sans `./projects.json`, `/gravity-architect` bascule sur `init` guidé (1 `ask_question` incluant atelier vide `0` projet / `../` / chemins directs), `init_workspace.py --workspace . --run-sync --offline` initialise à `0` projet en 1 commande (nom dérivé du dossier courant hors noms génériques via `_derive_default_workspace_name()`), et `plugin/templates/ECOSYSTEM.md` oriente vers `/gravity-architect add <chemin>` et `/gravity-architect spec <slug>`.
- **Clôture finale optionnelle (`gravity-metrics`) :** `plugin/skills/gravity-architect/references/workflows-and-hygiene.md` (§3) et `SKILL.md` (`archive <slug>`) formalisent la séquence ordonnée de fin de cycle (vague terminée, revue propre et `100 %` vérifs vertes *fail-closed* → auto `commit`/`push origin dev` non-force + `ecosystem_install.py --update` → archivage atelier + `sync_tracking.py --offline --ack-editorial --print-delta` → clôture finale optionnelle `gravity-metrics` via `cli.py archive <conversation_id>` / `--update-sealed`, sans `--force`, en no-op silencieux si absent).

### Garde-fou dépôt produit, principes & ergonomie CLI (`v0.5.0`)
- **Garde-fou `init_workspace.py` :** refuse (sauf `--force` ou atelier `projects.json` déjà existant) d'initialiser un atelier dans un dépôt produit (`.git` + manifeste code/plugin tel que `plugin/plugin.json`, `pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, `pom.xml`, `setup.py`), avec prise en charge `--json`.
- **Principes d'ingénierie dans `templates/AGENTS.md` :** l'invariant `Challenger` intègre explicitement `KISS, YAGNI, DRY, SOLID, CUPID`.
- **Ergonomie `sync_tracking.py` :** repli vers `default_architect_home()` (`$GRAVITY_ARCHITECT_HOME` > `$GRAVITY_HOME/architect` > `~/.gemini/gravity/architect`) après détection `cwd` ; options `--max-stdout-bytes` (défaut `8192`, `0` = illimité, résumé compact pointant vers `tracking/snapshots/delta.md`) et `--max-changelog-lines` (défaut `45`).
- **Hygiène `validate.py --strict` :** plafond strict `plugin/rules/AGENTS.md <= 1 000 o` (avertissement bloquant sous `--strict` au-delà de `600 o`, compacté `<= 520 o`), contrôle BOM/LF/budget sur `plugin/skills/gravity-architect/SKILL.md` (`<= 6 000 o`, compacté `<= 5 800 o`), `AGENTS.md` racine (`<= 2 500 o`) et `plugin/templates/AGENTS.md`.

### Audits Code & Architecture & suivi compact (`v0.4.0`)
- **Audits isolés (`audits/code/`) :** `init_workspace.py` déploie `audits/code/README.md`, `audits/code/_TEMPLATE.md` et `audits/agents/.gitkeep` ; le dossier `audits/code/` reste strictement séparé d'`audits/agents/`.
- **Commande `/gravity-architect audit [projet|all]` :** réalise un audit **Code & Architecture** en lecture seule sur les dépôts suivis, rédige `audits/code/<YYYY-MM-DD>-audit-code-<cible>.md` (`CODE-XX-N` `P0`/`P1`/`P2`) et met à jour le journal `audits/code/README.md`.
- **Handoffs archivés compacts & SemVer CLI :** `ECOSYSTEM.md` résume `handoffs/archive/` sur 1 ligne, les fiches projet limitent l'historique archivé aux 3 plus récents, et la comparaison SemVer CLI distingue `en avance` et `écart` pour éviter les fausses alertes.

### Découverte, presets & confidentialité (`v0.3.0`)
- **Découverte & ajout incrémental (`init_workspace.py`) :** `--discover [--scan-dir <dir>] [--json]` scanne en lecture seule (profondeur 1, sans jamais sortir du dossier cible implicitement) et `--add <chemin|id=chemin>` ajoute des projets *fail-closed* à un atelier existant.
- **Presets intégrés :** `--project <chemin>` auto-détecte manifeste plugin, branches (`main`/`master`/`dev`) et rôle ; `--watch antigravity` configure la veille officielle Google Antigravity (`tracking/antigravity/IMPACT.md` depuis `templates/impact-template.md`), `--watch-url id=url` ajoute un changelog Markdown, `--public-mode` active `privacy.public_mode` et `--run-sync --offline` lance la synchro initiale à la demande.
- **Contrat module :** [`plugin/config/module.json`](plugin/config/module.json) (`id: "architect"`, stockage par défaut `$GRAVITY_ARCHITECT_HOME` > `$GRAVITY_HOME/architect` > `~/.gemini/gravity/architect` via `default_architect_home()`).
- **Auto-détection `plugin_manifest` :** `plugin/plugin.json` en priorité, puis `{id}-plugin/plugin.json`, puis `plugin.json` (et dérivation automatique de `validator_script`).
- **Mode public (`privacy.public_mode`):** option opt-in dans `projects.json` (`{"privacy": {"public_mode": true}}` ou `"public_mode": true`) pour filtrer `ECOSYSTEM.md` aux seuls plugins suivis, supprimer les alertes `orphan_plugin_dirs` des répertoires tiers et masquer les chemins absolus machine dans les Markdown générés.

---

## Vérifications développeur

```powershell
python plugin/scripts/validate.py --strict
agy plugin validate ./plugin --strict
python -m unittest discover -s tests -p "test_*.py" -v
```

---

## Documentation & Releases

- [`CHANGELOG.md`](CHANGELOG.md) — Historique des releases (`v0.5.1`)
- [`plugin/README.md`](plugin/README.md) — Guide complet du plugin et des commandes `/gravity-architect`
- [`AGENTS.md`](AGENTS.md) — Charte, invariants et vérifications obligatoires

---

## Licence

Distribué sous licence MIT — voir [`LICENSE`](LICENSE) pour plus de détails.
