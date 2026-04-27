# 04 — Découvertes du budget Excel existant

> **Source** : `REVISION BUDGET 2026 VENTILLE RIST NOU CMD.xlsx` (5,6 MB, 68 feuilles)
> **Méthode** : analyse structurelle via openpyxl, métadonnées seulement (les valeurs financières restent confidentielles, hors repo)
> **Conséquence** : le **modèle de données du cadrage v0.1 doit être pivoté** — ce document explique pourquoi.

---

## 1. Résumé exécutif

Le budget réel n'est **pas organisé autour du plan comptable SYSCOHADA**. Il est organisé autour d'une grille opérationnelle **Marque × Modèle × Mois × Indicateur**. Le compte d'exploitation et le compte de résultat sont des **vues agrégées** construites à partir des feuilles marques.

Conséquences :

- Le data model doit traiter **Brand / VehicleModel / Period / BudgetLine** comme entités centrales (pas Account).
- L'import Excel doit lire en priorité les feuilles marques, pas le P&L.
- Le rapprochement avec SYSCOHADA est une **couche supérieure** (mapping configurable), pas le cœur du modèle.

---

## 2. Inventaire des 68 feuilles

### Feuilles métier — opérationnelles (priorité 1)

| Feuille    | Rôle                           | Lignes × cols | Notes                                                                 |
| ---------- | ------------------------------ | ------------- | --------------------------------------------------------------------- |
| `VW`       | Prévisions Volkswagen 2026     | 59 × 26       | Modèles : Tiguan Trend, Tiguan Life, etc.                             |
| `GW`       | Prévisions Great Wall 2026     | 82 × 27       | Modèles : H9 Lux Essence, Jolion Low, etc.                            |
| `CHERY`    | Prévisions Chery 2026          | 41 × 27       | Modèles : Tiggo 2 Pro Manuel/BVA Confort, etc.                        |
| `LOVOL`    | Prévisions Lovol 2026          | 68 × 16 383   | Inclut FOTON (chargeurs, mini-bus)                                    |
| `SINOTRUK` | Prévisions Sinotruck + DF 2026 | 90 × 16 384   | Camions bennes 8X4, 6X4                                               |
| `SEALAND`  | Prévisions Sealand 2026        | 68 × 16 383   | (Titre A1 = "PREVIONS DE LA MARQUE LOVOL" — copier/coller à corriger) |
| `MOTOS`    | Prévisions motos 2026          | 23 × 16 383   | KTM, Tricycle Isoth                                                   |

### Feuilles métier — agrégats (priorité 2)

| Feuille                                        | Rôle                            | Notes                                                                                   |
| ---------------------------------------------- | ------------------------------- | --------------------------------------------------------------------------------------- |
| `CA VN`                                        | Récap volumes par marque × mois | Source : agrégation des feuilles marques                                                |
| `CA VN 2023`                                   | Volumes 2023 par marque × mois  | Historique                                                                              |
| `CPT EXPL`                                     | Compte d'exploitation 2026      | Lignes : VENTES CHERY, VENTES GW, VENTES LOVOL, VENTES SEALANDS, VENTES SINOTRUCK, etc. |
| `RSTAT`                                        | Compte de résultat synthèse     | Lignes : TA=CA VN, RA=CA SAV, RB=Variation de stocks                                    |
| `Compte de resultat` / `Compte de resultat 24` | P&L détaillé                    | Référence comptable                                                                     |
| `BFR`                                          | Besoin en fonds de roulement    | 41 × 27                                                                                 |
| `SEUIL RENTAB`                                 | Seuil de rentabilité            | 53 × 3                                                                                  |

### Feuilles SAV / atelier (priorité 2)

| Feuille                 | Rôle                   | Colonnes clés                                                                                         |
| ----------------------- | ---------------------- | ----------------------------------------------------------------------------------------------------- |
| `SAV VP`                | Service après-vente VP | Réal S1 2024, Moyens mensuels 2024, Réal 2025, Moyens 2025, Janvier-Décembre 2026, S1, S2, TOTAL 2026 |
| `SAV VL`                | Service après-vente VL | Mêmes colonnes                                                                                        |
| `ATL& MAG`              | Atelier + Magasin      | "MAIN D'ŒUVRE ATELIER QUICK SERVICE / VOLKSWAGEN / ASIAN / TOLERIE-PEINTURE"                          |
| `Budget SAV & MAG 2024` | Budget SAV historique  | 36 × 27                                                                                               |

