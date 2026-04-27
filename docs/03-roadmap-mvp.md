# 03 — Roadmap MVP & user stories

> **Statut** : v0.1 — découpage Phase 1 (Vente VN). Les phases 2-7 sont esquissées en fin de document.
> **Méthode** : Sprints de 2 semaines. Découpage user-story avec critères d'acceptation. Definition of Done partagée.

---

## 1. Vue d'ensemble — toutes phases

| Phase | Activité             | Durée   | Livrable principal                       | Statut         |
| ----- | -------------------- | ------- | ---------------------------------------- | -------------- |
| **0** | Cadrage              | 2-3 sem | Docs 01/02/03 + validation               | 🟡 En cours    |
| **1** | MVP — Vente VN       | 6-8 sem | App utilisable, budget+réalisé+écarts VN | ⏳ À démarrer  |
| **2** | SAV + pièces         | 4-6 sem | Module OR, MO, marge pièces              | ⏳             |
| **3** | Forecast & Scénarios | 3-4 sem | Rolling forecast, simulations            | ⏳             |
| **4** | Intégrations natives | 4-6 sem | Connecteurs Sage / GESCOM                | ⏳             |
| **5** | Usine d'assemblage   | 6-8 sem | Coûts de revient, BOM, écarts production | ⏳             |
| **6** | BI avancé & ML       | 4-6 sem | Anomalies, prédictif                     | ⏳             |
| **7** | Mobile native        | 3-4 sem | App native si PWA insuffisante           | ⏳ Optionnelle |

**Total estimé** : 8 à 12 mois. Premier pilote utilisable fin Phase 1 (~3 mois).

---

## 2. Phase 1 — MVP Vente VN — Découpage en sprints

### Sprint 1 (semaines 1-2) — **Fondations techniques**

**Objectif** : poser l'infrastructure runtime et la première migration BD.

| ID     | User story                                                                                                                                                                                      | Estimation | Priorité |
| ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- | -------- |
| US-001 | En tant que dev, j'initialise une stack NestJS modulaire dans le repo TS existant                                                                                                               | 2 j        | P0       |
| US-002 | En tant que dev, je configure PostgreSQL local (Docker Compose) + Prisma                                                                                                                        | 2 j        | P0       |
| US-003 | En tant que dev, j'écris la 1re migration Prisma : `User`, `Role`, `Permission`, `AuditLog`, `Currency`, `ExchangeRate`, `FiscalYear`, `Period`, `Account`, `CostCenter`, `Department`, `Brand` | 3 j        | P0       |
| US-004 | En tant que dev, j'écris un seed minimal : 1 DG + 1 DAF, FY2026 + 12 périodes, plan SYSCOHADA importé, 7 marques                                                                                | 2 j        | P0       |
| US-005 | En tant que dev, je configure CI GitHub Actions (lint, typecheck, test, build)                                                                                                                  | 1 j        | P0       |

**Critères d'acceptation Sprint 1** :

- [ ] `docker compose up` lance PostgreSQL local
- [ ] `npm run db:migrate` applique 1 migration sans erreur
- [ ] `npm run db:seed` insère les données minimales
- [ ] `npm run build` produit un artefact NestJS exécutable
- [ ] CI verte sur PR vers `main`

---

### Sprint 2 (semaines 3-4) — **Auth & sécurité**

**Objectif** : login fonctionnel, RBAC, audit log.

| ID     | User story                                                                                                                                 | Estimation | Priorité |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------ | ---------- | -------- |
| US-010 | En tant qu'utilisateur, je me connecte avec email + mot de passe et reçois un JWT                                                          | 2 j        | P0       |
| US-011 | En tant qu'admin, j'active le 2FA TOTP pour mon compte                                                                                     | 2 j        | P1       |
| US-012 | En tant que dev, je code un guard NestJS pour vérifier rôle + permission par endpoint                                                      | 2 j        | P0       |
| US-013 | En tant que système, je log toute mutation (CREATE/UPDATE/DELETE) sur `BudgetLine`, `JournalEntry`, `User` dans `AuditLog` automatiquement | 3 j        | P0       |
| US-014 | En tant qu'auditeur, je consulte la liste des modifications d'une entité (page `/audit/<entityType>/<id>`)                                 | 1 j        | P1       |
| US-015 | En tant qu'admin, je crée/désactive un utilisateur et lui assigne des rôles                                                                | 2 j        | P0       |

