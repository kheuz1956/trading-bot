# 01 — Cadrage du projet

> **Statut** : v0.1 — hypothèses à valider/corriger par le métier
> **Périmètre** : application interne de suivi budgétaire et pilotage financier
> **Auteur** : Claude (assistant) en collaboration avec Cheikh Mbacké Dieng

---

## 1. Contexte

Concessionnaire automobile multi-marques distribuant **Volkswagen, Great Wall, Haval, SINOTRUK, Lovol, Chery, Sealands**, avec trois activités intégrées :

1. **Vente de véhicules neufs (VN)** — cœur de marge
2. **Service après-vente (SAV)** — atelier + pièces de rechange
3. **Usine d'assemblage** — production locale (probablement CKD/SKD)

L'objectif de l'application est de fournir un **outil de pilotage budgétaire** unifié sur ces 3 activités, avec analyse d'écarts, forecasting et tableaux de bord.

---

## 2. Hypothèses de cadrage (à valider)

> Chaque ligne marquée **🟡 HYP** est une hypothèse à confirmer ou corriger. Une fois validée, elle passe à **🟢 OK**.

### 2.1 Pays, fiscalité, comptabilité

| #   | Sujet                      | Hypothèse                                                                       | Statut |
| --- | -------------------------- | ------------------------------------------------------------------------------- | ------ |
| H1  | Pays d'opération principal | **Sénégal** (déduit du contexte utilisateur)                                    | 🟡 HYP |
| H2  | Référentiel comptable      | **SYSCOHADA OHADA révisé** (PCG 2018)                                           | 🟡 HYP |
| H3  | Fiscalité véhicules        | TVA 18 %, droits de douane variables par catégorie HS, écotaxe selon âge        | 🟡 HYP |
| H4  | Multi-pays                 | **Non** — un seul pays au démarrage. Architecture prévue pour extension future. | 🟡 HYP |

### 2.2 Devises

| #   | Sujet               | Hypothèse                                                         | Statut |
| --- | ------------------- | ----------------------------------------------------------------- | ------ |
| H5  | Devise de tenue     | **FCFA (XOF)** — toute la comptabilité légale                     | 🟡 HYP |
| H6  | Devises secondaires | **EUR, USD, CNY** (achats imports : VW Allemagne, Chinois divers) | 🟡 HYP |
| H7  | Taux de change      | Fixe pour XOF↔EUR (655,957). Cours quotidien BCEAO pour USD/CNY.  | 🟡 HYP |

### 2.3 Existants à intégrer

| #   | Sujet                                       | Hypothèse                                                                              | Statut |
| --- | ------------------------------------------- | -------------------------------------------------------------------------------------- | ------ |
| H8  | Logiciel comptable                          | **Sage 100** ou équivalent francophone (Saari, Tompro). Export CSV/Excel/ODBC supposé. | 🟡 HYP |
| H9  | GESCOM                                      | **Sage Gestion Commerciale** ou ERP propriétaire avec base SQL accessible              | 🟡 HYP |
| H10 | CRM                                         | À définir / inexistant — saisie Excel actuelle. **Hors MVP**.                          | 🟡 HYP |
| H11 | DMS (Dealer Management System) constructeur | Volkswagen impose souvent un DMS dédié (ex: Incadea). À traiter en **Phase 4**.        | 🟡 HYP |

### 2.4 Volume & échelle

