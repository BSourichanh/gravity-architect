# Task — `<projet>` : [Titre court du lot]

- **Vague :** `1` *(entier >= 1)*
- **Dépôt cible :** `<nom-du-dépôt>` (`<chemin-relatif>`)
- **Branche attendue :** `dev`
- **Dépendances :** `aucune` *(IDs de tasks antérieures, ex. `2026-11-24-core-lot1`)*
- **Profil workflow :** `standard` *(quick | standard | deep)*
- **Spec source :** `specs/<YYYY-MM-DD>-<slug>.md`
- **Date / Statut :** `YYYY-MM-DD` — `ready`

---

## Contexte & Objectif
*Problème et résultat attendu, formulés de façon autonome.*

## Décisions figées
- Décision 1 : ...
- Décision 2 : ...

## Périmètre (`<= 5` fichiers code hors tests/docs)
- **Inclus :**
  - `chemin/fichier.py` *(code)*
  - `tests/test_fichier.py` *(test, non-code)*
  - `CHANGELOG.md` *(entrée `[Unreleased]` produite en worktree, non-code hors quota `<= 5` — 0 édition directe en Phase 4)*
- **Exclu :** ...

## Ancres exactes
- `chemin/fichier.py::symbole (~L10-L45)` — *modification attendue*
- `tests/test_fichier.py` — *couverture unitaire attendue*
- `CHANGELOG.md` — *entrée `[Unreleased]` en worktree*

## Invariants à respecter
- *(Reprendre les invariants exacts du dépôt cible : branche `dev`, conventions Git, stdlib/encodage, tests et validations obligatoires.)*

## Critères d'acceptation & Vérifications obligatoires
- [ ] Critère 1
- [ ] Entrée `[Unreleased]` ajoutée dans `CHANGELOG.md` en worktree (zéro édition directe racine en Phase 4).
- [ ] Commandes passées avec 0 erreur (`python3` sous Linux/macOS, `python` sous Windows) :
  ```bash
  # Commandes du dépôt cible (ex. python3 plugin/scripts/validate.py --strict && python3 -m unittest discover -s tests)
  ```

## Retour attendu pour l'atelier
Fournir fichiers modifiés, résumé des tests ajoutés/passés, résultat exact des vérifications et confirmation de l'entrée `CHANGELOG.md`.