**Critères d'acceptation** :

- [ ] Endpoint `POST /auth/login` retourne JWT 8h + refresh 7j
- [ ] Endpoint protégé sans header → 401
- [ ] Endpoint protégé sans permission → 403
- [ ] AuditLog rempli pour 5 actions de test
- [ ] Tests E2E auth verts

---

### Sprint 3 (semaines 5-6) — **Budget : saisie & versions**

**Objectif** : créer un budget complet pour FY2026 VN.

| ID     | User story                                                                                                             | Estimation | Priorité |
| ------ | ---------------------------------------------------------------------------------------------------------------------- | ---------- | -------- |
| US-020 | En tant que contrôleur de gestion, je crée une `BudgetVersion` initiale FY2026 scénario `BASE`                         | 1 j        | P0       |
| US-021 | En tant que contrôleur, je saisis ligne par ligne un budget mensuel (montant + commentaire)                            | 3 j        | P0       |
| US-022 | En tant que contrôleur, j'importe un budget depuis Excel (template .xlsx fourni)                                       | 3 j        | P0       |
| US-023 | En tant que contrôleur, je duplique une `BudgetVersion` BASE en `OPTIMIST` (+10 % sur classe 7) et `PESSIMIST` (-10 %) | 2 j        | P1       |
| US-024 | En tant que DAF, je vois les 3 scénarios côte à côte sur un tableau récap                                              | 2 j        | P0       |
| US-025 | En tant que DG, j'approuve une `BudgetVersion` (passage `DRAFT` → `APPROVED` → `LOCKED`)                               | 1 j        | P0       |

**Critères d'acceptation** :

- [ ] Budget de 12 mois × 50 lignes saisi en < 30 min via UI
- [ ] Import Excel valide ou rejette avec message clair par ligne
- [ ] Une fois `LOCKED`, toute modification est refusée 403
- [ ] Auditlog enregistre approve + lock

---

### Sprint 4 (semaines 7-8) — **Réalisé : import compta**

**Objectif** : ingérer le grand livre / balance et calculer les écarts.

| ID     | User story                                                                                                                   | Estimation | Priorité |
| ------ | ---------------------------------------------------------------------------------------------------------------------------- | ---------- | -------- |
| US-030 | En tant que comptable, j'upload une balance mensuelle au format CSV/Excel                                                    | 2 j        | P0       |
| US-031 | En tant que système, je détecte un doublon d'import via `file_hash` et refuse                                                | 1 j        | P0       |
| US-032 | En tant que comptable, je vois un aperçu (preview) avant validation : nb lignes, total débit/crédit, comptes inconnus, écart | 2 j        | P0       |
| US-033 | En tant que comptable, je mappe les comptes inconnus vers le PCG SYSCOHADA via UI                                            | 2 j        | P0       |
| US-034 | En tant que système, je rejette tout `JournalEntry` avec déséquilibre débit≠crédit                                           | 1 j        | P0       |
| US-035 | En tant que système, je calcule les écarts Budget vs Réalisé et rafraîchis la vue matérialisée `Variance`                    | 2 j        | P0       |
| US-036 | En tant que contrôleur, j'annule un import (`ROLLED_BACK`) avec motif                                                        | 1 j        | P1       |

**Critères d'acceptation** :

- [ ] Import CSV de 10 000 lignes en < 60 sec
- [ ] Variance recalculée sous 30 sec après import
- [ ] Rejet sur fichier déséquilibré avec message ligne par ligne
- [ ] Rollback réversible

---

### Sprint 5 (semaines 9-10) — **Dashboards & écrans clés**

**Objectif** : 5 écrans de pilotage pour DG/DAF/Contrôleur.

| ID     | User story                                                                                                                | Estimation | Priorité |
| ------ | ------------------------------------------------------------------------------------------------------------------------- | ---------- | -------- |
| US-040 | En tant que DG, je consulte un dashboard "vue 1 minute" : CA cumulé, marge, écart vs budget, alerte rouge si > 10 %       | 3 j        | P0       |
| US-041 | En tant que DAF, je consulte le tableau d'écarts par centre de profit (1 ligne / marque) avec drill-down vers les comptes | 3 j        | P0       |
| US-042 | En tant que contrôleur, je consulte la courbe Budget vs Réalisé vs Forecast par mois (12 mois)                            | 2 j        | P0       |
| US-043 | En tant que contrôleur, j'export tout dashboard en PDF / Excel                                                            | 2 j        | P1       |
| US-044 | En tant que chef VN, je consulte mon dashboard filtré sur mon centre de profit uniquement                                 | 2 j        | P0       |
| US-045 | En tant que DAF, je commente un écart > seuil (motif libre + classification : volume / prix / mix / change / autre)       | 2 j        | P1       |

