/* eslint-disable */
// Generates docs/cadrage-pitch.pptx — cadrage deck for budget tracking app
// Run with: node scripts/build-pitch.cjs
// Palette : Midnight Executive (navy + ice blue + amber accent).

const pptxgen = require('pptxgenjs');
const path = require('path');

const C = {
  navy: '1E2761',
  navyDeep: '0F1535',
  ice: 'CADCFC',
  surface: 'F8FAFC',
  border: 'E2E8F0',
  ink: '1E293B',
  muted: '64748B',
  amber: 'F59E0B',
  amberSoft: 'FEF3C7',
  emerald: '10B981',
  emeraldSoft: 'D1FAE5',
  rose: 'EF4444',
  roseSoft: 'FEE2E2',
  white: 'FFFFFF',
};

const FONT_HEAD = 'Calibri';
const FONT_BODY = 'Calibri';

const pres = new pptxgen();
pres.layout = 'LAYOUT_16x9';
pres.author = 'Cheikh Mbacké Dieng';
pres.title = 'App de suivi budgétaire — Cadrage v0.1';
pres.subject = 'Pilotage financier pour concessionnaire multi-marques';

// ===== Helpers =====

function addPageHeader(slide, kicker, slideNum) {
  slide.background = { color: C.surface };
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0,
    y: 0,
    w: 10,
    h: 0.45,
    fill: { color: C.navy },
    line: { color: C.navy, width: 0 },
  });
  slide.addText(kicker.toUpperCase(), {
    x: 0.5,
    y: 0,
    w: 8,
    h: 0.45,
    fontSize: 10,
    fontFace: FONT_HEAD,
    color: C.ice,
    bold: true,
    valign: 'middle',
    margin: 0,
    charSpacing: 4,
  });
  slide.addText(`${slideNum} / 15`, {
    x: 8.7,
    y: 0,
    w: 1.1,
    h: 0.45,
    fontSize: 10,
    fontFace: FONT_HEAD,
    color: C.ice,
    align: 'right',
    valign: 'middle',
    margin: 0,
  });
}

function addPageTitle(slide, text, y = 0.7) {
  slide.addText(text, {
    x: 0.5,
    y,
    w: 9,
    h: 0.7,
    fontSize: 32,
    fontFace: FONT_HEAD,
    color: C.navy,
    bold: true,
    valign: 'middle',
    margin: 0,
  });
}

function addSubtitle(slide, text, y = 1.4) {
  slide.addText(text, {
    x: 0.5,
    y,
    w: 9,
    h: 0.4,
    fontSize: 14,
    fontFace: FONT_BODY,
    color: C.muted,
    valign: 'middle',
    margin: 0,
  });
}

function addFooter(slide) {
  slide.addText('Cadrage v0.1 — App suivi budgétaire — Cheikh Mbacké Dieng', {
    x: 0.5,
    y: 5.3,
    w: 9,
    h: 0.25,
    fontSize: 9,
    fontFace: FONT_BODY,
    color: C.muted,
    align: 'left',
    valign: 'middle',
    margin: 0,
  });
}

function card(slide, opts) {
  const { x, y, w, h, accent, title, body, bodySize = 11, titleSize = 13 } = opts;
  slide.addShape(pres.shapes.RECTANGLE, {
    x,
    y,
    w,
    h,
    fill: { color: C.white },
    line: { color: C.border, width: 0.75 },
    shadow: {
      type: 'outer',
      color: '000000',
      blur: 6,
      offset: 1,
      angle: 90,
      opacity: 0.05,
    },
  });
  if (accent) {
    slide.addShape(pres.shapes.RECTANGLE, {
      x,
      y,
      w: 0.08,
      h,
      fill: { color: accent },
      line: { color: accent, width: 0 },
    });
  }
  if (title) {
    slide.addText(title, {
      x: x + 0.2,
      y: y + 0.1,
      w: w - 0.3,
      h: 0.35,
      fontSize: titleSize,
      fontFace: FONT_HEAD,
      color: C.navy,
      bold: true,
      margin: 0,
    });
  }
  if (body) {
    slide.addText(body, {
      x: x + 0.2,
      y: y + (title ? 0.5 : 0.15),
      w: w - 0.3,
      h: h - (title ? 0.6 : 0.25),
      fontSize: bodySize,
      fontFace: FONT_BODY,
      color: C.ink,
      valign: 'top',
      margin: 0,
      paraSpaceAfter: 4,
    });
  }
}

function bulletList(items, opts) {
  return items.map((t, i) => ({
    text: t,
    options: { bullet: { code: '25A0' }, ...(i < items.length - 1 ? { breakLine: true } : {}) },
  }));
}

function plainList(items) {
  return items.map((t, i) => ({
    text: t,
    options: i < items.length - 1 ? { breakLine: true } : {},
  }));
}