### Feuilles achats / commandes (priorité 3)

| Feuille               | Rôle                                                              |
| --------------------- | ----------------------------------------------------------------- |
| `ACHAT VP`            | Suivi achats véhicules particuliers (Phase 1, Phase 2 par modèle) |
| `ACHAT VL`            | Suivi achats véhicules légers (chargeurs, camions)                |
| `COMMANDE`            | Commandes (205 lignes, 39 cols)                                   |
| `CMD`                 | Commandes synthèse                                                |
| `FIN CMD`             | Finalisation commandes                                            |
| `COUT CMD`            | Coût commandes                                                    |
| `RECAP BUDGET ACH 25` | Récap budget achats 2025                                          |
| `FRAIS.APP.ACHATS`    | Frais sur achats                                                  |

### Feuilles trésorerie / finance (priorité 3)

| Feuille         | Rôle                            |
| --------------- | ------------------------------- |
| `TVA`           | TVA                             |
| `ENCAISSEMENTS` | Encaissements clients           |
| `DECAISSEMENTS` | Décaissements                   |
| `F F`           | Frais financiers (probablement) |
| `DC`            | À identifier                    |

### Feuilles transactionnelles (priorité 1 pour Phase 4)

| Feuille       | Rôle                                                                                                                                                           |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `VENTES 2023` | **Ventes ligne par ligne** : Date, Client, Désignation, Marque, CA HT Net, CA HT brut, Prix Revient Total, Marge, Représentant, Quantité (240 lignes, 10 cols) |

→ C'est la structure-cible idéale pour notre table `Sale`. Pas besoin d'inventer un schéma, on a la vraie liste de colonnes.

### Feuilles divers / brouillons / autres

| Feuille                                                                                                          | Notes                                                                                |
| ---------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| `Claude Log`                                                                                                     | Présence d'un log d'IA — l'utilisateur a déjà utilisé un assistant IA sur ce fichier |
| `Feuil1`, `Feuil2`, `Feuil3`, `Feuil4`, `Feuil6`, `Feuil7`, `Feuil8`, `Feuil10`, `Feuil11`, `Feuil24`, `Feuil32` | Feuilles auto-nommées (scratch / brouillon)                                          |
| `BROUILLON GW`, `BROUILLON CHERY`, `BROUILLON FOTON`, `BROUILLON CHANGAN`                                        | Brouillons par marque                                                                |
| `PILOTAG`                                                                                                        | "DU CONTROLE BUDGETAIRE AU PILOTAGE STRATEGIQUE" — note méthodologique               |
| `MRKTING`                                                                                                        | Marketing                                                                            |
| `PVN`                                                                                                            | Probablement "Prévisions VN"                                                         |
| `TAIRIF` / `TAR`                                                                                                 | Tarifs                                                                               |
| `BUDGET 2010`                                                                                                    | Tableau cadre / template historique                                                  |
| `UTILITAIRES`                                                                                                    | Outillage Excel                                                                      |
| `CCBMI`                                                                                                          | À identifier                                                                         |
| `2025`                                                                                                           | Données 2025 (325 lignes)                                                            |
| `RIK_PARAMS`                                                                                                     | Paramètres                                                                           |
| `Objectifs commerciaux 2024`                                                                                     | Objectifs commerciaux                                                                |
| `COMPAR BUDGET.` / `COMPAR BUDGETAIRE AUTO`                                                                      | Comparaisons                                                                         |
| `RESUME 2`                                                                                                       | Résumé                                                                               |
| `CT AN`                                                                                                          | À identifier                                                                         |
| `CA GL`                                                                                                          | CA Grand Livre ?                                                                     |
| `CHARGES FONCTIONNEMENT 25` / `CHARGES FONCTIONNEMENT`                                                           | Charges de fonctionnement                                                            |

