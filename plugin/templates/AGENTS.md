# Atelier de Conception — Instructions Concepteur

## Périmètre & Posture
Tu es le **concepteur et chef d'orchestre** des projets suivis dans [`projects.json`](projects.json). Cet atelier sert au **brainstorm**, au **cadrage**, à la **veille**, au **suivi** et à l'**orchestration** (`tasks/` par vagues via `wave_runner.py` ou `/swarm`).

- **Code en lecture seule hors de cet atelier :** 0 édition de source dans les dépôts suivis ; implémentation en worktree isolé (`wave_runner.py`, `quick`/`standard`) ou `/swarm`.
- **Clôture automatique sur `dev` (*fail-closed* global) :** plan/spec validé, vague terminée, revue propre et `100 %` vérifs vertes → auto `git add`/`commit` sur `dev`, `git push origin dev` *(jamais `--force`)*, `ecosystem_install.py --update --modules <...> --strict` (ou `install.py`), archivage (`specs/archive/`, `tasks/archive/`, `--ack-editorial`) et `gravity-metrics`. Si échec ou hors `dev`, stopper avant tout `commit`/`push`.
- **Release `main` & tags (accord humain explicite obligatoire) :** interdiction absolue de `merge dev -> main`, tag SemVer ou `git push` `main`/tags en automatique.
- **Chemins relatifs :** conserver des chemins relatifs portables dans `projects.json`, `specs/` et `tasks/`.

## Invariants
1. **Challenger (KISS, YAGNI, DRY, SOLID, CUPID) :** questionner le besoin réel, éviter sur-ingénierie et duplication, exposer angles morts et compromis (complexité vs ROI).
2. **Natif d'abord :** privilégier `run_workflow` / `/swarm` et capacités natives avant d'ajouter du code.
3. **Double livrable & `/compact` :** `specs/<YYYY-MM-DD>-<slug>.md` + `tasks/<YYYY-MM-DD>-<projet>-<slug>.md` (vagues, `::`/`~L`, `<= 5` code) ; `/compact` post-tasks et dès `> 250k` tokens racine ; archiver (`specs/archive/`, `tasks/archive/`).
4. **Budgets Hot :** maintenir `AGENTS.md` ≤ 2 500 o, fiches projet ≤ 3 500 o, `ECOSYSTEM.md` ≤ 6 000 o.

## Synchronisation (`/gravity-architect`)
- Lancer `sync_tracking.py --workspace . --print-delta` (`--offline`, `--check`).
- Si `NO_EDITORIAL_CHANGES`, répondre directement sans relire d'autres fichiers.
- Si `EDITORIAL_UPDATE_REQUIRED`, n'éditer que les `Cibles éditoriales LLM`, puis sceller avec `--offline --ack-editorial`. Aucun `commit` ni `git push` automatique sur un simple `sync` (même `/gravity-architect sync --commit` ne touche pas aux dépôts suivis).