// ===== Slide 1 — Title =====
{
  const s = pres.addSlide();
  s.background = { color: C.navyDeep };

  // Accent rectangle bottom
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0,
    y: 5.0,
    w: 10,
    h: 0.625,
    fill: { color: C.amber },
    line: { color: C.amber, width: 0 },
  });

  // Kicker
  s.addText('CADRAGE PROJET · v0.1', {
    x: 0.7,
    y: 0.7,
    w: 9,
    h: 0.4,
    fontSize: 12,
    fontFace: FONT_HEAD,
    color: C.amber,
    bold: true,
    margin: 0,
    charSpacing: 6,
  });

  // Title
  s.addText('App de suivi budgétaire', {
    x: 0.7,
    y: 1.4,
    w: 9,
    h: 1.1,
    fontSize: 48,
    fontFace: FONT_HEAD,
    color: C.white,
    bold: true,
    margin: 0,
  });

  // Subtitle
  s.addText('Pilotage financier pour concessionnaire multi-marques', {
    x: 0.7,
    y: 2.5,
    w: 9,
    h: 0.5,
    fontSize: 20,
    fontFace: FONT_BODY,
    color: C.ice,
    margin: 0,
  });

  // Brands divider
  s.addShape(pres.shapes.LINE, {
    x: 0.7,
    y: 3.3,
    w: 1.5,
    h: 0,
    line: { color: C.amber, width: 2 },
  });

  // Brands list
  s.addText('Volkswagen · Haval · Great Wall · Chery · SINOTRUK · Lovol · Sealands', {
    x: 0.7,
    y: 3.5,
    w: 9,
    h: 0.4,
    fontSize: 14,
    fontFace: FONT_BODY,
    color: C.white,
    italic: true,
    margin: 0,
  });

  // Footer info
  s.addText('Cheikh Mbacké Dieng · Avril 2026 · Pour validation DG / DAF / DSI', {
    x: 0.7,
    y: 5.15,
    w: 9,
    h: 0.35,
    fontSize: 11,
    fontFace: FONT_BODY,
    color: C.navyDeep,
    bold: true,
    valign: 'middle',
    margin: 0,
  });
}

// ===== Slide 2 — Pourquoi maintenant =====
{
  const s = pres.addSlide();
  addPageHeader(s, 'Contexte', 2);
  addPageTitle(s, 'Pourquoi maintenant');
  addSubtitle(s, 'Le pilotage budgétaire actuel ne tient plus le rythme de l’activité');

  // Left card — pain points
  card(s, {
    x: 0.5,
    y: 1.95,
    w: 4.4,
    h: 3.05,
    accent: C.rose,
    title: 'Aujourd’hui',
    body: bulletList([
      'Budgets dispersés dans 4-6 fichiers Excel',
      'Écarts détectés en J+15 minimum',
      'Pas de pilotage temps réel par activité',
      'Pas de scénarios alternatifs (1 vue figée)',
      'Modifications non tracées (pas d’audit)',
      'Forecast reconstruit chaque mois à la main',
    ]),
  });

  // Right card — what's missing
  card(s, {
    x: 5.1,
    y: 1.95,
    w: 4.4,
    h: 3.05,
    accent: C.emerald,
    title: 'Ce qu’il manque',
    body: bulletList([
      'Source unique partagée DG / DAF / chefs de service',
      'Détection des dérives sous 24 h',
      'Drill-down du KPI vers le compte SYSCOHADA',
      '3 scénarios (optimiste / réaliste / pessimiste)',
      'Audit log immuable + RBAC fin',
      'Rolling forecast actualisé en continu',
    ]),
  });

  addFooter(s);
}

// ===== Slide 3 — Vision produit =====
{
  const s = pres.addSlide();
  addPageHeader(s, 'Vision produit', 3);
  addPageTitle(s, 'Une seule app pour piloter Vente VN, SAV et Usine');
  addSubtitle(
    s,
    'Trois leviers : pilotage temps réel · décision multi-scénarios · confiance des données',
  );

  const yCards = 2.05;
  const hCards = 3.0;
  const cards = [
    {
      x: 0.5,
      accent: C.amber,
      title: 'Pilotage',
      body: bulletList([
        'KPIs financiers temps réel',
        'Écarts visibles sous 24 h',
        'Drill-down compte par compte',
        'Tableau de bord par rôle',
      ]),
    },
    {
      x: 3.5,
      accent: C.amber,
      title: 'Décision',
      body: bulletList([
        '3 scénarios coexistants',
        'Simulation d’impact',
        'Rolling forecast 12-18 mois',
        'Comparaison versions',
      ]),
    },
    {
      x: 6.5,
      accent: C.amber,
      title: 'Confiance',
      body: bulletList([
        'Audit log immuable',
        'RBAC + 2FA optionnel',
        'Sauvegardes 3-2-1',
        'Conformité SYSCOHADA',
      ]),
    },
  ];
  cards.forEach((c) =>
    card(s, { ...c, y: yCards, w: 3.0, h: hCards, bodySize: 12, titleSize: 16 }),
  );

  addFooter(s);
}

