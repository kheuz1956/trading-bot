# 02 — Modèle de données

> **Statut** : v0.1 — schéma ER initial pour MVP (Vente VN). Extensions Phases 2-5 indiquées en commentaires.
> **Choix techniques** : PostgreSQL 16 + Prisma ORM. Toutes les tables en `snake_case`. Identifiants UUID v7 (triables temporellement, évite collisions multi-instances).

---

## 1. Choix techniques transverses

| Sujet                      | Choix                                                                                                                     | Rationale                                                                |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| **Identifiants**           | UUID v7 (Prisma `String @id @default(uuid(7))`)                                                                           | Triable temporellement, sans collision, exposable sans révéler le volume |
| **Montants monétaires**    | `Decimal(18,2)` en BD (PostgreSQL `NUMERIC(18,2)`)                                                                        | Précision exacte requise en finance ; **jamais de FLOAT**                |
| **Devises**                | Code ISO 4217 (`XOF`, `EUR`, `USD`, `CNY`) sur 3 caractères                                                               | Standard international                                                   |
| **Stockage multi-devise**  | Pour chaque montant : `amount_native` + `currency` + `amount_xof` (converti) + `exchange_rate_id`                         | Conserve la valeur d'origine + permet conso en XOF instantanée           |
| **Périodes**               | `period_id` référençant table `Period` (mois fiscal)                                                                      | Évite calculs de dates, supporte exercices décalés                       |
| **Soft delete**            | Colonne `deleted_at` sur entités métier mutables                                                                          | Audit, récupération                                                      |
| **Audit trail**            | Table `AuditLog` séparée (table append-only) + colonnes `created_by` / `updated_by` / `created_at` / `updated_at` partout | Conformité, debug, forensic                                              |
| **Timezone**               | UTC en base, conversion Africa/Dakar côté UI                                                                              | Évite ambiguïtés DST (XOF sans DST, mais pratique générale)              |
| **Versioning des budgets** | Snapshots immutables via `BudgetVersion`                                                                                  | Permet de comparer versions sans risque                                  |
| **Migrations**             | Prisma Migrate (`schema.prisma` → SQL généré)                                                                             | Type-safe, rollback supporté                                             |

---

## 2. Diagramme conceptuel haut niveau

```
                       ┌──────────────────┐
                       │   FiscalYear     │
                       │ (exercice 12 mois)│
                       └────┬─────────────┘
                            │ 1..N
                       ┌────▼──────────────┐
                       │     Period        │
                       │  (mois fiscal)    │
                       └────┬──────────────┘
                            │ 1..N
                            │ ┌─────────────────────────┐
                            │ │                         │
        ┌───────────────┐   │ │   ┌────────────────┐    │
        │  CostCenter   │◄──┴─┴───┤   BudgetLine   │────┴──► Account (SYSCOHADA)
        │ (centre profit│         │ (ligne budget) │
        │  ou de coûts) │         │ + montant      │
        └───┬───────────┘         │ + scénario     │
            │                     │ + version      │
            │                     └────┬───────────┘
            │                          │ N
            │                          ▼
            │                     ┌─────────────────┐
            │                     │ BudgetVersion   │
            │                     │ (snapshot)      │
            │                     └─────────────────┘
            │
            │
        ┌───▼───────────┐         ┌────────────────────┐
        │   Department  │         │ JournalEntry       │
        │ (ex: Vente VN)│         │ (écriture compta)  │
        └───────────────┘         │ + ligne(s)         │
                                  └────┬───────────────┘
                                       │ N
                                       ▼
                                  ┌─────────────────┐
                                  │ JournalLine     │
                                  │ (compte+débit/  │
                                  │  crédit)        │
                                  └─────────────────┘

      ┌─────────────────────── Métier VN ───────────────────────┐
      │                                                           │
   ┌──┴──────┐  N  ┌─────────────┐  N  ┌──────────┐  1  ┌────────┴─┐
   │  Brand  │────►│ VehicleModel│────►│ Vehicle  │────►│   Sale   │
   │ (VW, VW │     │ (Tiguan,    │     │ (VIN,    │     │ (date,   │
   │  HV...) │     │  Haval H6...)│    │  couleur)│     │  client) │
   └─────────┘     └─────────────┘     └──────────┘     └──────────┘
                                                              │
                                                              │ N..1
                                                              ▼
                                                        ┌──────────┐
                                                        │ Customer │
                                                        └──────────┘

      ┌────────────────── Sécurité & Audit ────────────────────┐

   ┌──────┐ N..N ┌──────┐ N..N ┌────────────┐
   │ User │─────►│ Role │─────►│ Permission │
   └──┬───┘      └──────┘      └────────────┘
      │ 1..N
      ▼
   ┌──────────┐
   │ AuditLog │ (append-only)
   └──────────┘
```

