# Application de suivi budgétaire — concessionnaire multi-marques

Outil local d'analyse et de visualisation du budget annuel d'un concessionnaire automobile multi-marques (Volkswagen, Great Wall, Haval, SINOTRUK, Lovol, Chery, Sealand, etc.). Le système :

1. **Parse** le fichier Excel de budget existant (68 feuilles, ~5,5 MB) via plusieurs parsers spécialisés
2. **Normalise** les données en JSON (records typés)
3. **Génère un dashboard HTML interactif** consommé localement sans serveur — un seul fichier auto-suffisant

> Statut : MVP fonctionnel, aucune valeur financière dans le repo Git (les fichiers populés sont gitignorés).

---

## 1. Démarrage rapide (≈ 1 minute)

### Pré-requis (déjà installés)

- Python 3.12 (vrai, pas le stub Microsoft Store)
- `uv` (`uvx` permet d'exécuter sans pré-installer les libs)
- Node.js 24 LTS (utilisé pour le scaffold TS)
- Git, ripgrep

Tout est listé dans [CLAUDE.md](CLAUDE.md) §9.

### Régénérer le dashboard avec les valeurs courantes du budget

```powershell
# Depuis la racine du repo
uvx --with openpyxl python scripts/build-local-dashboard.py
```

Cette commande **chaîne 3 parsers** (VN, SAV, CPT EXPL) puis **injecte les données** dans `dashboard/index.html` pour produire `scripts/.local/dashboard.html` (gitignoré, ~1,8 MB).

### Ouvrir le dashboard

```powershell
Start-Process "scripts\.local\dashboard.html"
```

ou simplement double-cliquer le fichier dans l'Explorateur. Aucun serveur requis.

### Si le budget Excel change

Relance la commande précédente. Le pipeline complet prend **~5-10 secondes**.

---

## 2. Que fait le dashboard ?

Le dashboard contient **3 sections principales** correspondant aux 3 modules métier :

### A. Vente Véhicules Neufs (VN)

- 4 KPI cards : CA Budget, Volume, Marge, Taux de marge
- Graphique CA mensuel par marque (stacked bar 12 mois)
- Donut Mix marques
- Top 15 modèles par CA
- Tableau de performance par marque (avec exports CSV)
- Tableau détail filtrable + paginé (5 000+ records, recherche, indicateur)

**Filtres globaux** : marque, période (mensuel / S1 / S2 / Total), unité d'affichage (FCFA / k / M).

### B. Compte d'Exploitation (CPT EXPL)

- 5 KPI cards : Ventes, Achats, Personnel, Frais généraux, Résultat
- **Variance Budget S1 vs Réalisé S1** (tableau avec écart, % et statut favorable/défavorable)
- Graphique mensuel empilé par section
- Tableau des 30 plus gros postes avec filtre par section

### C. SAV (Service après-vente)

- Toggle SAV VP / SAV VL
- 3 KPI cards : CA, Coûts directs, Marge brute estimée
- Graphique mensuel CA vs Coûts
- Top 20 postes par CA Budget total

---

## 3. Architecture du repo

```
.
├── README.md                      # ← ce fichier
├── CLAUDE.md                      # mémoire projet pour Claude Code
├── package.json                   # scaffold Node + TS (utilitaires)
├── tsconfig*.json
├── eslint.config.js, .prettierrc.json
│
├── docs/                          # Cadrage et livrables
│   ├── 01-cadrage.md              # 21 hypothèses, périmètre, glossaire, risques
│   ├── 02-modele-donnees.md       # Schéma ER + choix techniques
│   ├── 03-roadmap-mvp.md          # Sprints, user stories, DoD
│   ├── 04-budget-existant-decouvertes.md  # Analyse de l'Excel réel
│   ├── cadrage-pitch.pptx         # Présentation 15 slides
│   └── mockups/                   # 5 maquettes UX/UI HTML statiques
│
├── dashboard/                     # Templates dashboard (sans données)
│   └── index.html                 # Template injecté par le build script
│
├── scripts/                       # Parsers + build pipeline (Python)
│   ├── parse-budget-vn.py         # Parser feuilles marques (VW, GW, CHERY...)
│   ├── parse-sav.py               # Parser SAV VP + SAV VL
│   ├── parse-cpt-expl.py          # Parser Compte d'Exploitation
│   ├── build-local-dashboard.py   # Pipeline : 3 parsers + injection
│   ├── audit-parser-output.py     # QA : monthly vs S1+S2 sums
│   ├── diagnose-period-detection.py  # Debug : collisions de période
│   ├── inspect-*.py               # Outils d'inspection ad-hoc
│   ├── build-pitch.cjs            # Générateur PPTX (Node)
│   └── .local/                    # ❌ Gitignoré — sorties avec valeurs réelles
│       ├── dashboard.html         # ← le dashboard à ouvrir
│       ├── parsed-budget.json     # 4 700+ records VN
│       ├── parsed-sav.json        # 650+ records SAV
│       └── parsed-cpt-expl.json   # 1 380+ records P&L
│
└── src/, tests/                   # Scaffold TS (placeholder pour backend futur)
```

---

## 4. Sécurité des données

**Aucune valeur financière n'est commitée dans Git.** Le périmètre des fichiers gitignorés (cf. `.gitignore`) :

```
scripts/.local/             # Tous les outputs avec valeurs réelles
scripts/budget-*.txt        # Rapports d'inspection bruts
.claude/settings.local.json # Permissions Claude Code locales
```

Les fichiers commitables :

- Templates HTML/PPTX (avec placeholders `__DATA__`)
- Scripts Python/Node (logique sans valeurs)
- Documentation Markdown (avec exemples publics : noms de marques, modèles)

---

## 5. Pipeline de parsing

### `scripts/parse-budget-vn.py`

Parse les 7 feuilles marques (VW, GW, CHERY, LOVOL, SINOTRUK, SEALAND, MOTOS).

**Layout source** : pour chaque marque, blocs de 4 lignes par modèle (UNITES, CA, REVIENT, MARGES) × 12 mois + S1 budget + S1 réalisé + S2 budget + Total annuel.

**Fonctionnalités** :

- Détection automatique de la colonne indicateur (B ou C selon les feuilles)
- Détection des périodes via dates Excel + regex word-boundaries
- Filtrage des lignes "TOTAL", "SOMME", "RECAP" (pseudo-modèles)
- Désambiguïsation des doublons réels (`H6 TOP` apparaissant 2× → renommé `H6 TOP (#2)`)
- Détection de collisions (deux colonnes → même période → ignore la 2ème)

**Output** : `parsed-budget.json` avec records `{brand, model, period_code, indicator, scenario, value, source_sheet, source_cell}`.

### `scripts/parse-sav.py`

Parse SAV VP (114 lignes) et SAV VL (68 lignes).

**Layout source** : 1 ligne par poste budgétaire × colonnes mensuelles + historique 2024/2025.

**Fonctionnalités** :

- Layout hardcodé (positions de colonnes stables)
- Classification heuristique des sections via emoji + mots-clés (REVENUE / COST / MARGIN / SUBTOTAL / OTHER)
- Détection des entêtes vs données

**Output** : `parsed-sav.json` avec records `{activity, poste, section, period_code, scenario, value}`.

### `scripts/parse-cpt-expl.py`

Parse CPT EXPL (Compte d'Exploitation, 238 lignes).

**Layout source** : structure identique aux feuilles marques (1 ligne par poste × 12 mois + S1 + S2 + Total + Réal S1).

**Fonctionnalités** :

- Layout hardcodé pour cohérence
- Classification heuristique (VENTES, ACHATS, PERSONNEL, FRAIS_GENERAUX, IMPOTS, MARGES, RESULTAT, OTHER)

**Output** : `parsed-cpt-expl.json` avec records `{section, poste_code, poste_label, period_code, scenario, value}`.

### `scripts/build-local-dashboard.py`

Orchestrateur : appelle les 3 parsers en sub-process puis injecte les 3 JSON dans le template `dashboard/index.html` via remplacement de placeholders `__DATA__`, `__SAV_DATA__`, `__CPT_DATA__`, `__META__`.

---

## 6. Auditer la cohérence des extractions

```powershell
python scripts\audit-parser-output.py
```

Vérifie que pour chaque marque :

```
sum(monthly Jan-Dec) == sum(S1-budget + S2-budget) == 2026-total
```

Tout ratio ≠ 1.000 indique un problème de parsing à investiguer.

Une sortie en bonne santé ressemble à :

```
Brand              Monthly           S1+S2            Diff    Ratio
----------------------------------------------------------------------
CHERY        1,095,669,748   1,095,669,748               0    1.000
GW           2,051,804,505   2,051,804,505              -0    1.000
...
TOTAL       15,470,008,244  15,470,008,244              -0    1.000
```

---

## 7. Limites connues

- **MOTOS** : volume 0 sur le mensuel — la feuille MOTOS n'a pas de ventilation par mois dans l'Excel source (seulement total annuel).
- **ATL & MAG** (atelier + magasin) : non parsé. Layout multi-année interleaved (Réal 2023 / Prév 2024 / Réal 2024 / Prév 2026 par mois) trop complexe pour un parser simple — à traiter dans une phase ultérieure.
- **ACHAT VP / VL** : non parsé. Suit l'orientation "suivi de commandes" plutôt que budgétaire — différent.
- **Variance par marque** : limité car peu de données réalisées dans `2026-S1-actual`. Le compte d'exploitation (CPT EXPL) a plus de données réalisées et est mieux servi.
- **Section MOTOS** dans le dashboard VN affichera 0 partout sauf pour S1-actual.

---

## 8. Dépannage

### Le dashboard affiche `—` partout

Ouvre la console du navigateur (F12). Si tu vois une erreur sur `JSON.parse`, c'est que le build script n'a pas tourné — relance la commande de §1.

### Erreur d'encodage en PowerShell

Si tu vois `'charmap' codec can't encode...`, ajoute en premier :

```powershell
$env:PYTHONIOENCODING = "utf-8"
```

### Le script Python ne trouve pas openpyxl

Tu utilises probablement `python` au lieu de `uvx --with openpyxl python`. Le `uvx` installe la dépendance à la volée dans un environnement isolé.

### Le faux Python du Microsoft Store intercepte

Désactive : Paramètres Windows → Applications → Paramètres avancés → Alias d'exécution d'application → décocher `python.exe` et `python3.exe`.

### nvm-windows ne fonctionne pas (`nvm use`)

Bug connu sur les chemins avec espaces. Workaround : Node 24 a été ajouté directement au PATH utilisateur (et au `~/.bashrc`). Voir [CLAUDE.md](CLAUDE.md) §9 pour le détail.

---

## 9. Résultats actuels

**Dernière exécution** : extraction de 6 816 records depuis 5,5 MB d'Excel en ~5 secondes.

| Module                | Records   | Lignes parsées        |
| --------------------- | --------- | --------------------- |
| Vente VN (7 marques)  | 4 783     | 83 modèles uniques    |
| SAV (VP + VL)         | 649       | 144 postes            |
| Compte d'Exploitation | 1 384     | 100 postes            |
| **Total**             | **6 816** | **327 lignes métier** |

**Total CA Budget VN 2026** : ~15,47 Md FCFA (cohérent monthly = S1+S2 = 2026-total).

---

## 10. Évolutions prévues (non incluses dans le MVP local)

- **Backend NestJS + PostgreSQL** : transformer ce système local en application web multi-utilisateurs (cf. [docs/03-roadmap-mvp.md](docs/03-roadmap-mvp.md))
- **Auth + RBAC** : 4 rôles (DG, DAF, Contrôleur, Consultation)
- **Audit log immuable** des modifications budgétaires
- **Forecasting** + simulation de scénarios
- **Intégrations natives** Sage / GESCOM (au lieu de l'import Excel manuel)
- **Mobile PWA** pour consultation DG en mobilité
- **Parser ATL & MAG + ACHAT VP/VL** pour couvrir tout le périmètre

Voir [docs/01-cadrage.md](docs/01-cadrage.md) pour le détail des phases.

---

## 11. Contribution

Le projet utilise un workflow git standard avec [Conventional Commits](https://www.conventionalcommits.org/) :

```bash
# Avant chaque commit
npm run typecheck && npm run lint && npm run format && npm test

# Format de message
chore: ...
feat(dashboard): ...
fix(parser): ...
docs: ...
```

Toute modification du parser doit passer le test d'audit (§6).

---

## Auteur

Cheikh Mbacké Dieng — bootstrapped en pair-programming avec Claude Code (Opus 4.7).

Toutes les décisions techniques structurantes sont documentées dans [docs/](docs/) avec horodatage et raisonnement.
