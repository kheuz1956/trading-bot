# CLAUDE.md

> Mémoire de projet pour Claude Code. Ce fichier est lu à chaque session.
> Garde-le à jour : c'est le levier n°1 pour des réponses pertinentes.

---

## 1. Contexte du projet

- **Nom** : `code` (workspace TypeScript)
- **Objectif** : à compléter par l'utilisateur — pour le moment, il s'agit d'un workspace TS bootstrapé pour expérimenter avec Claude Code
- **Statut** : scaffold initial, aucun code métier
- **Mainteneur** : @CHEIKH-MBACKE-DIENG (à confirmer)

## 2. Stack technique

| Couche          | Technologie                                  | Version cible                                     |
| --------------- | -------------------------------------------- | ------------------------------------------------- |
| Runtime         | Node.js                                      | >= 22 (installé : 24.15.0 LTS)                    |
| Langage         | TypeScript                                   | ^6.0 (mode `strict` + `noUncheckedIndexedAccess`) |
| Modules         | ESM (`"type": "module"`)                     | natif Node                                        |
| Exécution dev   | `tsx` (TS direct, pas de build)              | ^4                                                |
| Tests           | `vitest`                                     | ^4                                                |
| Lint            | ESLint **flat config** + `typescript-eslint` | ^10 / ^8                                          |
| Format          | Prettier                                     | ^3                                                |
| Package manager | npm                                          | 11.x                                              |

## 3. Commandes courantes

| Commande                | Effet                                                      |
| ----------------------- | ---------------------------------------------------------- |
| `npm run dev`           | Lance `src/index.ts` en watch (rechargement à chaque save) |
| `npm run build`         | Compile `src/` vers `dist/` via `tsconfig.build.json`      |
| `npm start`             | Exécute le build (`dist/index.js`)                         |
| `npm test`              | Lance tous les tests une fois                              |
| `npm run test:watch`    | Tests en mode watch                                        |
| `npm run test:coverage` | Tests + rapport de couverture (HTML dans `coverage/`)      |
| `npm run typecheck`     | Vérification de types sans émettre de fichiers             |
| `npm run lint`          | ESLint sur tout le repo                                    |
| `npm run lint:fix`      | ESLint avec auto-fix                                       |
| `npm run format`        | Prettier en écriture                                       |
| `npm run format:check`  | Prettier en lecture seule (CI)                             |

## 4. Structure des dossiers

```
.
├── src/                  # Code source de production
│   └── index.ts          # Point d'entrée
├── tests/                # Tests vitest (séparés du code source)
│   └── index.test.ts
├── dist/                 # Sortie de build (gitignored)
├── coverage/             # Rapports de couverture (gitignored)
├── .claude/              # Config locale Claude Code (settings, agents, slash commands)
├── eslint.config.js      # ESLint flat config (ESLint 9+)
├── tsconfig.json         # Config TS pour éditeur + typecheck (inclut tests)
├── tsconfig.build.json   # Config TS pour build (src uniquement, émet du JS)
├── vitest.config.ts      # Config Vitest
├── .prettierrc.json
├── .editorconfig
├── package.json
└── CLAUDE.md             # Ce fichier
```

## 5. Conventions de code

- **Indentation** : 2 espaces, fin de ligne LF
- **Quotes** : simples (`'…'`) en TS/JS, doubles uniquement dans JSON
- **Trailing comma** : toujours
- **Largeur ligne** : 100 colonnes
- **Imports** : utiliser `import type` quand seul le type est utilisé (règle ESLint `consistent-type-imports`)
- **Variables non utilisées** : préfixer avec `_` pour suppression du warning (`_unused`)
- **Tests** : co-localisés dans `tests/` avec extension `.test.ts`

## 6. Workflow Git

- **Branche par défaut** : `main`
- **Convention de commits** : [Conventional Commits](https://www.conventionalcommits.org/)
  - `feat:` nouvelle fonctionnalité
  - `fix:` correction de bug
  - `chore:` maintenance, dépendances, config
  - `docs:` documentation uniquement
  - `refactor:` refactor sans changement de comportement
  - `test:` ajout/modification de tests
  - `perf:` amélioration de performance
- **Line endings** : LF (forcé via `core.eol lf` + `core.autocrlf false`)
- **Avant chaque commit** : lance `npm run typecheck && npm run lint && npm test`

## 7. Tests

- Framework : **Vitest** (API style Jest, ultra-rapide via Vite)
- Localisation : `tests/**/*.test.ts`
- Couverture : v8 provider (`npm run test:coverage`)
- Cible de couverture : à définir (recommandation : 70 % branches sur le code métier)

## 8. Variables d'environnement

| Variable                  | Usage | Exemple |
| ------------------------- | ----- | ------- |
| _(aucune pour le moment)_ | —     | —       |

> Quand des secrets seront ajoutés : `.env` est gitignored. Documenter chaque variable ici **sans la valeur**.

## 9. Pièges connus / contraintes locales

- **NVM-windows ne supporte pas les espaces dans le chemin user** (le dossier utilisateur contient des espaces). Conséquence : `nvm use <version>` échoue. Workaround appliqué : Node 24.15.0 ajouté directement au PATH utilisateur (`C:\Users\CHEIKH MBACKE DIENG\AppData\Local\nvm\v24.15.0`) **et** au `~/.bashrc` pour Git Bash.
- **Faux Python du Microsoft Store** peut intercepter `python` selon l'ordre du PATH. Désactivable manuellement dans : Paramètres Windows → Applications → Paramètres avancés des applications → Alias d'exécution d'application → décocher `python.exe` et `python3.exe`.
- **PowerShell** : politique d'exécution forcée à `RemoteSigned` au scope `CurrentUser` (sinon `npm.ps1` planté).
- **Path absolu avec espaces** : toujours quoter les chemins (`"C:\Users\CHEIKH MBACKE DIENG\..."`). Bash MINGW utilise `/c/Users/CHEIKH MBACKE DIENG/...`.

## 10. Préférences de communication avec Claude

- **Langue** : français pour les échanges, anglais pour le code, commits, et identifiants
- **Ton** : direct, professionnel, structuré, sans flatterie inutile
- **Format de réponse** : tableaux quand pertinent, listes courtes, blocs de code minimaux
- **Niveau de détail** : expert, mais pédagogique sur les choix non évidents
- **Plan d'abord** : pour toute tâche en >2 étapes, présenter un plan numéroté avant d'agir
- **Confirmation requise** pour : `git push`, `rm -rf`, modifications hors du repo, installation système, opérations destructives
- **Pas besoin de confirmation pour** : lecture, lint, format, test, écriture dans le repo, commits locaux

## 11. Définition de "fini"

Pour toute modification de code, considérer la tâche terminée seulement quand :

1. ✅ Le code compile (`npm run typecheck`)
2. ✅ Le linter passe (`npm run lint`)
3. ✅ Les tests passent (`npm test`)
4. ✅ Le formatage est appliqué (`npm run format`)
5. ✅ Le diff a été relu mentalement par Claude
6. ✅ Les changements sont commités avec un message Conventional Commits clair

## 12. À éviter

- ❌ Ajouter des dépendances sans valider leur utilité (préférer du code natif si simple)
- ❌ Désactiver des règles ESLint/TS sans raison documentée en commentaire
- ❌ Commits incluant `node_modules/`, `.env`, fichiers IDE
- ❌ Force-push sur `main`
- ❌ Émojis dans le code, les commits, ou les fichiers techniques (sauf si demandé explicitement)
