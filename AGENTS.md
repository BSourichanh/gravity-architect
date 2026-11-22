# Gravity Architect — Instructions Agents

## Périmètre & Architecture
Plugin Antigravity générique d'atelier de conception, specs, handoffs et suivi multi-projets lecture seule à architecture Hot / Cold :
- `gravity-architect-plugin/` : moteur autonome (`plugin.json`, `skills/gravity-architect/`, `rules/AGENTS.md`, `templates/`, `scripts/sync_tracking.py`, `init_workspace.py`, `validate.py`, `assets/`).
- `install.py` : installeur/désinstalleur multiplateformes ; `tests/` : suite `unittest`.
- **Séparation plugin / données :** aucun atelier privé ni fichier utilisateur suivi par Git dans ce dépôt.

## Invariants
- **Branche de développement (`dev`) obligatoire :** tout développement s'effectue sur `dev` (ou branche dédiée), puis est fusionné vers `main` aux releases.
- **Git & versioning (chef d'orchestre uniquement) :** `dev` / branches dédiées, jamais de commit ni push direct sur `main` ; *Conventional Commits* ; SemVer synchronisé dans `gravity-architect-plugin/plugin.json` + `CHANGELOG.md` ; tags annotés `vX.Y.Z` aux releases sur `main`. Sous-agents et workers `swarm` ne committent, ne poussent et ne taguent jamais.
- **Documentation synchronisée :** toute évolution fonctionnelle ou structurelle met à jour `README.md`, `gravity-architect-plugin/README.md` et `CHANGELOG.md` dans le même lot.
- **100 % bibliothèque standard Python 3** dans `gravity-architect-plugin/`, `install.py` et `tests/` (UTF-8, zéro `shell=True`).
- **Générique & sans fuite :** zéro chemin personnel ni projet tiers codé en dur dans `gravity-architect-plugin/` (`plugin.json` limité aux champs officiels).

## Vérifications obligatoires
- `python gravity-architect-plugin/scripts/validate.py --strict`
- `agy plugin validate ./gravity-architect-plugin`
- `python -m unittest discover -s tests -p "test_*.py" -v`
