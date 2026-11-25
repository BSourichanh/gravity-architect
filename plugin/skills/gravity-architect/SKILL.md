---
name: gravity-architect
description: >-
  Orchestre un atelier générique de conception, specs, tasks, architecture Hot/Cold
  et suivi multi-projets lecture seule. Activer sur /gravity-architect [init|add|sync|status|spec|task|archive|audit]
  ou lors d'une mise à jour d'un dépôt suivi.
---

# Gravity Architect — Atelier & Suivi Multi-Projets

Détails (4 phases, exécution native, Plan Mode, clôture, onboarding) : [workflows-and-hygiene.md](references/workflows-and-hygiene.md).

## Règles strictes
1. **Moteur :** scripts dans `~/.gemini/config/plugins/gravity-architect/scripts/` (ou `./plugin/scripts/`).
2. **Code en lecture seule hors atelier :** 0 édition de source dans les dépôts suivis (`projects.json`) ; implémentation en worktree isolé (`wave_plan_v1` ou repli natif sous-agents / `/swarm`).
   - **Clôture Git & installation :** plan/spec validé, vague terminée, revue propre et `100 %` vérifs vertes (*fail-closed* ; stopper avant `commit`/`push` si échec ou hors `dev`) → `git add`/`commit` `dev` + `git push origin dev` *(jamais `--force`)* + `ecosystem_install.py --update --modules <...> --strict` (`python3` POSIX, `python` Win, fin Validation seule). `merge dev -> main`, tag et release sur accord humain explicite seul.
3. **Hygiène tokens & Plan Mode :** `sync_tracking.py --print-delta` avant inspection ; déléguer multi-fichiers à `research` RO ; 0 spec/task dans `exit_plan_mode(plan=...)` ; `/compact` post-tasks et racine `> 250k` tokens.
4. **Registre :** `init_workspace.py` / `sync_tracking.py` (hors `--check`/`--dry-run`/`--discover`) inscrivent l'atelier dans `<architect_home>/ateliers.json` (`GRAVITY_ARCHITECT_SKIP_REGISTRY=1` opt-out).

## Routage

### 0. `/gravity-architect` vide vs `<instruction>` *(Cycle 4 phases)*
- **Vide :** état consultatif `PreInvocation` (`0` écriture, `0` capture `gravity-metrics`, via `atelier_status.py`).
- **`"<instruction>"` :** cycle **4 phases** ([`workflows-and-hygiene.md`](references/workflows-and-hygiene.md) §6) :
  1. **Conception :** `research` RO + `/grill-me` + `/plan` (`specs/`).
  2. **Planification :** ancres `research` (`::`/`~L`) + `tasks/` (`<= 5` code, `quick`|`standard`) + `core/waves.py --check-waves` + **1 checkpoint unique** (`RequestFeedback=True` **et/ou `ask_question`**, *`Proceed` absent sur certaines surfaces*).
  3. **Production :** `core/waves.py --export-wave <N>` (`wave_plan_v1`) en `git worktree` isolés (`gravity-workflow` `quick`|`standard` ou sous-agents / `/swarm`), retour `<= 10` l./dépôt, titres `update_steps` métier (0 « Vague N »), checkpoint `dev`, `/compact` `> 250k`.
  4. **Validation :** `verify_commands` (`100 %` vertes, *fail-closed*, ex. `audit_ecosystem.py --verify-parallel --strict`) → commit/push `dev` → archive (`specs/archive/`, `tasks/archive/`, `--offline --ack-editorial`) → docs → réinstall fin Validation (`ecosystem_install.py --update --modules <...> --strict`) → `gravity-metrics`.

### 1. `/gravity-architect init` *(onboarding guidé)*
1. **Existant (`projects.json`) :** `init_workspace.py --workspace .` *(idempotent sans `--force`)* ; proposer `/gravity-architect add <chemin...>`.
2. **Vierge :** `init_workspace.py --workspace . --discover --json` (CWD seul ; 0 scan `../` sans accord). Si `candidates: []`, **1 `ask_question`** : *(a) atelier vide (`0` projet)*, *(b) scanner `../`*, *(c) chemins directs*.
3. **À `0` projet :** `init_workspace.py --workspace . --run-sync --offline` *(1 commande, sans `--ack-editorial`, nom dérivé sauf `--name`)*.
4. **Avec dépôts :** 1 `ask_question` *(dépôts, veille, `public_mode=false`)* → `init_workspace.py` (`--project`, `--watch`, `--public-mode`, `--name`) → `sync_tracking.py --print-delta` → fiches/`IMPACT.md` → `--offline --ack-editorial --print-delta`.

### 2. `/gravity-architect add [chemin...]`
- **Sans argument :** si `projects.json` référence `../`, proposer `../` en 1re option (`ask_question`) avant `--discover --scan-dir ../ --json`.
- **Avec chemin(s) :** `init_workspace.py --workspace . --add "<CHEMIN>"` *(fail-closed)* → `sync_tracking.py --print-delta` → fiche → `--offline --ack-editorial --print-delta`.

### 3. `/gravity-architect status` & `sync`
- **`status` :** lancer `atelier_status.py` (ou lire `delta.md`/`ECOSYSTEM.md`) sans écrire ; résumer en 5–8 lignes.
- **`sync` :** sans `./projects.json`, basculer sur `init` ([`workflows-and-hygiene.md`](references/workflows-and-hygiene.md) §5). Sinon `sync_tracking.py --print-delta`. En Plan Mode, si `--check` → `NO_EDITORIAL_CHANGES` et `0` auto-MAJ, répondre sans `exit_plan_mode`. Si `EDITORIAL_UPDATE_REQUIRED`, éditer cibles puis `--offline --ack-editorial --print-delta`. Jamais `--ack-editorial` si WIP non commité. Commit atelier seul si `--commit`, sans `git push`.

### 4. `spec <slug>` · `task <projet> <slug>` · `archive <slug>`
- **`spec <slug>` :** challenger le besoin, créer `specs/<YYYY-MM-DD>-<slug>.md` depuis `specs/_TEMPLATE.md`.
- **`task <projet> <slug>` :** créer `tasks/<YYYY-MM-DD>-<projet>-<slug>.md` (vague, dépendances, `quick`|`standard`, `::`/`~L`, `<= 5` code, vérifs) → `core/waves.py --check-waves`. Afficher `rédigé, non déployé` et proposer `wave_plan_v1` (`--export-wave`) ou `/swarm` après **1 `ask_question` récapitulatif**.
- **`archive <slug>` :** après vérifs, commit/push `dev` et install, archiver (`specs/archive/`, `tasks/archive/`, `done`), `--offline --ack-editorial --print-delta`, puis clôture `gravity-metrics` ([`workflows-and-hygiene.md`](references/workflows-and-hygiene.md) §3).

### 5. `/gravity-architect audit [projet|all]` *(Code & Architecture)*
- Auditer en **lecture seule absolue** les dépôts suivis *(0 audit agent/métriques)* ; rédiger `audits/code/<YYYY-MM-DD>-audit-code-<cible>.md` (`CODE-XX-N` `P0`–`P2`) et MAJ `audits/code/README.md` *(isolé d'`audits/agents/`)*.
