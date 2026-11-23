# Gravity Architect

- `/gravity-architect [init|add|sync|status|spec|handoff|archive|audit]` : atelier de conception, specs, handoffs et suivi multi-projets lecture seule (Hot / Cold).
- `/gravity-architect audit [projet|all]` : audit **Code & Architecture** en lecture seule dans `audits/code/` (séparé d'`audits/agents/`).
- Posture **Concepteur strict & lecture seule hors atelier** : uniquement dans un atelier initialisé (`AGENTS.md` local), jamais sur les projets de code ordinaires.
- Scripts (`sync_tracking.py`, `init_workspace.py`, `validate.py`) : exécuter depuis le plugin installé (`~/.gemini/config/plugins/gravity-architect/` ou `./plugin/`).
- Pour `init` et `add` : `init_workspace.py --discover --json` + `ask_question` (jamais scanner hors du dossier courant sans accord), puis `sync_tracking.py --print-delta` → édition fiches → `--offline --ack-editorial`.
