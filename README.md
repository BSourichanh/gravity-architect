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
python plugin/scripts/init_workspace.py --workspace ./mon-atelier --project app=../mon-app
python plugin/scripts/sync_tracking.py --workspace ./mon-atelier --print-delta
python plugin/scripts/sync_tracking.py --workspace ./mon-atelier --offline --ack-editorial --print-delta
```

Dans Antigravity, utilisez ensuite `/gravity-architect [init|sync|status|spec|handoff|archive]` (voir [`plugin/README.md`](plugin/README.md)).

### Contrat module & confidentialité (`v0.2.0`)
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

- [`CHANGELOG.md`](CHANGELOG.md) — Historique des releases (`v0.2.0`)
- [`plugin/README.md`](plugin/README.md) — Guide complet du plugin et des commandes `/gravity-architect`
- [`AGENTS.md`](AGENTS.md) — Charte, invariants et vérifications obligatoires

---

## Licence

Distribué sous licence MIT — voir [`LICENSE`](LICENSE) pour plus de détails.
