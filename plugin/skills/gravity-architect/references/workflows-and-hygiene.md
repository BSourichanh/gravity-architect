# Workflows Avancés & Hygiène Opérationnelle

Fiche de référence chargée à la demande depuis [`SKILL.md`](../SKILL.md) *(progressive disclosure : 0 taxe tokens au chargement initial)*.

## 1. Post-task, vagues & Exécution native (`wave_runner.py` / `/swarm`)

### Statut obligatoire après rédaction d'une task
- Après création de `tasks/<YYYY-MM-DD>-<projet>-<slug>.md` (vague, dépendances, `Profil workflow` `quick` ou `standard`, ancres hybrides `::` / `~L`, plafond `<= 5` fichiers code hors tests/docs) et contrôle via `python "<PLUGIN_DIR>/core/waves.py" --check-waves --workspace .`, afficher explicitement le statut **`rédigé, non déployé`**.
- Rappeler à l'utilisateur la possibilité de lancer la vague en natif via `run_workflow` (`wave_runner.py`) ou `/swarm` (sans jamais lancer d'exécution de code sans feu vert humain).

### Lancement & isolation `git worktree` en Production
- **Par défaut (`run_workflow` + `wave_runner.py`) :** exécute les `tasks/` en `parallel` *fail-isolated* (`try/except` par dépôt) sur des `git worktree` temporaires créés sous `$GRAVITY_HOME/workflow/worktrees/<repo>-<id>` (jamais dans `../<repo>` ni `.gemini/antigravity/` hors `worktrees/`), lit `tasks/*.md` + `<repo>/AGENTS.md` en Python (`0` token), saute `Planner` (`skip_separate_planner=True` dès qu'un `plan_file` est fourni), applique sur `dev` uniquement si `PASS` (`apply_on_pass=True`) et garantit le nettoyage en `try/finally` (`cleanup_worktree_best_effort`).
- **Routage par risque (`quick` vs `standard`) & watchdogs :** utiliser `quick` (`Reviewer flash` à froid) sur docs, templates, UI ou CLI simples, et `standard` (`Reviewer pro`) sur sécurité, hooks, AST, installeur ou noyau `core/`. Watchdogs durs `asyncio.wait_for` (`Builder 15m` / `900s`, `Reviewer 6m` / `360s`) ; retour JSON compact (`<= 10` lignes/dépôt, `changed_files` `1..20`).
- **Option `/swarm` natif :** réserver `/swarm` aux chantiers exploratoires ou couplés entre dépôts nécessitant une coordination directe entre agents, tout en gardant la session racine en lecture seule sur le code suivi.

## 2. Hygiène tokens, Plan Mode & délégation

### `sync` no-op en Plan Mode
- Lorsqu'un `/gravity-architect` ou `/gravity-architect sync` est exécuté en Plan Mode :
  - Lancer `sync_tracking.py --check --print-delta`.
  - Si le delta retourne `NO_EDITORIAL_CHANGES` avec `0` fichier auto-mis à jour (`<!-- AUTO:START/END -->`) **et** que l'atelier figure déjà dans `<architect_home>/ateliers.json`, répondre directement en 5–8 lignes **sans appeler `exit_plan_mode`**.

### Contenu de `exit_plan_mode(plan=...)`
- Ne **jamais** recopier une spécification, une task ou un rapport d'audit complet dans `exit_plan_mode(plan=...)`.
- Limiter `plan` à un résumé structurel concis (périmètre, fichiers ciblés, vérifications attendues) ; la matière détaillée reste dans `specs/`, `tasks/` ou `audits/code/`.

### Exploration multi-fichiers & règle `/compact` (`> 250k`)
- Ne jamais charger une grappe de fichiers source des dépôts suivis dans la session racine ; après lecture du micro-delta, déléguer toute exploration multi-fichiers lecture seule à un sous-agent dédié (`research`) avec périmètre borné.
- Après production d'un lot de `tasks`, suggérer à l'utilisateur `/compact` ou l'ouverture d'une nouvelle session, et compacter la session racine dès que le contexte dépasse **`> 250k` tokens** pour préserver le budget contexte.

## 3. Garde `--ack-editorial` & clôture Git / install

### Garde `--ack-editorial` face au WIP
- Ne **jamais** exécuter `sync_tracking.py --ack-editorial` tant que des lots restent en WIP non commité dans les dépôts suivis (`git status` sale ou modifications en cours non validées).
- N'exécuter `--offline --ack-editorial --print-delta` qu'après mise à jour éditoriale effective et vérification que l'état suivi est stabilisé.

### Clôture ordonnée d'un lot & `gravity-metrics` final
Respecter strictement ces 4 étapes en fin de cycle :
1. **Retours & vérifications (*fail-closed* global) :** confirmer que le plan/spec est validé, la vague terminée, la revue propre et **100 %** des vérifications obligatoires vertes (ex. `audit_ecosystem.py --verify-parallel --strict` sur l'écosystème). Si une vérification échoue, régresse, si un dépôt n'est pas sur `dev` ou signale un blocage, **stopper avant tout `commit`/`push`** sur l'ensemble du lot et demander arbitrage humain.
2. **Clôture auto sur `dev` & réinstallation écosystème :** exécuter automatiquement `git add`/`commit` sur `dev` + `git push origin dev` *(jamais `--force`)* + réinstallation coordonnée via `ecosystem_install.py --update --modules <...> --strict` (`python3` sous Linux/macOS, `python` sous Windows, plutôt qu'un `install.py --strict` isolé afin de maintenir la cohérence entre modules installés). Les opérations `merge dev -> main`, tag SemVer et release exigent un **accord humain explicite** *(un simple `/gravity-architect sync`, même avec `--commit`, ne fait ni `commit` sur les dépôts suivis ni `git push`)*.
3. **Archivage atelier & `--ack-editorial` :** une fois les dépôts suivis propres et poussés sur `dev`, déplacer `specs/` → `specs/archive/` et `tasks/` → `tasks/archive/` (`done`), actualiser les pistes actives puis exécuter `sync_tracking.py --offline --ack-editorial --print-delta`.
4. **Clôture `gravity-metrics` en toute dernière étape *(session racine d'atelier uniquement)* :** si `~/.gemini/config/plugins/gravity-metrics/scripts/cli.py` existe *(ou `%USERPROFILE%\.gemini\config\plugins\gravity-metrics\scripts\cli.py` sous Windows ; no-op silencieux — zéro erreur ni message — si absent)*, clore la capture de la session racine courante :
   - `python3 ~/.gemini/config/plugins/gravity-metrics/scripts/cli.py archive <conversation_id> -l "<slug>" --workspace .` *(sous Windows : `python` sur le chemin `%USERPROFILE%\...`)*
   - Si une release (`merge dev -> main`, tag SemVer ou push `main`/tags) intervient un tour plus tard dans la **même** conversation déjà scellée, ré-exécuter avec `--update-sealed`.
   - Ne **jamais** passer `--force`.

## 4. `/gravity-architect add` sans argument (`../`)

- Si `/gravity-architect add` est invoqué sans chemin cible :
  1. Inspecter `projects.json` de l'atelier courant.
  2. Si des dépôts suivis utilisent déjà des chemins relatifs sous `../` (`../<repo>`), proposer directement `../` en **1re option recommandée** via `ask_question` avant de scanner un autre dossier.
  3. Après accord utilisateur, exécuter `python "<PLUGIN_DIR>/scripts/init_workspace.py" --workspace . --discover --scan-dir ../ --json` puis sélectionner les candidats à ajouter via `--add`.

## 5. Onboarding sur workspace vide (greenfield)

- **Détection préalable (`./projects.json` absent) :** avant `sync`, `status`, `spec`, `task` ou `add`, vérifier que `./projects.json` existe dans le dossier courant (ou dans un sous-dossier atelier unique dans `.`). Ne **jamais** appeler `sync_tracking.py` en aveugle et ne pas confondre un dossier vide avec `<architect_home>/projects.json` : basculer directement sur le flux `init` guidé.
- **Découverte & choix en 1 seul `ask_question` :** exécuter `init_workspace.py --workspace . --discover --json` (CWD seul). Si `candidates: []`, poser **1 seul `ask_question`** proposant :
  1. *(a)* Initialiser un atelier vide (`0` projet),
  2. *(b)* Scanner le dossier parent `../` (`--scan-dir ../`),
  3. *(c)* Fournir des chemins directs de dépôts.
- **Options & nommage :** `--name` reste facultatif (sinon nom dérivé automatiquement du dossier courant hors noms génériques vers `Mon Atelier Projets`), `public_mode=false` par défaut ; `public_mode` et `--watch-url` restent des options avancées.
- **Initialisation rapide à `0` projet :** exécuter en 1 commande `python "<PLUGIN_DIR>/scripts/init_workspace.py" --workspace . --run-sync --offline` (0 passe `--ack-editorial` requise).
- **Prochaines commandes à proposer :** `/gravity-architect add <chemin>` (suivre un dépôt existant) et `/gravity-architect spec <slug>` (démarrer une spécification).

## 6. Cycle 4 phases, checkpoint hybride & exécution native

### `/gravity-architect` vide vs `<instruction>`
- **`/gravity-architect` sans argument :** intercepté par le hook `PreInvocation` (`hooks/pre_invocation_architect.py` → `scripts/atelier_status.py`) en lecture seule stricte (`0` écriture disque, `0` écriture `ateliers.json`, `0` capture `gravity-metrics`). Affiche specs actives, tasks par vague/statut, alertes hygiène (`INT-07`) et actions suggérées (`reprendre`, `/gravity-architect <instruction>`, `/gravity-architect sync` ou `init`).
- **`/gravity-architect "<instruction>"` :** orchestre un cycle structuré en **4 phases** :
  1. **Conception :** délégation `research` lecture seule → challenge `/grill-me` → cadrage `/plan` et rédaction `specs/<YYYY-MM-DD>-<slug>.md`.
  2. **Planification :** ancrage exact des symboles et plages de lignes issus de `research` (`::` / `~L`) → découpage `tasks/<YYYY-MM-DD>-<projet>-<slug>.md` (`<= 5` fichiers code, profil `quick` ou `standard`) → contrôle `core/waves.py --check-waves` → **1 checkpoint unique** présenté via artefact (`RequestFeedback=True`) **et/ou `ask_question` explicite** *(bouton `Proceed` absent sur certaines surfaces Antigravity)*.
  3. **Production :** exécution 100 % native via `run_workflow` (`wave_runner.py`, `parallel` *fail-isolated* en `git worktree` temporaires, `apply_on_pass=True`, saut `Planner` si `plan_file`, routage `quick`=`Reviewer flash` / `standard`=`Reviewer pro`, watchdogs `15m`/`6m`) ou `/swarm` natif si chantier couplé, retour compact `<= 10` lignes/dépôt, mini-checkpoint sur `dev` entre vagues et `/compact` racine dès `> 250k` tokens.
  4. **Validation :** exécution de `verify_commands` (`100 %` vertes, *fail-closed* global, ex. `audit_ecosystem.py --verify-parallel --strict`) → `git add`/`commit`/`push origin dev` *(jamais `--force`)* → archivage (`specs/archive/`, `tasks/archive/`, `--offline --ack-editorial`) → mise à jour des docs écosystème → réinstallation en fin de Validation uniquement (`ecosystem_install.py --update --modules <...> --strict`) → récapitulatif final → clôture optionnelle `gravity-metrics` (§3).
