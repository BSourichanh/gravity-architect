# Workflows Avancés & Hygiène Opérationnelle

Fiche de référence chargée à la demande depuis [`SKILL.md`](../SKILL.md) *(progressive disclosure : 0 taxe tokens au chargement initial)*.

## 1. Post-handoff & Passerelle Bridge (`gravity-bridge`)

### Statut obligatoire après rédaction d'un handoff
- Après création de `handoffs/<YYYY-MM-DD>-<projet>-<slug>.md`, afficher explicitement le statut **`rédigé, non déployé`**.
- Rappeler à l'utilisateur la possibilité d'envoyer le lot via `/gravity-bridge` (sans jamais envoyer de message Bridge proactivement).

### Passerelle guidée depuis l'atelier
- Si l'utilisateur demande explicitement d'envoyer, transmettre ou dispatcher des handoffs depuis l'atelier *(même sans saisir le préfixe `/gravity-bridge`)* :
  1. Préparer un récapitulatif structuré : dépôt(s) cible(s), objet(s), `file_refs` relatifs *(max 20)* et posture (`approved=true, dispatch=true` ou dépôt boîte aux lettres seule).
  2. Déclencher **1 seul `ask_question` récapitulatif** demandant validation explicite de cet envoi.
  3. Cette validation unique vaut simultanément activation de la passerelle Bridge et feu vert humain `approved=true, dispatch=true` : **0 appel MCP silencieux**, **0 double confirmation**.
- Si l'outil MCP Bridge est indisponible dans la session courante, indiquer les cibles et fichiers prêts sans improviser d'envoi hors protocole.

## 2. Hygiène tokens, Plan Mode & délégation

### `sync` no-op en Plan Mode
- Lorsqu'un `/gravity-architect` ou `/gravity-architect sync` est exécuté en Plan Mode :
  - Lancer `sync_tracking.py --check --print-delta`.
  - Si le delta retourne `NO_EDITORIAL_CHANGES` avec `0` fichier auto-mis à jour (`<!-- AUTO:START/END -->`) **et** que l'atelier figure déjà dans `<architect_home>/ateliers.json`, répondre directement en 5–8 lignes **sans appeler `exit_plan_mode`**.

### Contenu de `exit_plan_mode(plan=...)`
- Ne **jamais** recopier une spécification, un handoff ou un rapport d'audit complet dans `exit_plan_mode(plan=...)`.
- Limiter `plan` à un résumé structurel concis (périmètre, fichiers ciblés, vérifications attendues) ; la matière détaillée reste dans `specs/`, `handoffs/` ou `audits/code/`.

### Exploration multi-fichiers & cycle de session
- Ne jamais charger une grappe de fichiers source des dépôts suivis dans la session racine ; après lecture du micro-delta, déléguer toute exploration multi-fichiers lecture seule à un sous-agent dédié (`research`) avec périmètre borné.
- Après production d'un lot de `handoffs`, suggérer à l'utilisateur `/compact` ou l'ouverture d'une nouvelle session pour préserver le budget contexte.

## 3. Callbacks Bridge, `--ack-editorial` & clôture Git / install

### Garde `--ack-editorial` face au WIP
- Ne **jamais** exécuter `sync_tracking.py --ack-editorial` tant que des lots restent en WIP non commité dans les dépôts suivis (`git status` sale ou modifications en cours non validées).
- N'exécuter `--offline --ack-editorial --print-delta` qu'après mise à jour éditoriale effective et vérification que l'état suivi est stabilisé.

### Consultation des jobs Bridge
- Pour suivre un job ou callback émis vers un workspace tiers, utiliser `manage_thread(action="get_job")` *(jamais `read_thread` complet en boucle)* afin d'éviter la saturation du contexte.

### Clôture Git & réinstallation écosystème
- Sur feu vert humain explicite, après revue, vérifications vertes et commit sur `dev` *(jamais `git push` sans demande explicite)*, recommander la réinstallation coordonnée via `ecosystem_install.py --update --modules <...> --strict` (`python3` sous Linux/macOS, `python` sous Windows) plutôt qu'un `install.py --strict` isolé, afin de maintenir la cohérence entre modules installés.

## 4. `/gravity-architect add` sans argument (`../`)

- Si `/gravity-architect add` est invoqué sans chemin cible :
  1. Inspecter `projects.json` de l'atelier courant.
  2. Si des dépôts suivis utilisent déjà des chemins relatifs sous `../` (`../<repo>`), proposer directement `../` en **1re option recommandée** via `ask_question` avant de scanner un autre dossier.
  3. Après accord utilisateur, exécuter `python "<PLUGIN_DIR>/scripts/init_workspace.py" --workspace . --discover --scan-dir ../ --json` puis sélectionner les candidats à ajouter via `--add`.