// ===== Slide 4 — Périmètre MVP =====
{
  const s = pres.addSlide();
  addPageHeader(s, 'Périmètre', 4);
  addPageTitle(s, 'Périmètre du MVP — Phase 1');
  addSubtitle(s, '6-8 semaines de dev · pilote utilisable à 3 mois · Vente VN uniquement');

  card(s, {
    x: 0.5,
    y: 1.95,
    w: 4.4,
    h: 3.05,
    accent: C.emerald,
    title: 'Inclus dans le MVP',
    body: bulletList([
      'Activité : Vente Véhicules Neufs',
      'Cycle : exercice annuel + révisé semestriel',
      '3 scénarios (BASE / OPTIMIST / PESSIMIST)',
      'Auth + 4 rôles (DG, DAF, Contrôleur, Consult.)',
      '5 à 7 dashboards principaux',
      'Audit trail des modifs budget + journal',
      'Imports comptables manuels (CSV / Excel)',
    ]),
  });

  card(s, {
    x: 5.1,
    y: 1.95,
    w: 4.4,
    h: 3.05,
    accent: C.muted,
    title: 'Hors MVP — phases ultérieures',
    body: bulletList([
      'SAV (Phase 2) — atelier, MO, pièces',
      'Usine d’assemblage (Phase 5) — coût de revient',
      'CRM / pipeline commercial',
      'Intégrations natives Sage / GESCOM (Phase 4)',
      'Mobile native (PWA d’abord)',
      'Détection d’anomalies, ML (Phase 6)',
      'Multi-pays / multi-entités juridiques',
    ]),
  });

  addFooter(s);
}

// ===== Slide 5 — Hypothèses à valider =====
{
  const s = pres.addSlide();
  addPageHeader(s, 'Hypothèses', 5);
  addPageTitle(s, '21 hypothèses à valider');
  addSubtitle(s, 'Chaque ligne reste en HYP jusqu’à signature DAF + DG');

  const rows = [
    [
      { text: 'Catégorie', options: { bold: true, color: C.white, fill: { color: C.navy } } },
      {
        text: 'Hypothèse principale',
        options: { bold: true, color: C.white, fill: { color: C.navy } },
      },
      { text: 'Statut', options: { bold: true, color: C.white, fill: { color: C.navy } } },
    ],
    ['Pays / fiscalité', 'Sénégal · SYSCOHADA OHADA révisé · TVA 18 %', 'HYP'],
    ['Devises', 'FCFA (XOF) tenue · EUR/USD/CNY imports · taux BCEAO', 'HYP'],
    ['Logiciels existants', 'Compta : Sage 100 (ou similaire) · GESCOM : à préciser', 'HYP'],
    ['Volumes annuels', '~1 500 véhicules vendus · ~3 000 OR/mois · ~50 k SKU', 'HYP'],
    ['Utilisateurs', '20 à 50 simultanés au pic', 'HYP'],
    ['Équipe projet', '1-3 devs + 1 référent métier (DAF / contrôleur)', 'HYP'],
    ['Hébergement', 'Scaleway Paris · latence Dakar 80-120 ms', 'HYP'],
    ['Budget infra', '< 500 €/mois sur les 6 premiers mois', 'HYP'],
    ['Échéance pilote', '3 mois pour MVP utilisable', 'HYP'],
  ];

  s.addTable(rows, {
    x: 0.5,
    y: 1.95,
    w: 9.0,
    colW: [2.4, 5.5, 1.1],
    rowH: 0.31,
    fontFace: FONT_BODY,
    fontSize: 11,
    color: C.ink,
    border: { type: 'solid', pt: 0.5, color: C.border },
    valign: 'middle',
  });

  addFooter(s);
}

// ===== Slide 6 — Stack technique =====
{
  const s = pres.addSlide();
  addPageHeader(s, 'Stack technique', 6);
  addPageTitle(s, 'Choix technologiques adaptés au contexte');
  addSubtitle(s, 'Open source · ouvert · francophone · pas de vendor lock-in');

  const layers = [
    {
      label: 'Frontend',
      tech: 'React + Vite · Tailwind · shadcn/ui · Recharts · TanStack Query',
      color: C.amber,
    },
    {
      label: 'Backend',
      tech: 'NestJS (modulaire) · TypeScript strict · OpenAPI auto · BullMQ workers',
      color: C.navy,
    },
    {
      label: 'Données',
      tech: 'PostgreSQL 16 + Prisma · Redis (cache + queue) · Object storage S3-compatible',
      color: C.navy,
    },
    {
      label: 'Infra',
      tech: 'Scaleway Paris · Docker · GitHub Actions · Sentry · Grafana / Prometheus',
      color: C.muted,
    },
  ];

  let y = 1.95;
  layers.forEach((l) => {
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.5,
      y,
      w: 9.0,
      h: 0.7,
      fill: { color: C.white },
      line: { color: C.border, width: 0.75 },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.5,
      y,
      w: 0.08,
      h: 0.7,
      fill: { color: l.color },
      line: { color: l.color, width: 0 },
    });
    s.addText(l.label.toUpperCase(), {
      x: 0.7,
      y,
      w: 1.6,
      h: 0.7,
      fontSize: 12,
      fontFace: FONT_HEAD,
      color: C.navy,
      bold: true,
      valign: 'middle',
      charSpacing: 3,
      margin: 0,
    });
    s.addText(l.tech, {
      x: 2.4,
      y,
      w: 7.0,
      h: 0.7,
      fontSize: 12,
      fontFace: FONT_BODY,
      color: C.ink,
      valign: 'middle',
      margin: 0,
    });
    y += 0.78;
  });

  addFooter(s);
}

