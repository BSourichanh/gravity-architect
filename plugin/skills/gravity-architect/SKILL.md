---
name: gravity-architect
description: >-
  Orchestre un atelier générique de conception, specs, handoffs, architecture Hot/Cold
  et suivi multi-projets lecture seule. Activer sur /gravity-architect [init|add|sync|status|spec|handoff|archive]
  ou lors d'une mise à jour d'un dépôt suivi.
---

# Gravity Architect — Atelier de Conception & Suivi Multi-Projets

## Règles strictes
1. **Résolution du moteur :** localiser les scripts dans `~/.gemini/config/plugins/gravity-architect/scripts/` (ou `./plugin/scripts/` en développement local).
2. **Lecture seule absolue hors de l'atelier :** ne jamais créer, éditer ou exécuter de commande Git mutante dans les dépôts suivis déclarés dans `projects.json`.
3. **Économie maximale de tokens :** ne jamais inspecter manuellement les dépôts suivis avant d'avoir exécuté `sync_tracking.py --print-delta` et lu le micro-delta.

## Routage

### 1. `/gravity-architect init` *(onboarding hybride guidé)*
1. **Atelier déjà initialisé (`projects.json` présent) :** exécuter :
   ```powershell
   python "<PLUGIN_DIR>/scripts/init_workspace.py" --workspace .
   ```
   *(Strictement idempotent sans `--force`)* puis rappeler d'utiliser `/gravity-architect add <chemin...>` pour ajouter des dépôts.
2. **Atelier vierge :** lancer la découverte lecture seule 0-token dans le dossier courant uniquement :
   ```powershell
   python "<PLUGIN_DIR>/scripts/init_workspace.py" --workspace . --discover --json
   ```
3. **Si `candidates` est vide :** ne **jamais** scanner `../` automatiquement ; demander via `ask_question` le dossier à scanner (`../` proposé en raccourci) ou des chemins directs, puis relancer `init_workspace.py --workspace . --discover --scan-dir "<CIBLE>" --json`.
4. **Sélection guidée (1 seul appel `ask_question`) :** proposer :
   - sélection multi-choix des dépôts découverts (`candidates`),
   - veille à activer (`antigravity` recommandé si au moins un plugin Antigravity est détecté, ou aucune / `--watch-url`),
   - `public_mode` (`false` par défaut).
5. **Déploiement & 1re synchro :** exécuter `init_workspace.py --workspace .` avec les options retenues (`--project ...`, `--watch antigravity`, `--watch-url id=url`, `--public-mode`, `--name "<Titre>"`), puis enchaîner *(sauf si `--no-sync` demandé)* :
   - `python "<PLUGIN_DIR>/scripts/sync_tracking.py" --workspace . --print-delta`
   - remplissage éditorial initial des fiches `tracking/projects/*.md` (et `tracking/antigravity/IMPACT.md` si veille activée)
   - `python "<PLUGIN_DIR>/scripts/sync_tracking.py" --workspace . --offline --ack-editorial --print-delta` pour sceller `tracking/snapshots/editorial_state.json`.

### 2. `/gravity-architect add <chemin...>` *(ajout incrémental)*
1. Exécuter `python "<PLUGIN_DIR>/scripts/init_workspace.py" --workspace . --add "<CHEMIN>"` *(répétable, accepte `<chemin>` ou `id=chemin` ; échoue fail-closed si `projects.json` absent ou doublon d'`id`/chemin)*.
2. Enchaîner *(sauf `--no-sync`)* `sync_tracking.py --workspace . --print-delta` → compléter la fiche `tracking/projects/<id>.md` ajoutée → `sync_tracking.py --workspace . --offline --ack-editorial --print-delta`.

### 3. `/gravity-architect status`
- Lire uniquement `tracking/snapshots/delta.md` (ou `ECOSYSTEM.md` s'il n'existe pas encore) dans l'atelier détecté, sans relancer de synchronisation.
- Résumer l'état courant, les chantiers WIP et les alertes hygiène en 5–8 lignes.

### 4. `/gravity-architect` ou `/gravity-architect sync` *(défaut)*
1. Exécuter **1 seule commande** :
   ```powershell
   python "<PLUGIN_DIR>/scripts/sync_tracking.py" --print-delta
   ```
   *(Options : `--workspace <dir>`, `--offline`, `--check`, `--ack-editorial`.)*
2. Lire la sortie du micro-delta :
   - **Si `Statut éditorial : NO_EDITORIAL_CHANGES` (et sans `--full`) :**
     - **Ne lire aucun autre fichier.**
     - Répondre directement en 5–8 lignes maximum : statut, fichiers auto-mis à jour (`<!-- AUTO:START/END -->`) et alertes hygiène éventuelles.
   - **Si `Statut éditorial : EDITORIAL_UPDATE_REQUIRED` (ou avec `--full`) :**
     - Lire **uniquement** les fichiers listés dans `Cibles éditoriales LLM`.
     - Appliquer des éditions minimales avec les extraits `CHANGELOG.md`, diffs `AGENTS.md` et puces de veille déjà fournis dans le delta (préserver `<!-- AUTO:START/... -->` / `<!-- AUTO:END/... -->` et respecter les budgets Hot).
     - Exécuter ensuite `python "<PLUGIN_DIR>/scripts/sync_tracking.py" --offline --ack-editorial --print-delta` pour sceller `tracking/snapshots/editorial_state.json` et confirmer `NO_EDITORIAL_CHANGES`.
3. **Commit Git :** ne **pas** committer par défaut ; uniquement si `--commit` est demandé explicitement dans l'atelier, sans jamais `git push`.

### 5. `/gravity-architect spec <slug>` · `handoff <projet> <slug>` · `archive <slug>`
- **`spec <slug>` :** challenger le besoin, vérifier les solutions natives/existantes avant d'ajouter du code, puis créer `specs/<YYYY-MM-DD>-<slug>.md` depuis `specs/_TEMPLATE.md`.
- **`handoff <projet> <slug>` :** créer `handoffs/<YYYY-MM-DD>-<projet>-<slug>.md` depuis `handoffs/_TEMPLATE.md` avec décisions figées, périmètre, invariants de `tracking/projects/<projet>.md` et commandes de vérification.
- **`archive <slug>` :** déplacer la spec et les handoffs livrés vers `specs/archive/` et `handoffs/archive/` (statut `done`), actualiser les pistes actives puis exécuter `--offline --ack-editorial --print-delta`.
