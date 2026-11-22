# Gravity Architect

- `/gravity-architect [init|add|sync|status|spec|handoff|archive|audit]` gère un atelier de conception, de spécifications, de handoffs autonomes et de suivi multi-projets en lecture seule (architecture Hot / Cold économe en tokens).
- `/gravity-architect audit [projet|all]` réalise un audit **Code & Architecture** en lecture seule dans `audits/code/` (strictement séparé d'`audits/agents/`).
- La posture **Concepteur strict & lecture seule hors atelier** s'applique **uniquement** à l'intérieur d'un atelier initialisé (selon son `AGENTS.md`), jamais globalement sur vos projets de code ordinaires.
- Exécuter les scripts du plugin (`sync_tracking.py`, `init_workspace.py`, `validate.py`) depuis le répertoire d'installation du plugin (`~/.gemini/config/plugins/gravity-architect/` ou source du dépôt).
- Pour `/gravity-architect init` et `add`, orchestrer via `init_workspace.py --discover --json` + `ask_question` (sans jamais scanner hors du dossier courant sans accord explicite), puis enchaîner `sync_tracking.py --print-delta` → édition fiches → `--offline --ack-editorial`.
