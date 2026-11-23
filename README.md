# Gravity Architect

> Plugin Antigravity générique (**100 % bibliothèque standard Python 3.10+**) de l'écosystème [Gravity](https://github.com/BSourichanh/gravity) (aux côtés de [Gravity Metrics](https://github.com/BSourichanh/gravity-metrics)) dédié au cadrage d'architecture, au brainstorming multi-projets, à la production de spécifications (`specs/`) et de briefs autonomes (`handoffs/`), avec gestion **Hot / Cold**, mode confidentiel (`privacy.public_mode`) et synchronisation lecture seule des dépôts suivis.

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
│   ├── rules/AGENTS.md              # Règle légère d'activation
│   ├── skills/gravity-architect/    # Skill /gravity-architect
│   ├── templates/                   # Modèles d'ateliers Hot/Cold
│   └── scripts/                     # sync_tracking.py (v5), init_workspace.py, validate.py
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

Dans Antigravity, utilisez ensuite `/gravity-architect [init|add|sync|status|spec|handoff|archive|audit]` (voir [`plugin/README.md`](plugin/README.md)).

### Garde-fou dépôt produit, principes & ergonomie CLI (`Unreleased`)
- **Garde-fou `init_workspace.py` :** refuse (sauf `--force` ou atelier `projects.json` déjà existant) d'initialiser un atelier dans un dépôt produit (`.git` + manifeste code/plugin tel que `plugin/plugin.json`, `pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, `pom.xml`, `setup.py`), avec prise en charge `--json`.
- **Principes d'ingénierie dans `templates/AGENTS.md` :** l'invariant `Challenger` intègre explicitement `KISS, YAGNI, DRY, SOLID, CUPID`.
- **Ergonomie `sync_tracking.py` :** repli vers `default_architect_home()` (`$GRAVITY_ARCHITECT_HOME` > `$GRAVITY_HOME/architect` > `~/.gemini/gravity/architect`) après détection `cwd` ; options `--max-stdout-bytes` (défaut `8192`, `0` = illimité, résumé compact pointant vers `tracking/snapshots/delta.md`) et `--max-changelog-lines` (défaut `45`).
- **Hygiène `validate.py --strict` :** plafond strict `plugin/rules/AGENTS.md <= 1 000 o` (note info au-delà de `600 o`), contrôle BOM/LF/budget sur `AGENTS.md` racine (`<= 2 500 o`) et `plugin/templates/AGENTS.md`.

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

- [`CHANGELOG.md`](CHANGELOG.md) — Historique des releases (`v0.4.0`)
- [`plugin/README.md`](plugin/README.md) — Guide complet du plugin et des commandes `/gravity-architect`
- [`AGENTS.md`](AGENTS.md) — Charte, invariants et vérifications obligatoires

---

## Licence

Distribué sous licence MIT — voir [`LICENSE`](LICENSE) pour plus de détails.