// ===== Slide 7 — Architecture haut niveau =====
{
  const s = pres.addSlide();
  addPageHeader(s, 'Architecture', 7);
  addPageTitle(s, 'Architecture haut niveau');
  addSubtitle(s, 'API Gateway centrale · 6 modules métier · ETL pour intégrations existants');

  // Browser/Mobile
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5,
    y: 2.05,
    w: 4.0,
    h: 0.6,
    fill: { color: C.amber },
    line: { color: C.amber, width: 0 },
  });
  s.addText('Browser · Mobile PWA', {
    x: 0.5,
    y: 2.05,
    w: 4.0,
    h: 0.6,
    fontSize: 12,
    fontFace: FONT_HEAD,
    color: C.navyDeep,
    bold: true,
    align: 'center',
    valign: 'middle',
    margin: 0,
  });

  // External systems
  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.5,
    y: 2.05,
    w: 4.0,
    h: 0.6,
    fill: { color: C.muted },
    line: { color: C.muted, width: 0 },
  });
  s.addText('Sage · GESCOM · CRM (ETL)', {
    x: 5.5,
    y: 2.05,
    w: 4.0,
    h: 0.6,
    fontSize: 12,
    fontFace: FONT_HEAD,
    color: C.white,
    bold: true,
    align: 'center',
    valign: 'middle',
    margin: 0,
  });

  // Arrows
  s.addShape(pres.shapes.LINE, {
    x: 2.5,
    y: 2.7,
    w: 0,
    h: 0.3,
    line: { color: C.muted, width: 1.5 },
  });
  s.addShape(pres.shapes.LINE, {
    x: 7.5,
    y: 2.7,
    w: 0,
    h: 0.3,
    line: { color: C.muted, width: 1.5 },
  });

  // API Gateway
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5,
    y: 3.05,
    w: 9.0,
    h: 0.7,
    fill: { color: C.navy },
    line: { color: C.navy, width: 0 },
  });
  s.addText('API Gateway NestJS  ·  Auth · RBAC · Rate-limit · Audit log', {
    x: 0.5,
    y: 3.05,
    w: 9.0,
    h: 0.7,
    fontSize: 13,
    fontFace: FONT_HEAD,
    color: C.white,
    bold: true,
    align: 'center',
    valign: 'middle',
    margin: 0,
  });

  // 6 modules row
  const modules = ['Budget', 'Réalisé', 'Forecast', 'Coûts', 'Reporting', 'Sécurité'];
  const modW = 1.42;
  const modGap = 0.06;
  const totalW = modules.length * modW + (modules.length - 1) * modGap;
  const startX = (10 - totalW) / 2;
  modules.forEach((m, i) => {
    const x = startX + i * (modW + modGap);
    s.addShape(pres.shapes.RECTANGLE, {
      x,
      y: 3.85,
      w: modW,
      h: 0.55,
      fill: { color: C.white },
      line: { color: C.navy, width: 1 },
    });
    s.addText(m, {
      x,
      y: 3.85,
      w: modW,
      h: 0.55,
      fontSize: 11,
      fontFace: FONT_HEAD,
      color: C.navy,
      bold: true,
      align: 'center',
      valign: 'middle',
      margin: 0,
    });
  });

  // PostgreSQL bottom
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5,
    y: 4.65,
    w: 9.0,
    h: 0.55,
    fill: { color: C.ice },
    line: { color: C.ice, width: 0 },
  });
  s.addText('PostgreSQL 16 + TimescaleDB  ·  Redis (cache + queue)  ·  Object storage', {
    x: 0.5,
    y: 4.65,
    w: 9.0,
    h: 0.55,
    fontSize: 12,
    fontFace: FONT_HEAD,
    color: C.navy,
    bold: true,
    align: 'center',
    valign: 'middle',
    margin: 0,
  });

  addFooter(s);
}