---

## 3. Schéma type d'une feuille marque (VW, GW, CHERY, LOVOL, etc.)

```
Row 1 :  Titre — "PREVISION DE LA MARQUE <BRAND> 2026"
Row 2 :  Header semestriel
         Col A=marge      Col B=PRIX VENTE      Col C-I=Mois S1
         Col J=Budget S1  Col K=Réal S1
         Col L=PRIX S2    Col M-R=Mois S2
         Col S=Budget S2  Col T=BUDGET 2026 (S1+S2)
Row 3+ :  Bloc de 4 lignes par modèle
         Ligne N   :  <MODEL_NAME> | UNITES | volumes mensuels…
         Ligne N+1 :          | CA      | montants mensuels…
         Ligne N+2 :          | REVIENT | coûts mensuels…
         Ligne N+3 :          | MARGES  | marges mensuelles…
```

### Modèles identifiés (extraits — liste partielle)

> Les noms de modèles sont publics (catalogues constructeurs).

| Marque         | Modèles repérés                                                                               |
| -------------- | --------------------------------------------------------------------------------------------- |
| Volkswagen     | Tiguan Trend, Tiguan Life, T-Cross Highline (vu dans VENTES 2023)                             |
| Great Wall     | H9 Lux Essence, Jolion Low, Wingle 7 DC Standard 2.0L, Wingle 7 DC Luxury 2.0L                |
| Chery          | Tiggo 2 Pro Manuel Confort, Tiggo 2 Pro BVA Confort                                           |
| Lovol / Foton  | Chargeur FL 956, Foton Mini Bus 15P (BJ6549B1PXA), FW215F                                     |
| Sinotruck / DF | Camion benne SIN 8X4 24 m³ (12 roues) Monobloc, Camion benne DF 6X4 18 m³ (10 roues) Monobloc |
| Motos          | KTM, Tricycle Isoth                                                                           |
| Sealand        | (à extraire — feuille présente)                                                               |

### Marques additionnelles découvertes (non listées dans le brief initial)

- **FOTON** — présent dans `BROUILLON FOTON` et lignes de la feuille LOVOL (mini-bus, chargeurs)
- **CHANGAN** — présent dans `BROUILLON CHANGAN`
- **DF** (DongFeng) — co-traité avec SINOTRUK dans la même feuille
- **KTM** — motos, dans `MOTOS`

→ Le référentiel `Brand` doit être étendu de 7 à **10-11 marques**.

---

## 4. Schéma de `VENTES 2023` (transactionnel — gold standard)

| Col | Header (français original) | Type      | Mapping cible (BD)                                            |
| --- | -------------------------- | --------- | ------------------------------------------------------------- |
| A   | Date de Vente              | datetime  | `Sale.sale_date`                                              |
| B   | Intitulé Client            | str       | `Customer.name` (ou FK)                                       |
| C   | Désignation Article        | str       | → décompose en `VehicleModel.name`                            |
| D   | Marque                     | str       | → FK `Brand.code`                                             |
| E   | CA HT Net                  | int       | `Sale.net_price_xof`                                          |
| F   | CA HT brut                 | float     | `Sale.gross_price_xof`                                        |
| G   | Prix Revient Total         | int/float | `Sale.cost_price_xof` (NEW)                                   |
| H   | Marge sur Prix Revient     | int/float | calculé OU `Sale.margin_xof` (NEW)                            |
| I   | Nom représentant           | str       | `Sale.salesperson_id` (FK User)                               |
| J   | Qté Vendues                | int       | `Sale.quantity` (NEW — VENTES 2023 a des ventes multi-unités) |

**Décisions** :

