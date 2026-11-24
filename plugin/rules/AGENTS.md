# Gravity Architect

- `/gravity-architect` vide : RO 0-token (`PreInvocation`). `<instruction>` : 4 phases ; `[init|add|sync|status|spec|task|archive|audit]`, Hot/Cold, `audits/code/` isolé d'`audits/agents/`.
- Code suivi RO ; plan validé + vérifs vertes (fail-closed) : commit/push dev + install auto ; merge/main/release sur accord humain.
- Scripts (`atelier_status.py`, `sync_tracking.py`, `init_workspace.py`, `validate.py`) installés.
- `init`/`add` : `--discover --json` + `ask_question`.