// ===== Slide 8 — Modèle de données =====
{
  const s = pres.addSlide();
  addPageHeader(s, 'Données', 8);
  addPageTitle(s, 'Modèle de données — 25+ entités');
  addSubtitle(
    s,
    'PostgreSQL + Prisma · UUID v7 · NUMERIC(18,2) · audit log immuable · multi-devise',
  );

  const groups = [
    {
      title: 'Comptable',
      items: 'Account · FiscalYear · Period · JournalEntry · JournalLine · ImportBatch',
      accent: C.navy,
    },
    {
      title: 'Budgétaire',
      items: 'BudgetVersion · BudgetLine · CostCenter · Department · Variance',
      accent: C.amber,
    },
    {
      title: 'Métier VN',
      items: 'Brand · VehicleModel · Vehicle · Sale · Customer',
      accent: C.amber,
    },
    {
      title: 'Sécurité & audit',
      items: 'User · Role · Permission · UserRole · RolePermission · AuditLog (append-only)',
      accent: C.navy,
    },
    {
      title: 'Devises',
      items: 'Currency · ExchangeRate (BCEAO ou fixé)',
      accent: C.muted,
    },
  ];

  let y = 1.95;
  groups.forEach((g) => {
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.5,
      y,
      w: 9.0,
      h: 0.55,
      fill: { color: C.white },
      line: { color: C.border, width: 0.75 },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.5,
      y,
      w: 0.08,
      h: 0.55,
      fill: { color: g.accent },
      line: { color: g.accent, width: 0 },
    });
    s.addText(g.title, {
      x: 0.7,
      y,
      w: 2.0,
      h: 0.55,
      fontSize: 12,
      fontFace: FONT_HEAD,
      color: C.navy,
      bold: true,
      valign: 'middle',
      margin: 0,
    });
    s.addText(g.items, {
      x: 2.7,
      y,
      w: 6.7,
      h: 0.55,
      fontSize: 11,
      fontFace: FONT_BODY,
      color: C.ink,
      valign: 'middle',
      margin: 0,
    });
    y += 0.62;
  });

  addFooter(s);
}

// ===== Slide 9 — Roadmap globale =====
{
  const s = pres.addSlide();
  addPageHeader(s, 'Roadmap', 9);
  addPageTitle(s, 'Roadmap globale — 8 à 12 mois');
  addSubtitle(s, '7 phases livrables · MVP utilisable à 3 mois · Mobile native optionnelle');

  const phases = [
    { code: '0', name: 'Cadrage', dur: '2-3 sem', color: C.muted, status: 'En cours' },
    { code: '1', name: 'MVP — Vente VN', dur: '6-8 sem', color: C.amber, status: '' },
    { code: '2', name: 'SAV + pièces', dur: '4-6 sem', color: C.navy, status: '' },
    { code: '3', name: 'Forecast & scénarios', dur: '3-4 sem', color: C.navy, status: '' },
    { code: '4', name: 'Intégrations Sage / GESCOM', dur: '4-6 sem', color: C.navy, status: '' },
    { code: '5', name: 'Usine d’assemblage', dur: '6-8 sem', color: C.navy, status: '' },
    { code: '6', name: 'BI avancé & ML', dur: '4-6 sem', color: C.navy, status: '' },
    { code: '7', name: 'Mobile native', dur: '3-4 sem', color: C.muted, status: 'Optionnel' },
  ];

  const rows = [
    [
      { text: 'Phase', options: { bold: true, color: C.white, fill: { color: C.navy } } },
      { text: 'Activité', options: { bold: true, color: C.white, fill: { color: C.navy } } },
      { text: 'Durée', options: { bold: true, color: C.white, fill: { color: C.navy } } },
      { text: 'Statut', options: { bold: true, color: C.white, fill: { color: C.navy } } },
    ],
    ...phases.map((p) => [p.code, p.name, p.dur, p.status]),
  ];

  s.addTable(rows, {
    x: 0.5,
    y: 1.95,
    w: 9.0,
    colW: [0.9, 5.2, 1.6, 1.3],
    rowH: 0.32,
    fontFace: FONT_BODY,
    fontSize: 11,
    color: C.ink,
    border: { type: 'solid', pt: 0.5, color: C.border },
    valign: 'middle',
  });

  addFooter(s);
}