---

## 3. Entités principales — MVP (Phase 1)

### 3.1 Référentiels comptables

#### `Account` — Plan comptable SYSCOHADA

| Colonne         | Type           | Notes                                                |
| --------------- | -------------- | ---------------------------------------------------- |
| `id`            | UUID v7        | PK                                                   |
| `code`          | `VARCHAR(10)`  | Code SYSCOHADA (ex: `701100`, `607000`) — **unique** |
| `name`          | `VARCHAR(255)` | Libellé (ex: "Ventes de marchandises VN")            |
| `class`         | `SMALLINT`     | 1-9 (classe SYSCOHADA)                               |
| `nature`        | enum           | `CHARGE`, `PRODUIT`, `ACTIF`, `PASSIF`, `RESULTAT`   |
| `is_analytical` | boolean        | Si true, doit avoir une analytique associée          |
| `parent_id`     | UUID           | FK self → comptes hiérarchiques                      |
| `is_active`     | boolean        | Désactivation logique                                |

#### `FiscalYear` — Exercice comptable

| Colonne      | Type          | Notes                       |
| ------------ | ------------- | --------------------------- |
| `id`         | UUID v7       | PK                          |
| `code`       | `VARCHAR(10)` | Ex: `FY2026`                |
| `start_date` | date          | Ex: 2026-01-01              |
| `end_date`   | date          | Ex: 2026-12-31              |
| `status`     | enum          | `OPEN`, `CLOSING`, `CLOSED` |

#### `Period` — Mois fiscal

| Colonne          | Type          | Notes                 |
| ---------------- | ------------- | --------------------- |
| `id`             | UUID v7       | PK                    |
| `fiscal_year_id` | UUID          | FK                    |
| `code`           | `VARCHAR(10)` | Ex: `2026-M01`        |
| `start_date`     | date          |                       |
| `end_date`       | date          |                       |
| `is_closed`      | boolean       | Empêche modifications |

### 3.2 Référentiels analytiques

#### `Department` — Département / direction

| Colonne        | Type           | Notes                           |
| -------------- | -------------- | ------------------------------- |
| `id`           | UUID v7        | PK                              |
| `code`         | `VARCHAR(20)`  | Ex: `VN`, `SAV`, `USINE`, `FIN` |
| `name`         | `VARCHAR(100)` |                                 |
| `parent_id`    | UUID           | FK self → hiérarchie            |
| `head_user_id` | UUID           | FK User → responsable           |

#### `CostCenter` — Centre de profit/coûts

| Colonne         | Type           | Notes                                           |
| --------------- | -------------- | ----------------------------------------------- |
| `id`            | UUID v7        | PK                                              |
| `code`          | `VARCHAR(20)`  | Ex: `VN-VW`, `VN-HAVAL`, `SAV-MO`, `SAV-PIECES` |
| `name`          | `VARCHAR(100)` |                                                 |
| `type`          | enum           | `PROFIT_CENTER`, `COST_CENTER`                  |
| `department_id` | UUID           | FK                                              |
| `is_active`     | boolean        |                                                 |

### 3.3 Budgétaire

#### `BudgetVersion` — Version d'un budget

