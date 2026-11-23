---
name: gravity-architect
description: >-
  Orchestre un atelier générique de conception, specs, handoffs, architecture Hot/Cold
  et suivi multi-projets lecture seule. Activer sur /gravity-architect [init|add|sync|status|spec|handoff|archive|audit]
  ou lors d'une mise à jour d'un dépôt suivi.
---

# Gravity Architect — Atelier de Conception & Suivi Multi-Projets

## Règles strictes
1. **Résolution du moteur :** scripts dans `~/.gemini/config/plugins/gravity-architect/scripts/` (ou `./plugin/scripts/` en local).
2. **Lecture seule absolue hors atelier :** ne jamais créer, éditer ou lancer de commande Git mutante dans les dépôts suivis (`projects.json`).
3. **Économie maximale de tokens :** ne jamais inspecter manuellement les dépôts suivis avant d'avoir exécuté `sync_tracking.py --print-delta` et lu le micro-delta.

## Routage

### 1. `/gravity-architect init` *(onboarding hybride guidé)*
1. **Atelier déjà initialisé (`projects.json` présent) :** exécuter `python "<PLUGIN_DIR>/scripts/init_workspace.py" --workspace .` *(idempotent sans `--force`)* et rappeler `/gravity-architect add <chemin...>` pour ajouter des dépôts.
2. **Atelier vierge :** découverte lecture seule 0-token dans le dossier courant uniquement : `python "<PLUGIN_DIR>/scripts/init_workspace.py" --workspace . --discover --json`.
3. **Si `candidates` est vide :** ne **jamais** scanner `../` automatiquement ; demander via `ask_question` le dossier cible (`../` en raccourci) ou des chemins directs, puis relancer `init_workspace.py --workspace . --discover --scan-dir "<CIBLE>" --json`.
4. **Sélection guidée (1 seul `ask_question`) :** choix multiple des dépôts (`candidates`), veille (`antigravity` recommandée si plugin Antigravity détecté, ou aucune / `--watch-url`), `public_mode` (`false` par défaut).
5. **Déploiement & 1re synchro :** exécuter `init_workspace.py --workspace .` (`--project ...`, `--watch antigravity`, `--watch-url id=url`, `--public-mode`, `--name "<Titre>"`), puis *(sauf `--no-sync`)* : `sync_tracking.py --workspace . --print-delta` → remplir `tracking/projects/*.md` (et `tracking/antigravity/IMPACT.md` si veille) → `sync_tracking.py --workspace . --offline --ack-editorial --print-delta` pour sceller `tracking/snapshots/editorial_state.json`.

### 2. `/gravity-architect add <chemin...>` *(ajout incrémental)*
1. Exécuter `python "<PLUGIN_DIR>/scripts/init_workspace.py" --workspace . --add "<CHEMIN>"` *(répétable, `<chemin>` ou `id=chemin` ; fail-closed si `projects.json` absent ou doublon d'`id`/chemin)*.
2. Enchaîner *(sauf `--no-sync`)* `sync_tracking.py --workspace . --print-delta` → compléter `tracking/projects/<id>.md` → `sync_tracking.py --workspace . --offline --ack-editorial --print-delta`.

### 3. `/gravity-architect status`
- Lire uniquement `tracking/snapshots/delta.md` (ou `ECOSYSTEM.md` s'il n'existe pas encore) dans l'atelier détecté, sans relancer de synchro.
- Résumer état courant, chantiers WIP et alertes hygiène en 5–8 lignes.

### 4. `/gravity-architect` ou `/gravity-architect sync` *(défaut)*
1. Exécuter **1 seule commande** : `python "<PLUGIN_DIR>/scripts/sync_tracking.py" --print-delta` *(options : `--workspace <dir>`, `--offline`, `--check`, `--ack-editorial`, `--max-stdout-bytes <N>`, `--max-changelog-lines <N>`)*.
2. Lire le micro-delta :
   - **`NO_EDITORIAL_CHANGES` (sans `--full`) :** ne lire aucun autre fichier ; répondre en 5–8 lignes max (statut, fichiers auto-mis à jour `<!-- AUTO:START/END -->`, alertes hygiène).
   - **`EDITORIAL_UPDATE_REQUIRED` (ou `--full`) :** lire **uniquement** `Cibles éditoriales LLM`, appliquer des éditions minimales avec les extraits `CHANGELOG.md`, diffs `AGENTS.md` et puces de veille du delta (préserver `<!-- AUTO:START/... -->` / `<!-- AUTO:END/... -->` et budgets Hot), puis exécuter `python "<PLUGIN_DIR>/scripts/sync_tracking.py" --offline --ack-editorial --print-delta` pour sceller `tracking/snapshots/editorial_state.json` et confirmer `NO_EDITORIAL_CHANGES`.
3. **Commit Git :** ne **pas** committer par défaut ; uniquement si `--commit` est demandé dans l'atelier, sans jamais `git push`.

### 5. `/gravity-architect spec <slug>` · `handoff <projet> <slug>` · `archive <slug>`
- **`spec <slug>` :** challenger le besoin, vérifier les solutions natives/existantes avant d'ajouter du code, puis créer `specs/<YYYY-MM-DD>-<slug>.md` depuis `specs/_TEMPLATE.md`.
- **`handoff <projet> <slug>` :** créer `handoffs/<YYYY-MM-DD>-<projet>-<slug>.md` depuis `handoffs/_TEMPLATE.md` (décisions figées, périmètre, invariants de `tracking/projects/<projet>.md`, vérifications).
- **`archive <slug>` :** déplacer spec et handoffs livrés vers `specs/archive/` et `handoffs/archive/` (statut `done`), actualiser les pistes actives puis exécuter `--offline --ack-editorial --print-delta`.

### 6. `/gravity-architect audit [projet|all]` *(audit Code & Architecture)*
- Auditer en **lecture seule absolue** les dépôts suivis (`projet` ou `all` par défaut) uniquement sur **Code & Architecture** *(jamais d'audit agent ni de métriques)*.
- Rédiger `audits/code/<YYYY-MM-DD>-audit-code-<cible>.md` depuis `audits/code/_TEMPLATE.md` avec constats `CODE-XX-N` (`P0`/`P1`/`P2`) et plan d'actions priorisé.
- Mettre à jour le **Journal des audits** dans `audits/code/README.md` *(isolé d'`audits/agents/`)*.
