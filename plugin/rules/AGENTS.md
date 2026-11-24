# Gravity Architect

- `/gravity-architect [init|add|sync|status|spec|task|archive|audit]` : Hot/Cold, `audits/code/` séparé d'`audits/agents/`.
- Code suivi RO ; plan validé + vérifs vertes (fail-closed) : commit/push dev + install auto ; merge/main/release sur accord humain.
- Scripts (`sync_tracking.py`, `init_workspace.py`, `validate.py`) du plugin installé.
- `init`/`add` : `--discover --json` + `ask_question` (hors CWD sur accord) ; `--print-delta` → édition → `--offline --ack-editorial`.
