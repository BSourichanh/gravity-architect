# [Titre concis du sujet]

- **Spec ID :** `SPEC-<DOMAINE>-<NN>`
- **Date :** YYYY-MM-DD
- **Statut :** `draft` | `validated` | `superseded`
- **Critères d'acceptation :** `AC-1`, `AC-2`
- **Projets impactés :** `<projet-1>` | `<projet-2>`
- **Tasks :** *(liens relatifs vers `../tasks/...`)*

---

## 1. Problème & Critères de succès
*Problème concret, exigences couvertes (`R1–R4`, `AC-*`) et résultat mesurable attendu.*

## 2. Capacités existantes vérifiées
*Ce que les outils, plateformes ou briques déjà en place couvrent déjà, et pourquoi un ajout reste justifié.*

## 3. Options & Arbitrage
| Option | Avantages | Risques / Coût | Verdict |
|---|---|---|---|
| A | ... | ... | **Retenue** |
| B | ... | ... | Rejetée |

## 4. Architecture retenue
*Flux, contrats de données, cas limites, comportement fail-closed et plan de tests. Si le domaine métier est riche ou multi-adapteurs, expliciter les frontières (domaine / ports / adapteurs) sans sur-ingénierie (KISS/YAGNI).*

## 5. Impacts & Invariants vérifiés
- Contrôle effectué contre les fiches projet dans [`tracking/projects/`](../tracking/projects/_TEMPLATE.md) et la documentation d'architecture de l'atelier.

## 6. Découpage en tasks (vagues)

| Task ID | Vague | Dépôt cible | Fichier task | Résumé |
|---|---|---|---|---|
| `TASK-<DOMAINE>-<NN>` | `1` | `<id>` | [`YYYY-MM-DD-w1-<repo>-<slug>.md`](../tasks/) | Résumé concis du lot |
