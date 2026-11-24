# Gravity Architect — Instructions Agents

## Périmètre & Architecture
Plugin Antigravity générique d'atelier de conception, specs, tasks et suivi multi-projets lecture seule (Hot / Cold) :
- `plugin/` : moteur autonome (`plugin.json` 9 champs, `config/module.json`, `core/`, `skills/`, `rules/AGENTS.md`, `templates/`, `scripts/{sync_tracking,init_workspace,validate}.py`, `assets/`).
- `install.py` : installeur cross-platform ; `tests/` : suite `unittest`.
- **Stockage :** `default_architect_home()` (`$GRAVITY_ARCHITECT_HOME` > `$GRAVITY_HOME/architect` > `~/.gemini/gravity/architect`) ; `--workspace` / `$GRAVITY_ARCHITECT_WORKSPACE` / `.` préservés. Aucun atelier privé suivi par Git.

## Invariants
- **Git & versioning (`dev` obligatoire, chef d'orchestre seul) :** tout dev sur `dev`/branche dédiée (jamais de commit/push direct sur `main`) ; *Conventional Commits*, SemVer synchronisé (`plugin/plugin.json` + `CHANGELOG.md`), tags annotés `vX.Y.Z` sur `main` aux releases. Sous-agents et `swarm` ne committent, ne poussent ni ne taguent.
- **Ingénierie & Python 3.10+ stdlib :** KISS, YAGNI, DRY, SOLID, CUPID ; 100 % stdlib dans `plugin/`, `install.py` et `tests/` (UTF-8 sans BOM, LF, zéro `shell=True`).
- **Docs & sans fuite :** mettre à jour `README.md`, `plugin/README.md` et `CHANGELOG.md` dans le même lot ; zéro chemin personnel ni projet tiers dans `plugin/` (`plugin.json` limité aux 9 champs officiels).

## Vérifications obligatoires
- `python plugin/scripts/validate.py --strict`
- `agy plugin validate ./plugin --strict`
- `python -m unittest discover -s tests -p "test_*.py" -v`