// ===== Slide 10 — Sprint plan Phase 1 =====
{
  const s = pres.addSlide();
  addPageHeader(s, 'Sprint plan', 10);
  addPageTitle(s, 'Phase 1 — 6 sprints de 2 semaines');
  addSubtitle(s, '~70 jours-homme dev · ~83 jours avec marge 20 % · pilote en fin de S6');

  const sprints = [
    {
      n: 'S1',
      name: 'Fondations',
      items: 'NestJS modulaire · Postgres + Prisma · 1re migration · seed · CI',
    },
    { n: 'S2', name: 'Auth & sécurité', items: 'JWT + refresh · 2FA TOTP · RBAC · audit log auto' },
    { n: 'S3', name: 'Budget', items: 'Saisie ligne · import Excel · 3 scénarios · approbation' },
    { n: 'S4', name: 'Réalisé', items: 'Import balance · équilibre · mapping · calcul écarts' },
    { n: 'S5', name: 'Dashboards', items: '5 écrans · drill-down · filtres · responsive · export' },
    {
      n: 'S6',
      name: 'Stabilisation',
      items: 'Tests E2E · déploiement Scaleway · doc · pilote 2 sem',
    },
  ];

  let y = 1.95;
  sprints.forEach((sp) => {
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.5,
      y,
      w: 9.0,
      h: 0.5,
      fill: { color: C.white },
      line: { color: C.border, width: 0.75 },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.5,
      y,
      w: 0.7,
      h: 0.5,
      fill: { color: C.amber },
      line: { color: C.amber, width: 0 },
    });
    s.addText(sp.n, {
      x: 0.5,
      y,
      w: 0.7,
      h: 0.5,
      fontSize: 14,
      fontFace: FONT_HEAD,
      color: C.navyDeep,
      bold: true,
      align: 'center',
      valign: 'middle',
      margin: 0,
    });
    s.addText(sp.name, {
      x: 1.3,
      y,
      w: 1.7,
      h: 0.5,
      fontSize: 12,
      fontFace: FONT_HEAD,
      color: C.navy,
      bold: true,
      valign: 'middle',
      margin: 0,
    });
    s.addText(sp.items, {
      x: 3.0,
      y,
      w: 6.4,
      h: 0.5,
      fontSize: 11,
      fontFace: FONT_BODY,
      color: C.ink,
      valign: 'middle',
      margin: 0,
    });
    y += 0.55;
  });

  addFooter(s);
}

// ===== Slide 11 — Maquettes (5 écrans) =====
{
  const s = pres.addSlide();
  addPageHeader(s, 'Maquettes UX/UI', 11);
  addPageTitle(s, '5 écrans clés du MVP');
  addSubtitle(
    s,
    'Maquettes HTML cliquables livrées dans /docs/mockups/ — validation visuelle préalable',
  );

  const screens = [
    {
      n: '1',
      title: 'DG — Vue 1 minute',
      desc: 'KPIs, courbe CA, perf marques, alertes critiques. Mobile-first.',
    },
    {
      n: '2',
      title: 'DAF — Tableau d’écarts',
      desc: 'Heatmap par centre de profit · drill-down volume/prix/mix/change.',
    },
    {
      n: '3',
      title: 'Budget vs Réalisé vs Forecast',
      desc: 'Courbe 12 mois · écart cumulé · décomposition par marque.',
    },
    {
      n: '4',
      title: 'Saisie budget',
      desc: 'Tableur 12 mois × N comptes · scénarios · commentaires inline.',
    },
    {
      n: '5',
      title: 'Import balance',
      desc: 'Stepper 4 étapes · hash dedup · équilibre · mapping comptes.',
    },
  ];

  let y = 1.9;
  screens.forEach((sc) => {
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.5,
      y,
      w: 9.0,
      h: 0.55,
      fill: { color: C.white },
      line: { color: C.border, width: 0.75 },
    });
    s.addShape(pres.shapes.OVAL, {
      x: 0.65,
      y: y + 0.1,
      w: 0.35,
      h: 0.35,
      fill: { color: C.amber },
      line: { color: C.amber, width: 0 },
    });
    s.addText(sc.n, {
      x: 0.65,
      y: y + 0.1,
      w: 0.35,
      h: 0.35,
      fontSize: 13,
      fontFace: FONT_HEAD,
      color: C.navyDeep,
      bold: true,
      align: 'center',
      valign: 'middle',
      margin: 0,
    });
    s.addText(sc.title, {
      x: 1.15,
      y,
      w: 3.5,
      h: 0.55,
      fontSize: 12,
      fontFace: FONT_HEAD,
      color: C.navy,
      bold: true,
      valign: 'middle',
      margin: 0,
    });
    s.addText(sc.desc, {
      x: 4.7,
      y,
      w: 4.7,
      h: 0.55,
      fontSize: 11,
      fontFace: FONT_BODY,
      color: C.ink,
      valign: 'middle',
      margin: 0,
    });
    y += 0.6;
  });

  addFooter(s);
}