1. **Ajouter `quantity`** sur `Sale` (le modèle initial supposait 1 véhicule = 1 vente, c'est faux pour les motos, pickups en flotte, équipements LOVOL).
2. **Stocker prix de revient et marge** explicitement (`cost_price_xof`, `margin_xof`) plutôt que les recalculer à chaque requête.
3. La colonne `Désignation Article` mélange marque + modèle + version → un service de **normalisation** est nécessaire à l'import (matching fuzzy).

---

## 5. Implications pour le modèle de données (cadrage v0.2)

### 5.1 Nouvelles entités à ajouter

| Entité               | Justification                                                                                                                                                                                    |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `BudgetLineByModel`  | La granularité réelle est **(Brand, Model, Period, Indicator)** pas seulement (Account, Period). Une `BudgetLineByModel` stocke {volume_units, ca_xof, cost_xof, margin_xof} pour un mois donné. |
| `Indicator` (enum)   | UNITES, CA, REVIENT, MARGES                                                                                                                                                                      |
| `MonthBudget`        | Vue agrégée pour calcul rapide                                                                                                                                                                   |
| `Semester` (concept) | Le budget est piloté en **demi-année** (Budget S1, Réal S1, Budget S2, Total 2026) — il faut un type ou un agrégat dédié                                                                         |

### 5.2 Entités à conserver mais reléguer en couche secondaire

| Entité                              | Statut                                                                                                                                                                  |
| ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Account` (SYSCOHADA)               | **Facultatif au MVP** — devient une couche de mapping pour générer le compte de résultat à partir des données opérationnelles. Le pilotage quotidien n'en a pas besoin. |
| `JournalEntry` / `JournalLine`      | **Phase 4** (intégrations Sage), pas MVP.                                                                                                                               |
| `BudgetLine` (générique par compte) | Renommer `BudgetLineByAccount` pour distinguer du modèle opérationnel.                                                                                                  |

### 5.3 Entités à étendre

| Entité          | Modification                                                                                                            |
| --------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `Brand`         | +3 marques : FOTON, CHANGAN, DF (+ KTM si motos sont scope MVP)                                                         |
| `VehicleModel`  | Ajouter `version` (Trend/Life/Confort/BVA…), `category` (Berline/SUV/Pickup/Camion/Engin/Moto), `is_imported`           |
| `Sale`          | Ajouter `quantity`, `cost_price_xof`, `margin_xof`, `customer_text` (libre avant matching), `model_text` (libellé brut) |
| `Period`        | Ajouter `semester` (S1 / S2) pour faciliter les agrégats vus dans le fichier                                            |
| `BudgetVersion` | Ajouter `is_revised` flag (le fichier s'appelle "REVISION BUDGET 2026")                                                 |

### 5.4 Décision architecturale clé

**Pivot du modèle métier** : on travaille **du commercial vers le comptable**, pas l'inverse.

```
┌─────────────────────────────────────────────────────────────┐
│  COUCHE COMMERCIALE (source de vérité métier)               │
│  Brand × VehicleModel × Period × Indicator (UNITES/CA/...)  │
│  + Sale (transactionnel)                                    │
└──────────────┬──────────────────────────────────────────────┘
               │ aggregate via mapping
               ▼
┌─────────────────────────────────────────────────────────────┐
│  COUCHE COMPTABLE (vue dérivée, optionnelle MVP)            │
│  Account (SYSCOHADA) × Period × CostCenter                  │
│  → Compte d'exploitation                                    │
│  → Compte de résultat                                       │
└─────────────────────────────────────────────────────────────┘
```

L'utilisateur saisit son budget **dans le commercial** (ce qu'il fait déjà dans Excel), et le **comptable est généré** automatiquement par mapping.

---

## 6. Sémantique semestrielle confirmée

Le pilotage utilise systématiquement la grille :

- **Janvier-Juin** = Semestre 1 (S1)
- **Juillet-Décembre** = Semestre 2 (S2)
- Colonnes synthèse : Budget S1, Réal S1, Budget S2, Budget Total 2026
- Colonne supplémentaire vue dans `CA VN` : "BUDGET 2025 AJUSTE AUX REALISAT (Real S1+Budget S2)" — révision intra-année

→ L'app doit nativement gérer ces 4 + 1 vues semestrielles dans tous les écrans (pas seulement mensuel et annuel).

---

## 7. Anomalies / quirks à corriger lors de l'import

| Anomalie                        | Détectée dans                                                                                             | Action                                                                                                                     |
| ------------------------------- | --------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Titre A1 erroné (copier/coller) | `SEALAND` (titre = "PREVIONS DE LA MARQUE LOVOL") · `MOTOS` (titre = "PREVISION DE LA MARQUE VOLKSWAGEN") | Logger un warning, ignorer le titre, identifier la marque par le nom de la feuille                                         |
| `cols=16383` ou `16384`         | LOVOL, MOTOS, SINOTRUK, SEALAND, BROUILLON GW/FOTON/CHANGAN                                               | Probablement formatage ayant étiré la sheet. Limiter le scan aux ~30 premières colonnes utiles                             |
| Mélange `int` / `float`         | Toutes les feuilles                                                                                       | Normaliser en `Decimal(18,2)` à l'ingest                                                                                   |
| Cellules NULL fréquentes        | Brand sheets                                                                                              | Traiter NULL = 0 pour les indicateurs UNITES/CA/REVIENT/MARGES (ou conserver NULL si délibéré ?) — **à arbitrer avec DAF** |
| Encodage des accents            | Headers comme "Prévision Janvier 2023"                                                                    | Garder UTF-8 strict ; refuser les imports en CP1252/Latin-1                                                                |
| Variants de noms de marques     | `SINOTRUCK` vs `SINOTRUK`, `SEALAND` vs `SEALANDS`, `GW` vs `GREATWALL`, `GREAT WALL`                     | Table de synonymes (`brand_alias`)                                                                                         |

---

## 8. Données extractibles immédiatement (vs. ce qui nécessite re-saisie)

### Extractibles automatiquement par le parser

- ✅ Volumes mensuels par modèle (UNITES) pour 2026 S1 + S2 + total
- ✅ CA mensuel par modèle (CA)
- ✅ Coût de revient par modèle (REVIENT)
- ✅ Marges par modèle (MARGES)
- ✅ Réalisé S1 2025/2026 quand renseigné
- ✅ Référentiel modèles avec leurs prix unitaires (PRIX VENTE)
- ✅ Marques (avec aliasing)
- ✅ Historique ventes 2023 (VENTES 2023 — 240 lignes)

### Nécessite intervention humaine ou règles à valider

- ❓ Mapping vers le plan SYSCOHADA (compte 701110 = Ventes VN VW etc.) — n'est pas dans l'Excel
- ❓ Définition formelle des centres de profit (cohérence avec `CostCenter` théorique)
- ❓ Règle de gestion des reventes / retours (négatifs ?)
- ❓ Statuts des véhicules (en stock / vendu / livré / facturé) — non présent dans le budget

---

## 9. Prochaine étape : parser opérationnel

Construire `scripts/parse-budget-vn.py` capable de :

1. Ouvrir le fichier Excel (chemin paramétrable)
2. Itérer sur les feuilles marques (configurable : VW, GW, CHERY, LOVOL, SINOTRUK, SEALAND, MOTOS)
3. Détecter le bloc 4 lignes (UNITES / CA / REVIENT / MARGES) par modèle
4. Reconnaître les colonnes mois (D-I S1, M-R S2) + colonnes synthèse (J=Budget S1, K=Réal S1, S=Budget S2, T=Total)
5. Émettre un JSON normalisé : `[{ brand, model, period_code, indicator, scenario, value }]`
6. Reporter : nb modèles trouvés, nb cellules extraites, marques inconnues, anomalies

Le JSON pourra ensuite alimenter directement la base `BudgetLineByModel` du futur backend NestJS.

---

## 10. Statut de validation

Ce document est en **v0.1**. Pour passer à v1.0 :

- [ ] DAF valide les marques étendues (FOTON, CHANGAN, DF, KTM)
- [ ] DAF confirme la sémantique S1/S2 et les vues "ajustée"
- [ ] DAF valide le pivot architectural commercial → comptable
- [ ] Contrôleur valide la liste de modèles extraits par le parser (étape suivante)
- [ ] Décision sur les feuilles SAV/Atelier : Phase 1 ou Phase 2 ?
