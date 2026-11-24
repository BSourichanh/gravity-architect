---
name: gravity-architect
description: >-
  Orchestre un atelier générique de conception, specs, tasks, architecture Hot/Cold
  et suivi multi-projets lecture seule. Activer sur /gravity-architect [init|add|sync|status|spec|task|archive|audit]
  ou lors d'une mise à jour d'un dépôt suivi.
---

# Gravity Architect — Atelier & Suivi Multi-Projets

Détails (Bridge, Plan Mode, callbacks, onboarding) : [workflows-and-hygiene.md](references/workflows-and-hygiene.md).

## Règles strictes
1. **Moteur :** scripts dans `~/.gemini/config/plugins/gravity-architect/scripts/` (ou `./plugin/scripts/`).
2. **Code en lecture seule hors atelier :** zéro création/édition/suppression de source dans les dépôts suivis (`projects.json`) ; implémentation déléguée aux sessions cibles.
   - **Clôture Git & installation :** plan/spec validé, `0` job Bridge, revue propre et `100 %` vérifs vertes (*fail-closed* global ; stopper avant tout `commit`/`push` si échec ou hors `dev`) → auto `git add`/`commit` sur `dev` + `git push origin dev` *(jamais `--force`)* + `ecosystem_install.py --update --modules <...> --strict` (`python3` POSIX, `python` Win, plutôt qu'`install.py --strict`). `merge dev -> main`, tag SemVer et release sur accord humain explicite seul.
3. **Hygiène tokens & Plan Mode :**
   - Exécuter `sync_tracking.py --print-delta` avant d'inspecter les dépôts ; déléguer l'exploration multi-fichiers à un sous-agent lecture seule (`research`).
   - Ne jamais recopier de spec/task complète dans `exit_plan_mode(plan=...)` (plan structurel concis seul).
   - Suggérer `/compact` ou une nouvelle session après production des tasks.
4. **Registre :** `init_workspace.py` / `sync_tracking.py` (hors `--check`/`--dry-run`/`--discover`) inscrivent l'atelier dans `<architect_home>/ateliers.json` (opt-out `GRAVITY_ARCHITECT_SKIP_REGISTRY=1`).

## Routage

### 1. `/gravity-architect init` *(onboarding guidé)*
1. **Existant (`projects.json` présent) :** `init_workspace.py --workspace .` *(idempotent sans `--force`)* ; suggérer `/gravity-architect add <chemin...>`.
2. **Vierge :** `init_workspace.py --workspace . --discover --json` (CWD seul ; 0 scan `../` sans accord). Si `candidates: []`, **1 `ask_question`** : *(a) atelier vide (`0` projet)*, *(b) scanner `../`*, *(c) chemins directs*.
3. **À `0` projet :** `init_workspace.py --workspace . --run-sync --offline` *(1 commande, sans `--ack-editorial`, nom dérivé sauf `--name` ; options : `public_mode`, `--watch-url`)*.
4. **Avec dépôts :** 1 `ask_question` *(dépôts, veille `antigravity`/aucune/`--watch-url`, `public_mode=false`)* → `init_workspace.py` (`--project`, `--watch`, `--public-mode`, `--name`) → `sync_tracking.py --print-delta` → fiches/`IMPACT.md` → `--offline --ack-editorial --print-delta`.

### 2. `/gravity-architect add [chemin...]`
- **Sans argument :** si `projects.json` référence `../`, proposer `../` en 1re option recommandée (`ask_question`) avant tout autre scan (`--discover --scan-dir ../ --json`).
- **Avec chemin(s) :** `init_workspace.py --workspace . --add "<CHEMIN>"` *(répétable, `<chemin>`/`id=chemin`, fail-closed si `projects.json` absent/doublon)* → `sync_tracking.py --print-delta` → `tracking/projects/<id>.md` → `--offline --ack-editorial --print-delta`.

### 3. `/gravity-architect status`
- Lire `tracking/snapshots/delta.md` (ou `ECOSYSTEM.md`) sans resynchroniser ; résumer état, WIP et alertes en 5–8 lignes.

### 4. `/gravity-architect` ou `/gravity-architect sync` *(défaut)*
0. **Atelier absent :** si `./projects.json` manque (hors sous-dossier unique), 0 `sync_tracking.py` ; basculer sur `init` ([`workflows-and-hygiene.md`](references/workflows-and-hygiene.md) §5).
1. **Synchro :** `python "<PLUGIN_DIR>/scripts/sync_tracking.py" --print-delta` *(`--workspace`, `--offline`, `--check`, `--ack-editorial`, `--max-stdout-bytes`, `--max-changelog-lines`)*.
2. **No-op Plan Mode :** si `--check --print-delta` → `NO_EDITORIAL_CHANGES` et `0` auto-MAJ (atelier dans `<architect_home>/ateliers.json`), répondre en 5–8 lignes sans `exit_plan_mode`.
3. **`EDITORIAL_UPDATE_REQUIRED` / `--full` :** lire `Cibles éditoriales LLM`, éditer au minimum (préserver `<!-- AUTO:START/END -->` et budgets Hot), puis `--offline --ack-editorial --print-delta`.
4. **Garde WIP & Bridge :** jamais `--ack-editorial` si WIP non commité dans les dépôts suivis ; suivre Bridge via `manage_thread(action="get_job")` (0 `read_thread` complet). Commit atelier seul si `--commit`, sans `git push`.

### 5. `spec <slug>` · `task <projet> <slug>` · `archive <slug>`
- **`spec <slug>` :** challenger le besoin, vérifier l'existant, créer `specs/<YYYY-MM-DD>-<slug>.md` depuis `specs/_TEMPLATE.md`.
- **`task <projet> <slug>` & vagues/Bridge :** créer `tasks/<YYYY-MM-DD>-<projet>-<slug>.md` depuis `tasks/_TEMPLATE.md` (vague, dépendances, profil, ancres `::`/`~L`, `<= 5` fichiers code, invariants `tracking/projects/<projet>.md`, vérifs) puis valider via `core/waves.py --check-waves`. Afficher *(« rédigé, non déployé »)* et proposer `/gravity-bridge`. Sur demande d'envoi/dispatch de tasks, **1 seul `ask_question` récapitulatif** (cibles, objets, `file_refs`, posture) vaut activation Bridge + `approved=true, dispatch=true` (0 appel MCP silencieux, 0 double confirmation).
- **`archive <slug>` :** après vérifs, commit/push `dev` et install, déplacer vers `specs/archive/` et `tasks/archive/` (`done`), actualiser pistes actives, `--offline --ack-editorial --print-delta`, puis clôture `gravity-metrics` ([`workflows-and-hygiene.md`](references/workflows-and-hygiene.md) §3).

### 6. `/gravity-architect audit [projet|all]` *(Code & Architecture)*
- Auditer en **lecture seule absolue** les dépôts suivis sur **Code & Architecture** *(0 audit agent/métriques)* ; rédiger `audits/code/<YYYY-MM-DD>-audit-code-<cible>.md` (`CODE-XX-N` `P0`–`P2`) et MAJ `audits/code/README.md` *(isolé d'`audits/agents/`)*.
