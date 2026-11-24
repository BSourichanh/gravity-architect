---
name: gravity-architect
description: >-
  Orchestre un atelier générique de conception, specs, handoffs, architecture Hot/Cold
  et suivi multi-projets lecture seule. Activer sur /gravity-architect [init|add|sync|status|spec|handoff|archive|audit]
  ou lors d'une mise à jour d'un dépôt suivi.
---

# Gravity Architect — Atelier & Suivi Multi-Projets

Détails (passerelle Bridge, hygiène Plan Mode, callbacks & clôture) : [workflows-and-hygiene.md](references/workflows-and-hygiene.md).

## Règles strictes
1. **Moteur :** scripts dans `~/.gemini/config/plugins/gravity-architect/scripts/` (ou `./plugin/scripts/`).
2. **Code en lecture seule hors atelier :** zéro création/édition/suppression de source dans les dépôts suivis (`projects.json`) ; implémentation déléguée aux sessions cibles.
   - **Clôture Git & installation (sur feu vert humain) :** après revue/vérifs vertes, `git add`/`commit` sur `dev`, `merge` `dev -> main`, tag SemVer et `install.py` / `ecosystem_install.py` permis (jamais `git push` sans demande explicite). Après commit sur `dev`, recommander `ecosystem_install.py --update --modules <...> --strict` (`python3` Linux/macOS, `python` Windows) plutôt qu'`install.py --strict`.
3. **Hygiène tokens & Plan Mode :**
   - Exécuter `sync_tracking.py --print-delta` avant d'inspecter les dépôts ; déléguer l'exploration multi-fichiers à un sous-agent lecture seule (`research`).
   - Ne jamais recopier de spec/handoff complet dans `exit_plan_mode(plan=...)` (plan structurel concis seul).
   - Suggérer `/compact` ou une nouvelle session après production des handoffs.
4. **Registre :** `init_workspace.py` et `sync_tracking.py` (hors `--check`/`--dry-run`/`--discover`) enregistrent l'atelier dans `<architect_home>/ateliers.json` (`GRAVITY_ARCHITECT_SKIP_REGISTRY=1` pour désactiver).

## Routage

### 1. `/gravity-architect init` *(onboarding guidé)*
1. **Déjà initialisé (`projects.json` présent) :** `python "<PLUGIN_DIR>/scripts/init_workspace.py" --workspace .` *(idempotent sans `--force`)* ; rappeler `/gravity-architect add <chemin...>`.
2. **Vierge :** `init_workspace.py --workspace . --discover --json` (CWD seul). Si `candidates` vide, jamais de scan `../` sans accord : demander le dossier via `ask_question` (`../` en raccourci) puis `--scan-dir "<CIBLE>"`.
3. **Sélection (1 `ask_question`) :** dépôts, veille (`antigravity` recommandée si plugin détecté, ou aucune / `--watch-url`), `public_mode` (`false` par défaut).
4. **Déploiement :** `init_workspace.py --workspace .` (`--project`, `--watch`, `--public-mode`, `--name`) puis *(hors `--no-sync`)* `sync_tracking.py --print-delta` → fiches/`IMPACT.md` → `--offline --ack-editorial --print-delta`.

### 2. `/gravity-architect add [chemin...]`
- **Sans argument :** si `projects.json` référence déjà des dépôts sous `../`, proposer `../` en 1re option recommandée via `ask_question` avant de scanner ailleurs (`--discover --scan-dir ../ --json`).
- **Avec chemin(s) :** `init_workspace.py --workspace . --add "<CHEMIN>"` *(répétable, `<chemin>` ou `id=chemin`, fail-closed si `projects.json` absent/doublon)*, puis *(hors `--no-sync`)* `sync_tracking.py --print-delta` → `tracking/projects/<id>.md` → `--offline --ack-editorial --print-delta`.

### 3. `/gravity-architect status`
- Lire uniquement `tracking/snapshots/delta.md` (ou `ECOSYSTEM.md`) dans l'atelier détecté, sans relancer de synchro ; résumer état, WIP et alertes en 5–8 lignes.

### 4. `/gravity-architect` ou `/gravity-architect sync` *(défaut)*
1. **1 seule commande :** `python "<PLUGIN_DIR>/scripts/sync_tracking.py" --print-delta` *(options : `--workspace`, `--offline`, `--check`, `--ack-editorial`, `--max-stdout-bytes`, `--max-changelog-lines`)*.
2. **No-op en Plan Mode :** si `--check --print-delta` retourne `NO_EDITORIAL_CHANGES` avec `0` fichier auto-mis à jour (et atelier dans `<architect_home>/ateliers.json`), répondre directement en 5–8 lignes sans appeler `exit_plan_mode`.
3. **`EDITORIAL_UPDATE_REQUIRED` / `--full` :** lire uniquement `Cibles éditoriales LLM`, appliquer des éditions minimales (préserver `<!-- AUTO:START/END -->` et budgets Hot), puis `--offline --ack-editorial --print-delta`.
4. **Garde WIP & Bridge :** ne **jamais** exécuter `--ack-editorial` tant que des lots restent en WIP non commité dans les dépôts suivis ; consulter les jobs Bridge via `manage_thread(action="get_job")` (jamais `read_thread` complet). Commit atelier uniquement si `--commit` demandé, sans `git push`.

### 5. `spec <slug>` · `handoff <projet> <slug>` · `archive <slug>`
- **`spec <slug>` :** challenger le besoin, vérifier l'existant, créer `specs/<YYYY-MM-DD>-<slug>.md` depuis `specs/_TEMPLATE.md`.
- **`handoff <projet> <slug>` & Bridge :** créer `handoffs/<YYYY-MM-DD>-<projet>-<slug>.md` depuis `handoffs/_TEMPLATE.md` (décisions figées, périmètre, invariants `tracking/projects/<projet>.md`, vérifications). Afficher le statut *(« rédigé, non déployé »)* et proposer `/gravity-bridge`. Si l'utilisateur demande d'envoyer/dispatcher des handoffs (même sans `/gravity-bridge`), déclencher **1 seul `ask_question` récapitulatif** (cibles, objets, `file_refs`, posture) valant activation Bridge + feu vert unique `approved=true, dispatch=true` (0 appel MCP silencieux, 0 double confirmation).
- **`archive <slug>` :** déplacer vers `specs/archive/` et `handoffs/archive/` (`done`), actualiser pistes actives puis `--offline --ack-editorial --print-delta`.

### 6. `/gravity-architect audit [projet|all]` *(Code & Architecture)*
- Auditer en **lecture seule absolue** les dépôts suivis uniquement sur **Code & Architecture** *(jamais d'audit agent ni métriques)* ; rédiger `audits/code/<YYYY-MM-DD>-audit-code-<cible>.md` (`CODE-XX-N` `P0`/`P1`/`P2`) et mettre à jour `audits/code/README.md` *(isolé d'`audits/agents/`)*.
