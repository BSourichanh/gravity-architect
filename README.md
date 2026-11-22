# Gravity Architect

> Plugin Antigravity générique (**100 % bibliothèque standard Python 3.10+**) de l'écosystème [Gravity](https://github.com/BSourichanh/gravity) (aux côtés de [Gravity Metrics](https://github.com/BSourichanh/gravity-metrics)) dédié au cadrage d'architecture, au brainstorming multi-projets, à la production de spécifications (`specs/`) et de briefs autonomes (`handoffs/`), avec gestion **Hot / Cold** et synchronisation lecture seule des dépôts suivis.

---

## Arborescence

```text
gravity-architect/
├── AGENTS.md                        # Charte développeur du plugin (≤ 2 500 o)
├── CHANGELOG.md                     # Historique des releases (Keep a Changelog / SemVer)
├── LICENSE                          # Licence MIT
├── README.md                        # Documentation du dépôt plugin
├── install.py                       # Installeur / désinstalleur cross-platform
├── gravity-architect-plugin/        # Plugin Antigravity autonome
│   ├── plugin.json                  # Manifeste officiel (9 champs)
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

[`install.py`](install.py) copie [`gravity-architect-plugin/`](gravity-architect-plugin/) vers `~/.gemini/config/plugins/gravity-architect/`, règle les permissions exécutables POSIX (`0755`) et exécute `validate.py --strict` sur une copie temporaire avant installation.

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
agy plugin install ./gravity-architect-plugin
```

---

## Utilisation rapide

Dans un atelier cible (initialisé via `/gravity-architect init` ou `init_workspace.py`) :

```powershell
python gravity-architect-plugin/scripts/init_workspace.py --workspace ./mon-atelier --project app=../mon-app
python gravity-architect-plugin/scripts/sync_tracking.py --workspace ./mon-atelier --print-delta
python gravity-architect-plugin/scripts/sync_tracking.py --workspace ./mon-atelier --offline --ack-editorial --print-delta
```

Dans Antigravity, utilisez ensuite `/gravity-architect [init|sync|status|spec|handoff|archive]` (voir [`gravity-architect-plugin/README.md`](gravity-architect-plugin/README.md)).

---

## Vérifications développeur

```powershell
python gravity-architect-plugin/scripts/validate.py --strict
agy plugin validate ./gravity-architect-plugin
python -m unittest discover -s tests -p "test_*.py" -v
```

---

## Documentation & Releases

- [`CHANGELOG.md`](CHANGELOG.md) — Historique des releases (`v0.1.0`)
- [`gravity-architect-plugin/README.md`](gravity-architect-plugin/README.md) — Guide complet du plugin et des commandes `/gravity-architect`
- [`AGENTS.md`](AGENTS.md) — Charte, invariants et vérifications obligatoires

---

## Licence

Distribué sous licence MIT — voir [`LICENSE`](LICENSE) pour plus de détails.
