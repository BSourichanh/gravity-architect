# Gravity Architect — Instructions Agents

## Périmètre & Architecture
Plugin Antigravity générique d'atelier de conception, specs, handoffs et suivi multi-projets lecture seule à architecture Hot / Cold :
- `plugin/` : moteur autonome (`plugin.json` 9 champs, `config/module.json`, `skills/gravity-architect/`, `rules/AGENTS.md`, `templates/`, `scripts/{sync_tracking,init_workspace,validate}.py`, `assets/`).
- `install.py` : installeur/désinstalleur multiplateformes ; `tests/` : suite `unittest`.
- **Stockage & ateliers :** `default_architect_home()` (`$GRAVITY_ARCHITECT_HOME` > `$GRAVITY_HOME/architect` > `~/.gemini/gravity/architect`) ; `--workspace` / `$GRAVITY_ARCHITECT_WORKSPACE` / `.` préservés. Aucun atelier privé suivi par Git.

## Invariants
- **Branche de développement (`dev`) obligatoire :** tout développement s'effectue sur `dev` (ou branche dédiée), puis est fusionné vers `main` aux releases.
- **Git & versioning (chef d'orchestre uniquement) :** `dev` / branches dédiées, jamais de commit ni push direct sur `main` ; *Conventional Commits* ; SemVer synchronisé dans `plugin/plugin.json` + `CHANGELOG.md` ; tags annotés `vX.Y.Z` aux releases sur `main`. Sous-agents et workers `swarm` ne committent, ne poussent et ne taguent jamais.
- **Ingénierie & Python 3.10+ stdlib :** appliquer KISS, YAGNI, DRY, SOLID et CUPID ; 100 % bibliothèque standard Python 3 dans `plugin/`, `install.py` et `tests/` (UTF-8 sans BOM, LF, zéro `shell=True`).
- **Documentation synchronisée :** toute évolution fonctionnelle ou structurelle met à jour `README.md`, `plugin/README.md` et `CHANGELOG.md` dans le même lot.
- **Générique & sans fuite :** zéro chemin personnel ni projet tiers codé en dur dans `plugin/` (`plugin.json` limité aux 9 champs officiels).

## Vérifications obligatoires
- `python plugin/scripts/validate.py --strict`
- `agy plugin validate ./plugin --strict`
- `python -m unittest discover -s tests -p "test_*.py" -v`