**Critères d'acceptation** :

- [ ] Chaque dashboard charge en < 2 sec (95e percentile)
- [ ] Filtres période / centre de profit / marque actifs
- [ ] Export PDF fidèle à l'écran
- [ ] Responsive — utilisable sur mobile (PWA)

---

### Sprint 6 (semaines 11-12) — **Stabilisation & pilote**

**Objectif** : qualité, doc utilisateur, mise en pilote.

| ID     | User story                                                                                                          | Estimation        | Priorité |
| ------ | ------------------------------------------------------------------------------------------------------------------- | ----------------- | -------- |
| US-050 | En tant que dev, je couvre les flows critiques par tests E2E (Playwright) : login, saisie budget, import, dashboard | 4 j               | P0       |
| US-051 | En tant que dev, je déploie sur Scaleway (Kubernetes ou Docker Swarm + RDS-like)                                    | 3 j               | P0       |
| US-052 | En tant que rédacteur, je livre un guide utilisateur PDF (≤ 30 pages, illustré)                                     | 2 j               | P0       |
| US-053 | En tant que formateur, j'organise 2 sessions × 2 h pour DG/DAF/contrôleurs                                          | 1 j               | P1       |
| US-054 | En tant que support, j'active monitoring (Sentry erreurs + uptime)                                                  | 1 j               | P0       |
| US-055 | En tant qu'utilisateur pilote, je teste pendant 2 semaines avec données réelles                                     | 10 j (calendaire) | P0       |

**Critères d'acceptation Phase 1** :

- [ ] Couverture tests > 60 % (lignes), 100 % sur services critiques (BudgetService, VarianceService, ImportService)
- [ ] 0 bug bloquant en pilote
- [ ] Disponibilité ≥ 99 % sur 14 jours
- [ ] DAF signe la recette

---

## 3. Estimation totale Phase 1

| Sprint                | Charge brute          | Avec marge 20 % |
| --------------------- | --------------------- | --------------- |
| S1 — Fondations       | 10 j                  | 12 j            |
| S2 — Auth & sécurité  | 12 j                  | 14 j            |
| S3 — Budget           | 12 j                  | 14 j            |
| S4 — Réalisé & écarts | 11 j                  | 13 j            |
| S5 — Dashboards       | 14 j                  | 17 j            |
| S6 — Stabilisation    | 11 j (sur calendaire) | 13 j            |
| **Total**             | **70 j-h dev**        | **~83 j-h**     |

> ≈ 4 mois en équipe de 1 dev. ≈ 2,5 mois en équipe de 2 devs. **Hypothèse plan : 3 mois en équipe 1,5 dev (1 senior + 0,5 junior).**

---

## 4. Definition of Done (par user story)

Une US est **DONE** quand :

1. ✅ Le code passe `npm run typecheck && npm run lint && npm test`
2. ✅ Couverture tests sur le service ajouté ≥ 80 %
3. ✅ Endpoint(s) documenté(s) en OpenAPI (auto-généré par NestJS)
4. ✅ Au moins 1 test E2E couvre le happy path
5. ✅ Code review approuvée par 1 pair (humain ou Claude)
6. ✅ AuditLog couvre toutes les mutations
7. ✅ UI testée sur Chrome desktop + Chrome mobile (responsive)
8. ✅ Aucun secret en dur, aucun `console.log` oublié
9. ✅ PR mergée dans `main` avec message Conventional Commits
10. ✅ Issue / ticket fermé avec lien vers la PR

---

## 5. Backlog priorisé Phase 1 (récap par priorité)

### P0 (must-have, sans ça pas de pilote)

US-001, US-002, US-003, US-004, US-005, US-010, US-012, US-013, US-015, US-020, US-021, US-022, US-024, US-025, US-030, US-031, US-032, US-033, US-034, US-035, US-040, US-041, US-042, US-044, US-050, US-051, US-052, US-054, US-055

### P1 (nice-to-have, peut basculer Phase 2)