| Colonne             | Type           | Notes                                                  |
| ------------------- | -------------- | ------------------------------------------------------ |
| `id`                | UUID v7        | PK                                                     |
| `fiscal_year_id`    | UUID           | FK                                                     |
| `name`              | `VARCHAR(100)` | Ex: "Budget initial 2026", "Révisé S1 2026"            |
| `scenario`          | enum           | `BASE`, `OPTIMIST`, `PESSIMIST`, `FORECAST`            |
| `version_type`      | enum           | `INITIAL`, `REVISED`, `FORECAST`                       |
| `status`            | enum           | `DRAFT`, `SUBMITTED`, `APPROVED`, `LOCKED`, `ARCHIVED` |
| `parent_version_id` | UUID           | FK self → version précédente                           |
| `approved_by`       | UUID           | FK User                                                |
| `approved_at`       | timestamp      |                                                        |
| `locked_at`         | timestamp      | Plus de modifs après                                   |

#### `BudgetLine` — Ligne budgétaire

| Colonne             | Type            | Notes                    |
| ------------------- | --------------- | ------------------------ |
| `id`                | UUID v7         | PK                       |
| `budget_version_id` | UUID            | FK                       |
| `period_id`         | UUID            | FK                       |
| `account_id`        | UUID            | FK                       |
| `cost_center_id`    | UUID            | FK                       |
| `amount_xof`        | `NUMERIC(18,2)` | Montant en FCFA          |
| `amount_native`     | `NUMERIC(18,2)` | Montant devise d'origine |
| `currency`          | `CHAR(3)`       | ISO 4217                 |
| `exchange_rate`     | `NUMERIC(12,6)` | Taux appliqué            |
| `description`       | text            | Hypothèses, commentaire  |
| `created_by`        | UUID            |                          |
| `updated_by`        | UUID            |                          |

**Index** : `(budget_version_id, period_id, account_id, cost_center_id)` UNIQUE.

### 3.4 Réalisé comptable

#### `JournalEntry` — En-tête écriture

