# Audit Code & Architecture — <cible>

- **Date :** YYYY-MM-DD
- **Cible :** `<projet|ecosystem>`
- **Branche & Commit :** `<branche>` @ `<hash>`
- **Périmètre :** *Lecture seule — dépôts, contrats et tests inspectés.*
- **Verdict :** `PASS` | `WARN` | `FAIL`

---

## 1. Inventaire dépôts / branches / commits & versions
| Projet | Branche active | Commit (`HEAD`) | Version manifeste | Tag (`main`) | État |
|---|---|---|---|---|---|
| `<id>` | `<branche>` | `<hash>` | `<version>` | `<tag>` | `OK` / `Écart` |

## 2. Qualité d'ingénierie (KISS / YAGNI / DRY / SOLID / CUPID)
- **Lisibilité & découpage :** *Observations factuelles sur la modularité, la cohésion et la dette technique.*
- **Duplication & complexité :** *Fonctions critiques, duplication éventuelle et couplages observés.*
- **Frontières domaine & découplage (Hexagonal / DDD pragmatique) :** *Si le domaine est complexe ou multi-adapteurs, séparation domaine / ports / adapteurs vérifiée sans sur-ingénierie sur les scripts simples.*

## 3. Invariants & contrats (`config/module.json`, `plugin.json`, séparation Hot / Cold)
- **Manifeste & contrat module :** *Conformité des champs, du schéma et des commandes.*
- **Séparation Hot / Cold & vagues (`tasks/`) :** *Respect de la lecture seule hors atelier, isolation, ancres hybrides (`<= 5` fichiers code) et budgets tokens.*

## 4. Sécurité, hygiène & tests (stdlib, UTF-8, LF)
- **Dépendances & sûreté :** *100 % bibliothèque standard Python 3.10+, zéro `shell=True`, absence de secrets/fuites.*
- **Encodage & vérifications :** *UTF-8 sans BOM, fins de ligne LF et résultats de la suite de tests.*

## 5. Constats `CODE-XX-N` (`P0` / `P1` / `P2`)
| ID | Sévérité | Fichier / Symbole | Constat factuel | Action recommandée |
|---|---|---|---|---|
| `CODE-01-1` | `P1` | `chemin/fichier.py` | *Constat factuel...* | *Action ciblée...* |

## 6. Plan d'actions priorisé
1. **P0 (bloquant) :** *Aucun ou action corrective immédiate.*
2. **P1 (important) :** *Correction ou refactorisation prioritaire.*
3. **P2 (amélioration) :** *Durcissement ou nettoyage optionnel.*
