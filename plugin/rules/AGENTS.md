# Gravity Architect

- `/gravity-architect [init|add|sync|status|spec|handoff|archive|audit]` : Hot/Cold, `audits/code/` séparé d'`audits/agents/`.
- Posture stricte lecture seule uniquement si atelier initialisé, jamais sur projet de code ordinaire.
- Scripts (`sync_tracking.py`, `init_workspace.py`, `validate.py`) depuis le plugin installé.
- `init`/`add` : `--discover --json` + `ask_question` (jamais hors CWD sans accord), `sync_tracking.py --print-delta` → édition → `--offline --ack-editorial`.