| #   | Sujet                       | Hypothèse                                                                | Statut |
| --- | --------------------------- | ------------------------------------------------------------------------ | ------ |
| H12 | Véhicules vendus / an       | **800 à 2 000** (concessionnaire moyen Afrique de l'Ouest multi-marques) | 🟡 HYP |
| H13 | Ordres de réparation / mois | **1 500 à 4 000** (incluant entretiens)                                  | 🟡 HYP |
| H14 | Références pièces           | **20 000 à 100 000** SKU actifs                                          | 🟡 HYP |
| H15 | Utilisateurs simultanés     | **20 à 50** au pic (consultation + saisie contrôleurs)                   | 🟡 HYP |
| H16 | Lignes comptables / mois    | **50 000 à 200 000** écritures                                           | 🟡 HYP |

### 2.5 Équipe, hébergement, contraintes

| #   | Sujet                      | Hypothèse                                                                                                    | Statut |
| --- | -------------------------- | ------------------------------------------------------------------------------------------------------------ | ------ |
| H17 | Équipe projet              | **1 à 3 développeurs** + 1 référent métier (DAF ou contrôleur de gestion) + Claude en pair-programming       | 🟡 HYP |
| H18 | Hébergement                | **Scaleway Paris (zone fr-par-1)** — latence Dakar ≈ 80-120 ms, OVH/Scaleway moins chers qu'AWS, francophone | 🟡 HYP |
| H19 | Souveraineté               | Acceptation hébergement EU. Si exigence stricte SN → option DC local (Sonatel/Orange Business).              | 🟡 HYP |
| H20 | Échéance pilote            | **3 mois** pour pilote MVP utilisable (Vente VN uniquement)                                                  | 🟡 HYP |
| H21 | Budget infra mensuel cible | **< 500 € / mois** sur les 6 premiers mois (1 BD + 1 backend + 1 frontend + monitoring)                      | 🟡 HYP |

---

## 3. Périmètre du MVP (Phase 1)

### Inclus (✅)

- **Une seule activité** : vente de véhicules neufs
- **Un seul cycle budgétaire** : exercice fiscal annuel + révisé semestriel
- **Trois scénarios** : optimiste / réaliste / pessimiste
- **KPIs essentiels VN** : CA par marque, marge brute, coût moyen par véhicule, stock VN, BFR-VN
- **Imports comptables manuels** : upload CSV/Excel avec mapping de comptes → lignes budgétaires
- **Auth basique** : login email/password, 4 rôles (DG, DAF, Contrôleur, Consultation)
- **Dashboards web** : 5-7 écrans clés
- **Audit trail** : journalisation des modifications budgétaires

### Exclus du MVP (⛔ à traiter en Phases 2+)

- SAV, atelier, pièces
- Usine d'assemblage et coûts de revient produits finis
- CRM et pipeline commercial
- Intégrations natives Sage / GESCOM (manuel d'abord, automatisation Phase 4)
- Mobile native
- ML / détection d'anomalies (Phase 6)
- Multi-pays / multi-entités juridiques

---

## 4. Glossaire métier

| Terme                | Définition                                                                       |
| -------------------- | -------------------------------------------------------------------------------- |
| **CAPEX**            | Capital Expenditure — investissements (véhicules de démo, outillage atelier, IT) |
| **OPEX**             | Operating Expenditure — charges courantes (salaires, loyers, énergie)            |
| **CA**               | Chiffre d'affaires                                                               |
| **MB**               | Marge brute = CA - coût d'achat des marchandises vendues (COGS)                  |
| **MN**               | Marge nette = MB - charges d'exploitation - charges financières                  |
| **BFR**              | Besoin en fonds de roulement = stock + créances clients - dettes fournisseurs    |
| **DAF**              | Directeur Administratif et Financier                                             |
| **DG**               | Directeur Général                                                                |
| **OR**               | Ordre de Réparation (SAV)                                                        |
| **MO**               | Main d'œuvre (heures atelier facturables)                                        |
| **VN**               | Véhicule Neuf                                                                    |
| **VO**               | Véhicule d'Occasion                                                              |
| **VAD**              | Véhicule à Disposition (de démo, de courtoisie)                                  |
| **CKD / SKD**        | Completely / Semi Knocked Down — véhicules importés en kit pour assemblage local |
| **HS**               | Système Harmonisé (codes douaniers)                                              |
| **SYSCOHADA**        | Système Comptable de l'OHADA (référentiel comptable des 17 pays OHADA)           |
| **PCG**              | Plan Comptable Général                                                           |
| **BCEAO**            | Banque Centrale des États de l'Afrique de l'Ouest (émet le FCFA XOF)             |
| **DMS**              | Dealer Management System — ERP métier dédié concessionnaires                     |
| **Forecast**         | Prévision de fin d'exercice basée sur réalisé partiel + projection               |
| **Rolling forecast** | Forecast actualisé en continu (mensuel ou trimestriel) sur 12-18 mois glissants  |
| **Variance / Écart** | Différence Budget vs Réalisé, décomposée en effets : volume, prix, mix, change   |
| **Centre de profit** | Unité organisationnelle dont le résultat (CA - coûts) est mesuré                 |
| **Centre de coûts**  | Unité organisationnelle dont seuls les coûts sont mesurés                        |

---

## 5. Acteurs / personas

| Persona                        | Périmètre                 | Besoins clés                                                              |
| ------------------------------ | ------------------------- | ------------------------------------------------------------------------- |
| **DG**                         | Vue globale               | Dashboards consolidés, alertes critiques, mobile-friendly                 |
| **DAF**                        | Toutes activités          | Saisie/validation budgets, analyse écarts, forecast, drill-down comptable |
| **Contrôleur de gestion**      | Toutes activités          | Construction budget, analyses ad-hoc, exports vers Excel, commentaires    |
| **Chef département VN**        | Vente VN uniquement       | Suivi de son budget, prévisions ventes, analyse par marque/modèle         |
| **Chef SAV**                   | SAV uniquement (Phase 2+) | Suivi atelier, productivité MO, marge pièces                              |
| **Directeur usine**            | Production (Phase 5+)     | Coûts d'assemblage, taux de rebut, productivité                           |
| **Comptable**                  | Saisie / import           | Upload des balances, rapprochement avec budget                            |
| **Auditeur (interne/externe)** | Lecture seule + audit log | Traçabilité des modifications, exports certifiés                          |

---

## 6. Risques identifiés et mitigations

| #   | Risque                                                               | Impact   | Probabilité | Mitigation                                                                            |
| --- | -------------------------------------------------------------------- | -------- | ----------- | ------------------------------------------------------------------------------------- |
| R1  | Refus métier de saisir/maintenir les budgets dans un nouvel outil    | Critique | Haute       | Onboarding fort, import depuis Excel existant, formation, ambassadeur métier          |
| R2  | Plan comptable réel ≠ SYSCOHADA standard (comptes créés ad-hoc)      | Élevé    | Élevée      | Mapping configurable, tolérance comptes 6/7 non standards                             |
| R3  | Données comptables non fiables (corrections rétroactives fréquentes) | Élevé    | Moyenne     | Versioning des imports, alerte sur recalculs, snapshot mensuel figé                   |
| R4  | Connectivité Sage/GESCOM impossible (logiciel fermé, pas d'API)      | Moyen    | Élevée      | Plan B = export CSV manuel mensuel ; Plan C = scraping ODBC en lecture seule          |
| R5  | Latence cloud EU pour utilisateurs Dakar                             | Faible   | Faible      | Mesure dès Phase 0, CDN Cloudflare frontend, repli sur Sonatel si > 200 ms            |
| R6  | Coupures électriques / connectivité utilisateurs                     | Moyen    | Élevée      | PWA offline-first, file d'attente locale de saisies                                   |
| R7  | Sécurité données financières                                         | Critique | Moyenne     | Audit log immutable, chiffrement at rest + in transit, sauvegardes 3-2-1, RBAC strict |
| R8  | Scope creep (ajout SAV/usine en Phase 1)                             | Élevé    | Élevée      | Roadmap signée, gel du scope MVP, feature flags pour le reste                         |
| R9  | Volkswagen impose son DMS et empêche notre intégration               | Moyen    | Moyenne     | Réutiliser les exports DMS plutôt que les remplacer ; négocier des exports comptables |
| R10 | Départ du référent métier interne                                    | Critique | Moyenne     | Documentation continue, démos hebdo enregistrées, code review croisée                 |

---

## 7. Définition du succès du MVP

Le MVP (fin Phase 1) est considéré **réussi** si :

1. ✅ **Le DAF saisit/importe le budget annuel VN** sans support technique en moins de 2 h
2. ✅ **Le contrôleur de gestion charge la balance comptable mensuelle** et voit les écarts en moins de 5 min
3. ✅ **Le DG consulte un dashboard CA/marge/écart** depuis son téléphone en moins de 30 sec
4. ✅ Le système gère **l'exercice fiscal complet** (12 mois) sans pertes de données
5. ✅ Les **3 scénarios** (optimiste/réaliste/pessimiste) coexistent et sont comparables
6. ✅ Audit log retient **100 % des modifications** budgétaires avec utilisateur + timestamp
7. ✅ **0 régression** lors des montées de version (CI/CD avec tests E2E)
8. ✅ **Disponibilité ≥ 99 %** sur les heures ouvrées (8h-19h GMT, lun-sam)

---

## 8. Hors-périmètre explicite (à arbitrer plus tard)

- Module RH / paie (le plan demande "Capital humain" — uniquement vue budgétaire des charges salariales, pas la paie elle-même)
- Module GED / archivage légal des pièces comptables
- Outil de consolidation multi-sociétés (si holding existe)
- Trésorerie pure (cash-flow management) — peut être ajoutée en Phase 3.5
- E-facturation / dématérialisation fiscale

---

## 9. Décisions de gouvernance proposées

| Item                      | Proposition                                      |
| ------------------------- | ------------------------------------------------ |
| Cycle de revue produit    | Hebdo 30 min : sprint review + démo              |
| Validation des écarts MVP | DAF en lecture, DG en signature                  |
| Outil de suivi de tickets | GitHub Issues (gratuit, suffisant)               |
| Communication équipe      | Slack ou WhatsApp Business                       |
| Revue de code             | Pull Request obligatoire avec 1 reviewer minimum |
| Branche de production     | `main` (toujours déployable)                     |
| Branches de feature       | `feat/<id>-<slug>`                               |

---

## 10. Validation de ce document

Pour passer ce document de **v0.1 (hypothèses)** à **v1.0 (cadrage acté)** :

- [ ] DAF / contrôleur de gestion valide les hypothèses **H1 à H21**
- [ ] DG valide le périmètre MVP (§3)
- [ ] DG valide le succès du MVP (§7)
- [ ] Budget infra (H21) approuvé par finance
- [ ] Hébergement (H18-H19) validé par DSI / juridique

**Tant que ce document n'est pas en v1.0, le développement reste en "scaffold + spec only" — pas de feature métier figée.**