// ===== Slide 12 — KPIs livrés au pilote =====
{
  const s = pres.addSlide();
  addPageHeader(s, 'KPIs MVP', 12);
  addPageTitle(s, 'KPIs livrés au pilote');
  addSubtitle(s, 'Ce que le DG voit dès le 1er jour de production — mesurés en temps réel');

  const kpis = [
    {
      label: 'CA par marque',
      val: 'Volkswagen, Haval, Chery, Great Wall, SINOTRUK, Lovol & Sealands',
    },
    { label: 'Marge brute', val: 'Globale + par marque + tendance vs budget' },
    { label: 'Écart vs budget', val: 'Décomposé en effets : volume · prix · mix · change' },
    {
      label: 'Forecast atterrissage',
      val: 'Prévision fin d’exercice avec 3 modes (linéaire / tendance / saisonnier)',
    },
    { label: 'Coût moyen véhicule', val: 'Achat + douane + transport, par modèle et par marque' },
    { label: 'Stock VN', val: 'Volume + couverture en mois + véhicules > 60 jours' },
    { label: 'BFR-VN', val: 'Stock + créances clients - dettes fournisseurs' },
    { label: 'Mix commercial', val: 'Répartition des ventes par marque / catégorie' },
  ];

  // 2 colonnes, 4 lignes
  kpis.forEach((k, i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const x = 0.5 + col * 4.55;
    const y = 1.95 + row * 0.78;
    s.addShape(pres.shapes.RECTANGLE, {
      x,
      y,
      w: 4.45,
      h: 0.7,
      fill: { color: C.white },
      line: { color: C.border, width: 0.75 },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x,
      y,
      w: 0.08,
      h: 0.7,
      fill: { color: C.amber },
      line: { color: C.amber, width: 0 },
    });
    s.addText(k.label, {
      x: x + 0.2,
      y: y + 0.05,
      w: 4.15,
      h: 0.3,
      fontSize: 12,
      fontFace: FONT_HEAD,
      color: C.navy,
      bold: true,
      margin: 0,
    });
    s.addText(k.val, {
      x: x + 0.2,
      y: y + 0.32,
      w: 4.15,
      h: 0.36,
      fontSize: 10,
      fontFace: FONT_BODY,
      color: C.ink,
      margin: 0,
    });
  });

  addFooter(s);
}

// ===== Slide 13 — Risques top 5 =====
{
  const s = pres.addSlide();
  addPageHeader(s, 'Risques', 13);
  addPageTitle(s, 'Top 5 risques projet');
  addSubtitle(s, 'Mitigations identifiées · réévaluées en revue mensuelle');

  const rows = [
    [
      { text: 'Risque', options: { bold: true, color: C.white, fill: { color: C.navy } } },
      { text: 'Impact', options: { bold: true, color: C.white, fill: { color: C.navy } } },
      { text: 'Proba.', options: { bold: true, color: C.white, fill: { color: C.navy } } },
      { text: 'Mitigation', options: { bold: true, color: C.white, fill: { color: C.navy } } },
    ],
    [
      'Refus métier de saisir le budget dans l’app',
      'Critique',
      'Haute',
      'Onboarding fort, ambassadeur DAF, import depuis Excel',
    ],
    [
      'Plan compta réel diverge de SYSCOHADA standard',
      'Élevé',
      'Élevée',
      'Mapping configurable, tolérance comptes ad-hoc',
    ],
    [
      'Sage / GESCOM sans API exploitable',
      'Moyen',
      'Élevée',
      'Plan B export CSV manuel mensuel ; ODBC en lecture seule',
    ],
    [
      'Données comptables non fiables (corrections rétroactives)',
      'Élevé',
      'Moyenne',
      'Versioning imports, alerte sur recalculs, snapshot mensuel',
    ],
    [
      'Scope creep (ajout SAV / Usine en Phase 1)',
      'Élevé',
      'Élevée',
      'Roadmap signée, gel scope MVP, feature flags',
    ],
  ];

  s.addTable(rows, {
    x: 0.5,
    y: 1.95,
    w: 9.0,
    colW: [3.4, 1.0, 1.0, 3.6],
    rowH: 0.45,
    fontFace: FONT_BODY,
    fontSize: 10.5,
    color: C.ink,
    border: { type: 'solid', pt: 0.5, color: C.border },
    valign: 'middle',
  });

  addFooter(s);
}

// ===== Slide 14 — Définition du succès =====
{
  const s = pres.addSlide();
  addPageHeader(s, 'Succès du MVP', 14);
  addPageTitle(s, 'Définition du succès — 8 critères');
  addSubtitle(s, 'Mesurés à la fin du pilote (2 semaines après mise en prod)');

  const criteria = [
    { num: '01', label: 'Saisie budget', target: 'DAF saisit budget annuel sans support en < 2 h' },
    { num: '02', label: 'Import comptable', target: 'Charge balance + écarts visibles en < 5 min' },
    {
      num: '03',
      label: 'Dashboard mobile',
      target: 'DG consulte CA / marge / écart sur smartphone en < 30 sec',
    },
    { num: '04', label: 'Cycle complet', target: 'Système gère 12 mois sans pertes de données' },
    {
      num: '05',
      label: '3 scénarios',
      target: 'Optimiste / réaliste / pessimiste coexistent et comparables',
    },
    {
      num: '06',
      label: 'Audit',
      target: '100 % des modifications budget tracées (user + timestamp)',
    },
    { num: '07', label: 'Qualité', target: '0 régression CI/CD · couverture tests > 60 %' },
    {
      num: '08',
      label: 'Disponibilité',
      target: '≥ 99 % sur heures ouvrées (8 h - 19 h, lun - sam)',
    },
  ];

  // 2 columns × 4 rows
  criteria.forEach((c, i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const x = 0.5 + col * 4.55;
    const y = 1.95 + row * 0.78;
    s.addShape(pres.shapes.RECTANGLE, {
      x,
      y,
      w: 4.45,
      h: 0.7,
      fill: { color: C.white },
      line: { color: C.border, width: 0.75 },
    });
    s.addText(c.num, {
      x: x + 0.15,
      y: y + 0.1,
      w: 0.55,
      h: 0.5,
      fontSize: 22,
      fontFace: FONT_HEAD,
      color: C.amber,
      bold: true,
      margin: 0,
    });
    s.addText(c.label, {
      x: x + 0.85,
      y: y + 0.05,
      w: 3.5,
      h: 0.3,
      fontSize: 12,
      fontFace: FONT_HEAD,
      color: C.navy,
      bold: true,
      margin: 0,
    });
    s.addText(c.target, {
      x: x + 0.85,
      y: y + 0.32,
      w: 3.5,
      h: 0.36,
      fontSize: 10,
      fontFace: FONT_BODY,
      color: C.ink,
      margin: 0,
    });
  });

  addFooter(s);
}

