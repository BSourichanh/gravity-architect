# Couche froide & Archives historiques

Ce dossier conserve la couche **Cold** (spécifications clôturées et changelogs complets des dépôts suivis), isolée de la couche active (**Hot**) afin de maintenir le coût en tokens minimal.

## Modèle Hot / Cold
- **Couche Hot** *(lue à la demande)* : `AGENTS.md`, `ECOSYSTEM.md`, `tracking/projects/*.md`, `specs/*.md` actives, `handoffs/*.md` ouverts.
- **Couche Cold** *(consultation historique uniquement)* :
  - `changelogs/` — Copies archivées complètes des `CHANGELOG.md` des dépôts suivis.
  - `../specs/archive/` — Spécifications livrées et clôturées.
  - `../handoffs/archive/` — Briefs autonomes livrés et clôturés.