| Colonne           | Type          | Notes                                                |
| ----------------- | ------------- | ---------------------------------------------------- |
| `id`              | UUID v7       | PK                                                   |
| `period_id`       | UUID          | FK                                                   |
| `entry_date`      | date          | Date pièce                                           |
| `journal_code`    | `VARCHAR(10)` | Ex: `VTE`, `ACH`, `BNQ`, `OD`                        |
| `reference`       | `VARCHAR(50)` | N° pièce                                             |
| `description`     | text          |                                                      |
| `source`          | enum          | `MANUAL`, `IMPORT_SAGE`, `IMPORT_GESCOM`, `INTERNAL` |
| `import_batch_id` | UUID          | FK → ImportBatch (groupe d'import)                   |

#### `JournalLine` — Ligne d'écriture

| Colonne            | Type            | Notes                       |
| ------------------ | --------------- | --------------------------- |
| `id`               | UUID v7         | PK                          |
| `journal_entry_id` | UUID            | FK                          |
| `account_id`       | UUID            | FK                          |
| `cost_center_id`   | UUID?           | FK (optionnel — analytique) |
| `debit`            | `NUMERIC(18,2)` | ≥ 0                         |
| `credit`           | `NUMERIC(18,2)` | ≥ 0                         |
| `currency`         | `CHAR(3)`       |                             |
| `amount_xof`       | `NUMERIC(18,2)` | Calculé                     |
| `description`      | text            |                             |

**Contrainte BD** : pour chaque `journal_entry`, `SUM(debit) = SUM(credit)` (équilibre comptable). À vérifier en transaction au commit.

#### `ImportBatch` — Lot d'import

| Colonne       | Type           | Notes                                            |
| ------------- | -------------- | ------------------------------------------------ |
| `id`          | UUID v7        | PK                                               |
| `period_id`   | UUID           | FK                                               |
| `source`      | enum           | (cf. JournalEntry)                               |
| `file_name`   | `VARCHAR(255)` |                                                  |
| `file_hash`   | `CHAR(64)`     | SHA-256, évite re-import                         |
| `imported_by` | UUID           |                                                  |
| `imported_at` | timestamp      |                                                  |
| `status`      | enum           | `PENDING`, `VALIDATED`, `APPLIED`, `ROLLED_BACK` |
| `errors`      | jsonb          | Détail des erreurs                               |

### 3.5 Métier — Vente VN (MVP)

#### `Brand` — Marque

| Colonne          | Type           | Notes                                                                |
| ---------------- | -------------- | -------------------------------------------------------------------- |
| `id`             | UUID v7        | PK                                                                   |
| `code`           | `VARCHAR(20)`  | `VW`, `HAVAL`, `GREATWALL`, `CHERY`, `SINOTRUK`, `LOVOL`, `SEALANDS` |
| `name`           | `VARCHAR(100)` |                                                                      |
| `country_origin` | `CHAR(2)`      | ISO 3166 — `DE`, `CN`                                                |
| `is_active`      | boolean        |                                                                      |

#### `VehicleModel` — Modèle

| Colonne                | Type           | Notes                                                      |
| ---------------------- | -------------- | ---------------------------------------------------------- |
| `id`                   | UUID v7        | PK                                                         |
| `brand_id`             | UUID           | FK                                                         |
| `code`                 | `VARCHAR(50)`  |                                                            |
| `name`                 | `VARCHAR(100)` | Ex: "Tiguan 2.0 TDI"                                       |
| `category`             | enum           | `BERLINE`, `SUV`, `PICKUP`, `CAMION`, `BUS`, `AGRI`, `BTP` |
| `is_assembled_locally` | boolean        | True si CKD/SKD usine                                      |

#### `Vehicle` — Véhicule physique

| Colonne             | Type            | Notes                                                                     |
| ------------------- | --------------- | ------------------------------------------------------------------------- |
| `id`                | UUID v7         | PK                                                                        |
| `vin`               | `VARCHAR(17)`   | **UNIQUE** — n° de châssis                                                |
| `vehicle_model_id`  | UUID            | FK                                                                        |
| `color`             | `VARCHAR(50)`   |                                                                           |
| `year`              | smallint        | Année modèle                                                              |
| `purchase_cost_xof` | `NUMERIC(18,2)` | Prix de revient (achat + douane + transport)                              |
| `status`            | enum            | `IN_TRANSIT`, `IN_STOCK`, `DEMO`, `RESERVED`, `SOLD`, `WARRANTY_RETURNED` |
| `arrival_date`      | date            | Date entrée stock                                                         |

#### `Customer` — Client

| Colonne  | Type           | Notes                                   |
| -------- | -------------- | --------------------------------------- |
| `id`     | UUID v7        | PK                                      |
| `type`   | enum           | `INDIVIDUAL`, `COMPANY`, `STATE`, `ONG` |
| `name`   | `VARCHAR(255)` |                                         |
| `tax_id` | `VARCHAR(50)`  | NINEA / IFU                             |
| `phone`  | `VARCHAR(50)`  |                                         |
| `email`  | `VARCHAR(255)` |                                         |

#### `Sale` — Vente VN

| Colonne           | Type            | Notes                                 |
| ----------------- | --------------- | ------------------------------------- |
| `id`              | UUID v7         | PK                                    |
| `vehicle_id`      | UUID            | FK — UNIQUE (un véhicule = une vente) |
| `customer_id`     | UUID            | FK                                    |
| `sale_date`       | date            |                                       |
| `period_id`       | UUID            | FK                                    |
| `gross_price_xof` | `NUMERIC(18,2)` | Prix HT                               |
| `tax_xof`         | `NUMERIC(18,2)` | TVA + autres                          |
| `discount_xof`    | `NUMERIC(18,2)` | Remise commerciale                    |
| `net_price_xof`   | `NUMERIC(18,2)` | Net facturé                           |
| `salesperson_id`  | UUID            | FK User                               |
| `cost_center_id`  | UUID            | FK (= centre profit marque)           |

### 3.6 Calculs / vues matérialisées

#### `Variance` — Écart Budget vs Réalisé (vue matérialisée rafraîchie)

| Colonne             | Type            | Notes                                 |
| ------------------- | --------------- | ------------------------------------- |
| `period_id`         | UUID            |                                       |
| `cost_center_id`    | UUID            |                                       |
| `account_id`        | UUID            |                                       |
| `budget_amount_xof` | `NUMERIC(18,2)` |                                       |
| `actual_amount_xof` | `NUMERIC(18,2)` |                                       |
| `variance_xof`      | `NUMERIC(18,2)` | actual - budget                       |
| `variance_pct`      | `NUMERIC(8,4)`  |                                       |
| `variance_type`     | enum            | `FAVORABLE`, `UNFAVORABLE`, `NEUTRAL` |
| `last_refreshed_at` | timestamp       |                                       |

> Implémentée en PostgreSQL via `MATERIALIZED VIEW` ou table de calcul rafraîchie par job BullMQ après chaque import.

### 3.7 Sécurité & audit

#### `User`

| Colonne         | Type           | Notes           |
| --------------- | -------------- | --------------- |
| `id`            | UUID v7        | PK              |
| `email`         | `VARCHAR(255)` | UNIQUE          |
| `password_hash` | `VARCHAR(255)` | bcrypt / argon2 |
| `full_name`     | `VARCHAR(255)` |                 |
| `is_active`     | boolean        |                 |
| `last_login_at` | timestamp      |                 |
| `mfa_secret`    | `VARCHAR(255)` | TOTP            |

#### `Role`

| Colonne | Type           | Notes                                                                       |
| ------- | -------------- | --------------------------------------------------------------------------- |
| `id`    | UUID v7        | PK                                                                          |
| `code`  | `VARCHAR(50)`  | `DG`, `DAF`, `CTRL`, `CHEF_VN`, `CHEF_SAV`, `COMPTABLE`, `CONSULT`, `AUDIT` |
| `name`  | `VARCHAR(100)` |                                                                             |

#### `Permission`

| Colonne       | Type           | Notes                                                                      |
| ------------- | -------------- | -------------------------------------------------------------------------- |
| `id`          | UUID v7        | PK                                                                         |
| `code`        | `VARCHAR(100)` | Ex: `BUDGET:CREATE`, `BUDGET:APPROVE`, `JOURNAL:IMPORT`, `REPORT:VIEW_ALL` |
| `description` | text           |                                                                            |

Relations : `UserRole` (N..N) et `RolePermission` (N..N).

#### `AuditLog` — Journal d'audit (append-only)

| Colonne       | Type          | Notes                                                     |
| ------------- | ------------- | --------------------------------------------------------- |
| `id`          | UUID v7       | PK                                                        |
| `user_id`     | UUID          | Acteur                                                    |
| `entity_type` | `VARCHAR(50)` | `BudgetLine`, `JournalEntry`, etc.                        |
| `entity_id`   | UUID          | ID de l'entité touchée                                    |
| `action`      | enum          | `CREATE`, `UPDATE`, `DELETE`, `APPROVE`, `LOCK`, `IMPORT` |
| `before`      | jsonb         | État avant                                                |
| `after`       | jsonb         | État après                                                |
| `ip_address`  | inet          |                                                           |
| `user_agent`  | text          |                                                           |
| `at`          | timestamp     |                                                           |

> Cette table est en **insert-only** (révoquer DELETE/UPDATE au niveau Postgres).

### 3.8 Devises

#### `Currency`

| Colonne    | Type          | Notes                           |
| ---------- | ------------- | ------------------------------- |
| `code`     | `CHAR(3)`     | PK — `XOF`, `EUR`, `USD`, `CNY` |
| `name`     | `VARCHAR(50)` |                                 |
| `decimals` | smallint      | XOF=0, EUR/USD/CNY=2            |

#### `ExchangeRate`

| Colonne         | Type            | Notes                      |
| --------------- | --------------- | -------------------------- |
| `id`            | UUID v7         | PK                         |
| `from_currency` | `CHAR(3)`       |                            |
| `to_currency`   | `CHAR(3)`       |                            |
| `rate`          | `NUMERIC(18,8)` |                            |
| `valid_from`    | date            |                            |
| `valid_to`      | date?           | NULL = en cours            |
| `source`        | enum            | `BCEAO`, `MANUAL`, `FIXED` |

> XOF↔EUR fixé à `655.957` ; USD/CNY chargés quotidiennement via job ETL (BCEAO ou ECB).

---

## 4. Entités prévues mais hors-MVP (cadrage Phases 2-5)

### Phase 2 — SAV

- `RepairOrder` (en-tête OR)
- `RepairOrderLine` (lignes : MO, pièces, sous-traitance)
- `LaborTimeEntry` (pointage atelier)
- `Part` (pièce de rechange — référentiel)
- `PartStock` (stock pièces par emplacement)
- `Mechanic` (lié à User)

### Phase 3 — Forecast

- `ForecastVersion` (extension de `BudgetVersion` avec type `FORECAST`)
- `ScenarioParameter` (paramètres de simulation : prix VW +5 %, vol Haval -10 %…)

### Phase 4 — Intégrations

- `IntegrationConnector` (Sage, GESCOM, etc.)
- `MappingRule` (compte source → compte SYSCOHADA cible)
- `SyncRun` (historique synchronisations)

### Phase 5 — Usine

- `BillOfMaterials` (BOM par modèle CKD)
- `ProductionOrder` (ordre d'assemblage)
- `ComponentPart` (composant + coût)
- `ProductionVarianceCause` (cause d'écart : volume, mix, efficience MO, prix matière)

---

## 5. Index et performance

Index critiques à prévoir dès la première migration :

```sql
-- Recherches budget par version + période + analytique
CREATE INDEX idx_budget_line_lookup
  ON budget_line (budget_version_id, period_id, account_id, cost_center_id);

-- Recherches comptables par période
CREATE INDEX idx_journal_line_period
  ON journal_line (journal_entry_id);
CREATE INDEX idx_journal_entry_period
  ON journal_entry (period_id);

-- Recherche audit par entité
CREATE INDEX idx_audit_entity
  ON audit_log (entity_type, entity_id, at DESC);

-- Plein texte clients
CREATE INDEX idx_customer_name_trgm
  ON customer USING gin (name gin_trgm_ops);
```

> À monitorer : si volume `journal_line` dépasse ~10 M lignes, partitionner par `period_id` (PostgreSQL native partitioning).

---

## 6. Contraintes d'intégrité métier (à coder côté app + BD)

1. **Équilibre comptable** : pour chaque `JournalEntry`, somme des débits = somme des crédits, par devise.
2. **Période ouverte** : impossible d'insérer un `JournalEntry` ou `BudgetLine` sur une `Period` avec `is_closed = true`.
3. **Budget verrouillé** : impossible de modifier `BudgetLine` si la `BudgetVersion` est en statut `LOCKED` ou `ARCHIVED`.
4. **Vente unique** : un `Vehicle` ne peut avoir qu'une seule `Sale` (sauf retours/rétrocessions, gérées comme `Sale` négative).
5. **Cohérence devise** : si `currency != XOF`, alors `exchange_rate` doit pointer vers une `ExchangeRate` valide à la date de la pièce.
6. **Audit immuable** : aucun UPDATE/DELETE permis sur `audit_log` (Postgres role privileges).
7. **Soft delete** : les lignes avec `deleted_at IS NOT NULL` sont exclues des calculs d'écarts par défaut.

---

## 7. Stratégie de migration / seed

1. **Seed minimal** : utilisateur DG + DAF, 1 fiscal year (FY2026), 12 périodes, plan comptable SYSCOHADA importé, marques + modèles.
2. **Source du plan comptable** : SYSCOHADA OHADA révisé 2018, comptes classes 1-9, ~600 entrées. À fournir en CSV.
3. **Devises** : 4 codes ISO + 1 taux XOF→EUR fixé.
4. **Test data** : 50 véhicules, 30 ventes, 1 budget initial complet pour FY2026 — généré par script de seed (Faker.js + valeurs cohérentes).

---

## 8. Décisions à confirmer

| #   | Décision                               | Proposition                                                                                               |
| --- | -------------------------------------- | --------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| D1  | Précision décimale                     | `NUMERIC(18,2)` — XOF a 0 décimale mais on garde 2 pour les devises secondaires                           |
| D2  | Stratégie audit log                    | Triggers Postgres OU instrumentation app NestJS                                                           | **Préférence app** (plus testable) |
| D3  | Soft delete partout ?                  | Uniquement entités mutables/sensibles (Budget, Sale, Journal). Référentiels (Brand, Model) → `is_active`. |
| D4  | Multi-tenant ?                         | **Non au MVP** (1 entité juridique). Architecture prête : ajout `organization_id` partout en Phase 4.     |
| D5  | Stockage des fichiers (pièces jointes) | S3-compatible (Scaleway Object Storage / MinIO). MVP = pas de PJ.                                         |