// ===== Slide 15 — Next steps =====
{
  const s = pres.addSlide();
  s.background = { color: C.navyDeep };

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0,
    y: 5.0,
    w: 10,
    h: 0.625,
    fill: { color: C.amber },
    line: { color: C.amber, width: 0 },
  });

  s.addText('PROCHAINES ÉTAPES', {
    x: 0.7,
    y: 0.6,
    w: 9,
    h: 0.4,
    fontSize: 12,
    fontFace: FONT_HEAD,
    color: C.amber,
    bold: true,
    margin: 0,
    charSpacing: 6,
  });

  s.addText('Décisions attendues', {
    x: 0.7,
    y: 1.1,
    w: 9,
    h: 1.0,
    fontSize: 40,
    fontFace: FONT_HEAD,
    color: C.white,
    bold: true,
    margin: 0,
  });

  const decisions = [
    {
      n: '1',
      title: 'Validation des hypothèses',
      who: 'DAF + DG · 1 h',
      desc: 'Revoir les 21 HYP en bloc et corriger les écarts avec la réalité.',
    },
    {
      n: '2',
      title: 'GO / NO-GO Sprint 1',
      who: 'DG + DSI · 1 h',
      desc: 'Valider l’équipe, le budget, le planning et l’hébergement Scaleway.',
    },
    {
      n: '3',
      title: 'Identifier l’ambassadeur métier',
      who: 'DG · décision',
      desc: 'Désigner la personne interne qui co-pilote la conception au quotidien.',
    },
  ];

  let y = 2.3;
  decisions.forEach((d) => {
    s.addShape(pres.shapes.OVAL, {
      x: 0.7,
      y: y + 0.1,
      w: 0.5,
      h: 0.5,
      fill: { color: C.amber },
      line: { color: C.amber, width: 0 },
    });
    s.addText(d.n, {
      x: 0.7,
      y: y + 0.1,
      w: 0.5,
      h: 0.5,
      fontSize: 18,
      fontFace: FONT_HEAD,
      color: C.navyDeep,
      bold: true,
      align: 'center',
      valign: 'middle',
      margin: 0,
    });
    s.addText(d.title, {
      x: 1.4,
      y: y,
      w: 6.5,
      h: 0.35,
      fontSize: 16,
      fontFace: FONT_HEAD,
      color: C.white,
      bold: true,
      margin: 0,
    });
    s.addText(d.who, {
      x: 7.9,
      y: y,
      w: 1.7,
      h: 0.35,
      fontSize: 10,
      fontFace: FONT_BODY,
      color: C.amber,
      align: 'right',
      bold: true,
      margin: 0,
      charSpacing: 2,
    });
    s.addText(d.desc, {
      x: 1.4,
      y: y + 0.35,
      w: 8.0,
      h: 0.35,
      fontSize: 12,
      fontFace: FONT_BODY,
      color: C.ice,
      margin: 0,
    });
    y += 0.85;
  });

  s.addText(
    'Atelier de validation proposé : 2 h en présence DG / DAF / DSI + Cheikh Mbacké Dieng',
    {
      x: 0.7,
      y: 5.15,
      w: 9,
      h: 0.35,
      fontSize: 12,
      fontFace: FONT_BODY,
      color: C.navyDeep,
      bold: true,
      valign: 'middle',
      margin: 0,
    },
  );
}

// ===== Write file =====
const outPath = path.resolve(__dirname, '..', 'docs', 'cadrage-pitch.pptx');
pres
  .writeFile({ fileName: outPath })
  .then(() => {
    console.log(`OK: ${outPath}`);
  })
  .catch((err) => {
    console.error('ERROR generating PPTX:', err);
    process.exit(1);
  });
