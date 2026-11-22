# Gravity Architect

- `/gravity-architect [init|sync|status|spec|handoff|archive]` gère un atelier de conception, de spécifications, de handoffs autonomes et de suivi multi-projets en lecture seule (architecture Hot / Cold économe en tokens).
- La posture **Concepteur strict & lecture seule hors atelier** s'applique **uniquement** à l'intérieur d'un atelier initialisé (selon son `AGENTS.md`), jamais globalement sur vos projets de code ordinaires.
- Exécuter les scripts du plugin (`sync_tracking.py`, `init_workspace.py`, `validate.py`) depuis le répertoire d'installation du plugin (`~/.gemini/config/plugins/gravity-architect/` ou source du dépôt).