US-011, US-014, US-023, US-036, US-043, US-045, US-053

---

## 6. Risques de planning Phase 1

| #   | Risque                                                      | Impact               | Mitigation                                              |
| --- | ----------------------------------------------------------- | -------------------- | ------------------------------------------------------- |
| RP1 | Plan comptable SYSCOHADA réel diverge fortement du standard | +5 j US-003/004      | Réserver 1 j de calage + import customisable via CSV    |
| RP2 | Format export Sage non standard (DBF, propriétaire)         | +5 j US-030          | Demander un export Excel manuel comme contournement MVP |
| RP3 | Lenteur calcul `Variance` sur >100k lignes                  | +3 j US-035          | Pré-agrégation par période, index BTREE composé         |
| RP4 | Refus utilisateur de saisir le budget                       | Pilote raté          | Ateliers métier dès Sprint 2 ; ambassadeur DAF          |
| RP5 | Hébergement Scaleway défaillant pour utilisateurs Dakar     | Migration non prévue | Mesurer latence dès J1 ; plan B Sonatel                 |

---

## 7. Phases 2 à 7 — esquisse

### Phase 2 — SAV (4-6 sem)

**Objectifs** : OR, MO, marge atelier, marge pièces.
**User stories types** : saisie OR (réception → diagnostic → réparation → facturation), pointage MO, gestion stock pièces (entrée/sortie/inventaire), marge pièces (PV - PR), marge MO (taux horaire vendu vs coûté), dashboard atelier.
**Pré-requis** : modèle de données SAV finalisé (cf. doc 02 §4.1).

### Phase 3 — Forecast (3-4 sem)

**Objectifs** : rolling forecast 12-18 mois, scénarios paramétriques.
**User stories types** : générer forecast à partir de N premiers mois réalisés + N+1 budget, ajuster par hypothèse (prix +X %, volume -Y %), comparer 2 forecasts, alerter si forecast diverge > seuil du budget.

### Phase 4 — Intégrations (4-6 sem)

**Objectifs** : automatiser l'import comptable + ventes GESCOM.
**User stories types** : connecteur Sage 100 (FTP fichier ou ODBC), connecteur GESCOM (API ou base), planification cron quotidien, monitoring sync, gestion erreurs et reprises.

### Phase 5 — Usine d'assemblage (6-8 sem)

**Objectifs** : coût de revient industriel par véhicule assemblé.
**User stories types** : BOM par modèle, ordre de production, consommation matière, MO directe, frais généraux, écarts (volume / mix / efficience), valorisation stock en-cours.

### Phase 6 — BI avancé & ML (4-6 sem)

**Objectifs** : détection d'anomalies, recommandations, prédictif.
**User stories types** : alerte automatique si une ligne réalisée dérive > X écarts-types, suggestion top-N actions sur écarts critiques, prédiction stock atterrissage fin d'exercice, modèle simple de saisonnalité ventes.

### Phase 7 — Mobile native (3-4 sem, optionnelle)

**À évaluer après Phase 1** : si la PWA est jugée insuffisante (offline-first, notifications push critiques, perfs), construire React Native avec partage du code TypeScript. Sinon, skip.

---

## 8. Métriques de succès produit (post-pilote)

| Métrique                                      | Cible 3 mois                   | Cible 12 mois                    |
| --------------------------------------------- | ------------------------------ | -------------------------------- |
| Utilisateurs actifs hebdo                     | 5 (DG, DAF, ctrl×2, comptable) | 20 (+ chefs services, auditeurs) |
| Délai de production reporting mensuel         | -50 % vs Excel actuel          | -70 %                            |
| Nombre de réimports / mois (signe de qualité) | < 3 / mois                     | < 1 / mois                       |
| Taux d'utilisation mobile                     | 30 % des connexions            | 50 %                             |
| Score satisfaction utilisateur (NPS interne)  | > 40                           | > 60                             |

---

## 9. Validation de cette roadmap

Pour passer ce document de **v0.1** à **v1.0** :

- [ ] DAF valide la priorisation (P0 vs P1)
- [ ] DG valide les sprints S1-S6 et les jalons
- [ ] Équipe dev valide les estimations (charge réaliste ?)
- [ ] DSI valide la stack technique (cf. doc 01 §3)
- [ ] Budget infra Phase 1 (~ 500 €/mois × 3 mois ≈ 1 500 €) approuvé
