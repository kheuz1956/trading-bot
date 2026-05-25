#!/usr/bin/env python3
"""
News Surveillance Engine — Veille 24/7 financière, macroéconomique,
géopolitique et institutionnelle.

Sources couvertes :
  - Banques centrales : Fed (FOMC), ECB, BOE, BOJ (flux RSS officiels)
  - Agences : Reuters, AP Business
  - Marchés : CNBC Markets, MarketWatch, Yahoo Finance, Investing.com
  - Macro/Opinion : ZeroHedge, FXStreet
  - Google News (fallback universel)

Classification IA (règles + pondération) :
  hawkish / dovish / bullish / bearish / risk-on / risk-off
  Impact par actif : NQ, SPX, DJI, DXY, VIX, GOLD, OIL, BONDS

Intégration bot :
  - quick_check(direction) → (safe: bool, reason: str, size_factor: float)
  - full_scan()            → SurveillanceReport (rapport complet)
  - start_background_loop() → tâche asyncio 24/7
"""

import asyncio
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

log = logging.getLogger("xtb_pw")

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION DES SOURCES
# ══════════════════════════════════════════════════════════════════════════════

# Délai cache par source (secondes)
_CACHE_TTL = {
    "fed":        180,   # Banque centrale — mise à jour rapide
    "ecb":        300,
    "boe":        300,
    "boj":        300,
    "reuters":    120,
    "ap":         120,
    "cnbc":       90,
    "marketwatch":120,
    "yahoo":      120,
    "investing":  180,
    "zerohedge":  300,
    "fxstreet":   180,
    "gnews":      120,   # Google News fallback
}

# Flux RSS par source
_RSS_FEEDS = {
    "fed":         "https://www.federalreserve.gov/feeds/press_all.xml",
    "ecb":         "https://www.ecb.europa.eu/rss/press.html",
    "boe":         "https://www.bankofengland.co.uk/rss/publications",
    "reuters":     "https://feeds.reuters.com/reuters/businessNews",
    "ap":          "https://feeds.apnews.com/rss/business",
    "cnbc":        "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    "marketwatch": "https://feeds.marketwatch.com/marketwatch/marketpulse/",
    "yahoo":       "https://finance.yahoo.com/news/rssindex",
    "investing":   "https://www.investing.com/rss/news_25.rss",
    "zerohedge":   "https://feeds.feedburner.com/zerohedge/feed",
    "fxstreet":    "https://www.fxstreet.com/rss/news",
}

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

# ══════════════════════════════════════════════════════════════════════════════
# LEXIQUES DE CLASSIFICATION
# ══════════════════════════════════════════════════════════════════════════════

_HAWKISH = [
    "rate hike", "tighten", "tightening", "hawkish", "restrictive",
    "higher for longer", "above neutral", "not cutting soon", "patience",
    "inflation too high", "above target", "persistent inflation",
    "balance sheet reduction", "quantitative tightening", "qt",
    "further increases", "not yet confident", "more work to do",
    "upside risk", "inflation surprise", "wage growth", "core sticky",
    "services inflation", "shelter inflation", "strong labor",
    "overheating", "no cuts", "policy firm",
]

_DOVISH = [
    "rate cut", "cutting rates", "dovish", "easing", "accommodation",
    "below target", "inflation cooling", "disinflation", "pivot",
    "loosen", "loosening", "stimulus", "qe", "quantitative easing",
    "soft landing", "pause", "hold rates", "neutral rate",
    "labor market cooling", "unemployment rising", "growth slowing",
    "recession risk", "below expectations", "miss", "weaker",
]

_BEARISH_NQ = [
    "recession", "inflation surge", "rate hike", "hawkish", "tariff",
    "sanction", "war", "conflict", "crash", "bubble", "default", "crisis",
    "collapse", "sell-off", "selloff", "fear", "panic", "layoffs",
    "guidance cut", "trade war", "geopolitical tension", "uncertainty",
    "downgrade", "contraction", "stagflation", "debt ceiling", "shutdown",
    "ban", "restrict", "export control", "chip ban", "tech war",
    "vix spike", "correction", "bear market", "quantitative tighten",
    "yield curve inversion", "job loss", "unemployment rise",
    "margin call", "liquidation", "deleveraging", "contagion",
    "trump tariff", "china tariff", "25%", "145%", "100%",
    "nuclear", "missile", "attack", "iran", "north korea",
    "treasury downgrade", "moody", "fitch", "s&p downgrade",
    "banking crisis", "bank failure", "contagion", "credit event",
]

_BULLISH_NQ = [
    "rate cut", "dovish", "stimulus", "rally", "surge", "boom",
    "all-time high", "earnings beat", "revenue beat", "guidance raise",
    "buyback", "dividend", "deal", "agreement", "ceasefire",
    "trade deal", "fed pivot", "pause", "soft landing",
    "ai boom", "artificial intelligence", "nvidia beat", "microsoft",
    "innovation", "gdp beat", "jobs beat", "nfp beat",
    "de-escalation", "truce", "tariff exemption", "tariff reduction",
    "rate relief", "qe", "buyback", "m&a", "ipo",
    "record revenue", "outperform", "upgrade", "blowout quarter",
    "peace deal", "trade agreement", "semiconductor recovery",
]

_HIGH_IMPACT_KEYWORDS = [
    # Banques centrales
    "fed", "fomc", "powell", "federal reserve", "ecb", "lagarde",
    "boe", "bailey", "boj", "ueda", "rate decision", "monetary policy",
    # Données macro critiques
    "cpi", "pce", "nfp", "payroll", "gdp", "unemployment",
    "inflation", "jobs report", "retail sales", "pmi", "ism",
    # Événements systémiques
    "trump", "china", "russia", "ukraine", "israel", "iran",
    "tariff", "sanction", "war", "nuclear", "default", "crisis",
    # Earnings majeurs
    "nvidia", "nvda", "apple", "aapl", "microsoft", "msft",
    "meta", "google", "alphabet", "amazon", "tesla",
    # Finance systémique
    "treasury", "debt ceiling", "downgrade", "recession",
    "banking crisis", "fed emergency", "circuit breaker",
]

_CB_MEMBERS = {
    "FED": [
        "powell", "waller", "jefferson", "williams", "daly",
        "kashkari", "bostic", "barr", "cook", "kugler",
        "mester", "goolsbee", "federal reserve", "fomc",
    ],
    "ECB": [
        "lagarde", "de guindos", "lane", "schnabel", "knot",
        "nagel", "villeroy", "centeno", "ecb", "european central bank",
    ],
    "BOE": [
        "bailey", "broadbent", "ramsden", "mann", "haskel",
        "bank of england", "boe", "mpc",
    ],
    "BOJ": [
        "ueda", "himino", "uchida", "bank of japan", "boj",
    ],
}

# Mots-clés géopolitiques à fort impact
_GEOPOLITICAL_HIGH = [
    "nuclear", "missile strike", "war declaration", "invasion",
    "default sovereign", "emergency g7", "emergency g20",
    "fed emergency meeting", "circuit breaker activated",
    "market halt", "trading suspended", "flash crash",
    "oil embargo", "strait of hormuz", "taiwan strait",
]

# ══════════════════════════════════════════════════════════════════════════════
# DATACLASSES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class NewsItem:
    title:     str
    source:    str
    url:       str        = ""
    timestamp: float      = 0.0
    # Classification
    sentiment:     str   = "NEUTRE"   # BULLISH | BEARISH | HAWKISH | DOVISH | NEUTRE
    market_tone:   str   = "NEUTRE"   # RISK_ON | RISK_OFF | NEUTRE
    impact:        str   = "LOW"      # HIGH | MEDIUM | LOW
    score:         float = 0.0        # -1.0 baissier → +1.0 haussier
    # Impact par actif (0-10)
    impact_nq:     float = 0.0
    impact_spx:    float = 0.0
    impact_dxy:    float = 0.0
    impact_vix:    float = 0.0
    impact_gold:   float = 0.0
    impact_oil:    float = 0.0
    # Flags
    is_cb_event:   bool  = False      # Discours/décision banque centrale
    is_geo_crisis: bool  = False      # Crise géopolitique majeure
    cb_bank:       str   = ""         # FED | ECB | BOE | BOJ
    cb_tone:       str   = ""         # HAWKISH | DOVISH | NEUTRE


@dataclass
class SurveillanceReport:
    timestamp:          float = 0.0
    # Sentiment global
    composite_score:    float = 0.0        # -1 → +1
    regime:             str   = "NEUTRE"   # RISK_ON | RISK_OFF | NEUTRE | VOLATILE
    # Alertes triées par importance
    top_alerts:         list[NewsItem] = field(default_factory=list)
    # Banques centrales
    cb_detected:        bool  = False
    cb_bank:            str   = ""
    cb_tone:            str   = ""
    cb_headline:        str   = ""
    # Géopolitique
    geo_risk:           str   = "LOW"      # LOW | MODERATE | HIGH | CRITICAL
    geo_headline:       str   = ""
    # Décision de trading
    trade_action:       str   = "CONTINUE" # CONTINUE | REDUCE | PAUSE | ABORT
    trade_size_factor:  float = 1.0        # 0.5 = demi-volume | 0 = stop
    block_reason:       str   = ""
    # Stats
    sources_fetched:    int   = 0
    items_analyzed:     int   = 0
    high_impact_count:  int   = 0
    fetch_errors:       list[str] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# CLASSIFIEUR DE SENTIMENT
# ══════════════════════════════════════════════════════════════════════════════

def _classify(title: str, source: str) -> NewsItem:
    """Classifie un titre de news et calcule l'impact sur chaque actif."""
    t = title.lower()
    item = NewsItem(title=title, source=source, timestamp=time.time())

    # ── Impact global (présence de mots-clés à fort impact) ──────────────────
    hi_hits = sum(1 for kw in _HIGH_IMPACT_KEYWORDS if kw in t)
    if hi_hits >= 3:
        item.impact = "HIGH"
    elif hi_hits >= 1:
        item.impact = "MEDIUM"

    # ── Banques centrales ─────────────────────────────────────────────────────
    for bank, members in _CB_MEMBERS.items():
        if any(m in t for m in members):
            item.is_cb_event = True
            item.cb_bank     = bank
            h_score = sum(1 for kw in _HAWKISH if kw in t)
            d_score = sum(1 for kw in _DOVISH  if kw in t)
            if h_score > d_score:
                item.cb_tone = "HAWKISH"
            elif d_score > h_score:
                item.cb_tone = "DOVISH"
            else:
                item.cb_tone = "NEUTRE"
            item.impact = "HIGH"
            break

    # ── Géopolitique ──────────────────────────────────────────────────────────
    if any(kw in t for kw in _GEOPOLITICAL_HIGH):
        item.is_geo_crisis = True
        item.impact        = "HIGH"

    # ── Score de sentiment NQ ─────────────────────────────────────────────────
    bull = sum(1 for kw in _BULLISH_NQ if kw in t)
    bear = sum(1 for kw in _BEARISH_NQ if kw in t)

    raw_score = (bull - bear) / max(bull + bear, 1)
    item.score = round(max(-1.0, min(1.0, raw_score)), 2)

    if item.score > 0.25:
        item.sentiment   = "BULLISH"
        item.market_tone = "RISK_ON"
    elif item.score < -0.25:
        item.sentiment   = "BEARISH"
        item.market_tone = "RISK_OFF"
    else:
        item.sentiment   = "NEUTRE"
        item.market_tone = "NEUTRE"

    # Ajuster avec hawkish/dovish
    if item.cb_tone == "HAWKISH":
        item.sentiment   = "HAWKISH"
        item.market_tone = "RISK_OFF"
        item.score       = min(item.score - 0.3, -0.2)
    elif item.cb_tone == "DOVISH":
        item.sentiment   = "DOVISH"
        item.market_tone = "RISK_ON"
        item.score       = max(item.score + 0.3, 0.2)

    # ── Impact par actif ──────────────────────────────────────────────────────
    s = abs(item.score)
    nq_mult = 1.0

    # NQ/NASDAQ sensible à : Fed, Tech earnings, Tarifs, Récession
    if any(kw in t for kw in ["nvidia", "microsoft", "apple", "meta", "google", "amazon", "tech", "semiconductor"]):
        nq_mult = 1.5
    if any(kw in t for kw in ["tariff", "chip ban", "export control"]):
        nq_mult = 1.4

    item.impact_nq  = round(min(10, s * 10 * nq_mult), 1)
    item.impact_spx = round(min(10, s * 9), 1)

    # DXY : monte si hawkish, baisse si dovish
    dxy_sign = 1.0 if item.cb_tone == "HAWKISH" else (-1.0 if item.cb_tone == "DOVISH" else -item.score)
    item.impact_dxy = round(min(10, abs(dxy_sign) * 7), 1)

    # VIX : monte si bearish/risque, baisse si bullish
    vix_sign = 1.0 if item.score < 0 or item.is_geo_crisis else -0.3
    item.impact_vix = round(min(10, abs(vix_sign) * s * 10 + (3 if item.is_geo_crisis else 0)), 1)

    # Gold : safe haven, monte si risk-off / géo
    gold_up = item.market_tone == "RISK_OFF" or item.is_geo_crisis
    item.impact_gold = round(min(10, (s * 8 if gold_up else s * 3)), 1)

    # Oil : géopolitique Moyen-Orient dominant
    oil_up = any(kw in t for kw in ["iran", "opec", "hormuz", "oil", "crude", "petrol", "energy"])
    item.impact_oil = round(min(10, s * 9 if oil_up else s * 4), 1)

    return item


# ══════════════════════════════════════════════════════════════════════════════
# FETCH RSS (synchrone — appelé via run_in_executor)
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_rss_sync(url: str, source: str, max_items: int = 15) -> list[NewsItem]:
    """Fetch RSS synchrone — à lancer dans un thread executor."""
    items: list[NewsItem] = []
    try:
        req = Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/rss+xml,application/xml,*/*"})
        with urlopen(req, timeout=8) as resp:
            raw = resp.read()
        root = ET.fromstring(raw)
        # Gérer namespaces RSS 2.0 et Atom
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = (
            root.findall(".//item")           # RSS 2.0
            or root.findall(".//atom:entry", ns)  # Atom
        )
        for entry in entries[:max_items]:
            title_el = entry.find("title")
            if title_el is None:
                title_el = entry.find("atom:title", ns)
            link_el = entry.find("link")
            if link_el is None:
                link_el = entry.find("atom:link", ns)
            if title_el is None or not title_el.text:
                continue
            title = title_el.text.strip()
            url_  = ""
            if link_el is not None:
                url_ = (link_el.text or link_el.get("href") or "").strip()
            news = _classify(title, source)
            news.url = url_
            items.append(news)
    except Exception as exc:
        log.debug(f"RSS {source}: {exc}")
    return items


def _fetch_gnews_sync(query: str, max_items: int = 10) -> list[NewsItem]:
    """Google News RSS comme fallback universel pour tout sujet."""
    items: list[NewsItem] = []
    try:
        encoded = quote_plus(query)
        url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
        req = Request(url, headers={"User-Agent": _USER_AGENT})
        with urlopen(req, timeout=8) as resp:
            raw = resp.read()
        root = ET.fromstring(raw)
        for entry in root.findall(".//item")[:max_items]:
            title_el = entry.find("title")
            if title_el is None or not title_el.text:
                continue
            title  = title_el.text.strip()
            source = "gnews"
            # Extraire la source depuis le titre Google News "Article Title - Source Name"
            if " - " in title:
                parts  = title.rsplit(" - ", 1)
                title  = parts[0].strip()
                source = parts[1].strip()
            news     = _classify(title, source)
            items.append(news)
    except Exception as exc:
        log.debug(f"Google News: {exc}")
    return items


# ══════════════════════════════════════════════════════════════════════════════
# MOTEUR PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

class NewsSurveillanceEngine:
    """
    Moteur de veille 24/7.

    Usage dans le bot :
        self._surveillance = NewsSurveillanceEngine()
        asyncio.create_task(self._surveillance.start_background_loop())
        ...
        safe, reason, factor = await self._surveillance.quick_check(sig.direction)
    """

    def __init__(self, scan_interval: int = 120):
        self._scan_interval = scan_interval   # secondes entre chaque scan complet
        self._cache:  dict[str, tuple[float, list[NewsItem]]] = {}   # source → (ts, items)
        self._last_report: Optional[SurveillanceReport] = None
        self._running = False
        self._bg_task: Optional[asyncio.Task] = None

    # ── Fetch avec cache ──────────────────────────────────────────────────────

    async def _get_feed(self, source: str, url: str) -> list[NewsItem]:
        """Retourne items depuis cache ou fetch frais."""
        ttl   = _CACHE_TTL.get(source, 180)
        now   = time.time()
        ts, cached = self._cache.get(source, (0, []))
        if now - ts < ttl:
            return cached
        loop  = asyncio.get_event_loop()
        items = await loop.run_in_executor(None, _fetch_rss_sync, url, source)
        self._cache[source] = (now, items)
        return items

    async def _get_gnews(self, query: str, key: str) -> list[NewsItem]:
        """Google News avec cache par query."""
        ttl  = 120
        now  = time.time()
        ts, cached = self._cache.get(key, (0, []))
        if now - ts < ttl:
            return cached
        loop  = asyncio.get_event_loop()
        items = await loop.run_in_executor(None, _fetch_gnews_sync, query)
        self._cache[key] = (now, items)
        return items

    # ── Scan complet ──────────────────────────────────────────────────────────

    async def full_scan(self) -> SurveillanceReport:
        """Récupère toutes les sources et produit un rapport complet."""
        report = SurveillanceReport(timestamp=time.time())
        all_items: list[NewsItem] = []

        # --- Flux RSS primaires (parallèle) ---
        tasks = {
            src: asyncio.create_task(self._get_feed(src, url))
            for src, url in _RSS_FEEDS.items()
        }
        errors: list[str] = []
        for src, task in tasks.items():
            try:
                items = await asyncio.wait_for(task, timeout=12)
                all_items.extend(items)
                if items:
                    report.sources_fetched += 1
            except asyncio.TimeoutError:
                errors.append(f"{src}:timeout")
            except Exception as e:
                errors.append(f"{src}:{e}")

        # --- Google News pour thèmes critiques (parallèle) ---
        gnews_queries = {
            "gn_fed":   "Federal Reserve monetary policy rate 2025",
            "gn_macro": "US economy GDP inflation jobs report",
            "gn_trade": "US China tariffs trade war 2025",
            "gn_geo":   "geopolitical risk oil Iran Taiwan 2025",
            "gn_tech":  "NVIDIA earnings tech stocks Nasdaq",
        }
        gnews_tasks = {
            key: asyncio.create_task(self._get_gnews(q, key))
            for key, q in gnews_queries.items()
        }
        for key, task in gnews_tasks.items():
            try:
                items = await asyncio.wait_for(task, timeout=10)
                all_items.extend(items)
                if items:
                    report.sources_fetched += 1
            except (asyncio.TimeoutError, Exception) as e:
                errors.append(f"{key}:{e}")

        report.fetch_errors    = errors
        report.items_analyzed  = len(all_items)

        if not all_items:
            report.trade_action      = "CONTINUE"
            report.trade_size_factor = 1.0
            return report

        # --- Tri et filtrage ---
        # Priorité : HIGH → MEDIUM → LOW, puis score abs
        all_items.sort(
            key=lambda x: (
                {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(x.impact, 0),
                abs(x.score),
                x.is_cb_event,
                x.is_geo_crisis,
            ),
            reverse=True,
        )
        report.top_alerts = all_items[:10]
        report.high_impact_count = sum(1 for i in all_items if i.impact == "HIGH")

        # --- Détection banque centrale ---
        for item in all_items:
            if item.is_cb_event and item.cb_tone:
                report.cb_detected  = True
                report.cb_bank      = item.cb_bank
                report.cb_tone      = item.cb_tone
                report.cb_headline  = item.title[:120]
                break

        # --- Détection crise géopolitique ---
        geo_items = [i for i in all_items if i.is_geo_crisis]
        if geo_items:
            geo_count = len(geo_items)
            if geo_count >= 5:
                report.geo_risk = "CRITICAL"
            elif geo_count >= 3:
                report.geo_risk = "HIGH"
            elif geo_count >= 1:
                report.geo_risk = "MODERATE"
            report.geo_headline = geo_items[0].title[:120]

        # --- Score composite (pondéré par impact) ---
        weight_map = {"HIGH": 3.0, "MEDIUM": 1.5, "LOW": 0.5}
        total_w = sum(weight_map.get(i.impact, 0.5) for i in all_items)
        if total_w > 0:
            weighted = sum(
                i.score * weight_map.get(i.impact, 0.5) for i in all_items
            )
            report.composite_score = round(weighted / total_w, 3)

        if report.composite_score > 0.15:
            report.regime = "RISK_ON"
        elif report.composite_score < -0.15:
            report.regime = "RISK_OFF"
        elif report.high_impact_count >= 5:
            report.regime = "VOLATILE"
        else:
            report.regime = "NEUTRE"

        # --- Décision de trading ---
        report.trade_action, report.trade_size_factor, report.block_reason = (
            self._trade_decision(report)
        )

        self._last_report = report
        return report

    def _trade_decision(
        self, report: SurveillanceReport
    ) -> tuple[str, float, str]:
        """Traduit le rapport en décision opérationnelle."""

        # ABORT — crise systémique détectée
        if report.geo_risk == "CRITICAL":
            return "ABORT", 0.0, f"Crise géopolitique critique: {report.geo_headline[:80]}"

        if report.composite_score < -0.60:
            return "ABORT", 0.0, f"Sentiment global effondré ({report.composite_score:.2f}) — news très négatives"

        # PAUSE — risque élevé mais pas critique
        if report.geo_risk == "HIGH":
            return "PAUSE", 0.0, f"Risque géopolitique élevé: {report.geo_headline[:80]}"

        if report.composite_score < -0.40:
            return "PAUSE", 0.0, f"Sentiment négatif fort ({report.composite_score:.2f})"

        if report.cb_detected and report.cb_tone == "HAWKISH" and report.cb_bank == "FED":
            return "PAUSE", 0.0, f"Fed HAWKISH détecté: {report.cb_headline[:80]}"

        # REDUCE — tension modérée
        if report.composite_score < -0.20 or report.geo_risk == "MODERATE":
            return "REDUCE", 0.5, "Tension modérée — volume réduit à 50%"

        if report.cb_detected and report.cb_tone == "HAWKISH":
            return "REDUCE", 0.5, f"{report.cb_bank} HAWKISH — volume réduit"

        if report.high_impact_count >= 6:
            return "REDUCE", 0.7, f"{report.high_impact_count} événements HIGH impact — prudence"

        # CONTINUE normal
        return "CONTINUE", 1.0, ""

    # ── Quick check (appelé dans _tick) ───────────────────────────────────────

    async def quick_check(self, direction: str) -> tuple[bool, str, float]:
        """
        Vérification rapide avant exécution d'un trade.

        Returns:
            (safe, reason, size_factor)
            safe=False → bloquer le trade
            size_factor < 1.0 → réduire le volume
        """
        # Si un scan récent existe (< 3 min), l'utiliser
        report = self._last_report
        if report and (time.time() - report.timestamp) < 180:
            pass
        else:
            # Lancer un scan rapide des sources prioritaires
            report = await self._quick_scan()

        # ABORT / PAUSE → blocage total (crise ou sentiment effondré)
        if report.trade_action in ("ABORT", "PAUSE"):
            return False, report.block_reason, 0.0

        # REDUCE → autoriser avec volume réduit (news tendu mais pas critique)
        # Ne pas bloquer directionnellement sur REDUCE — la décision appartient
        # au scoring technique + conviction, pas à la surveillance seule.
        # Bloquer uniquement si le score est proche de PAUSE (< -0.45) ET
        # que le biais directionnel va clairement contre le sentiment.
        if direction == "LONG" and report.composite_score < -0.45:
            return False, f"Sentiment trop negatif ({report.composite_score:.2f}) — attendre amelioration", 0.0

        if direction == "SHORT" and report.composite_score > 0.45:
            return False, f"Sentiment trop positif ({report.composite_score:.2f}) — attendre correction", 0.0

        # Ajustement du facteur selon la tension residuelle
        factor = report.trade_size_factor
        if direction == "LONG" and report.composite_score < -0.30:
            # Score entre -0.30 et -0.45 : LONG autorise mais volume reduit a 70%
            factor = min(factor, 0.7)
            reason = f"LONG sous tension modere ({report.composite_score:+.2f}) — volume {factor*100:.0f}%"
        elif direction == "SHORT" and report.composite_score > 0.30:
            factor = min(factor, 0.7)
            reason = f"SHORT contre sentiment haussier ({report.composite_score:+.2f}) — volume {factor*100:.0f}%"
        else:
            reason = report.block_reason or f"OK ({report.regime}, score={report.composite_score:+.2f})"

        return True, reason, factor

    async def _quick_scan(self) -> SurveillanceReport:
        """Scan léger des 4 sources les plus réactives."""
        report = SurveillanceReport(timestamp=time.time())
        quick_sources = {
            "cnbc":    _RSS_FEEDS["cnbc"],
            "reuters": _RSS_FEEDS["reuters"],
            "fed":     _RSS_FEEDS["fed"],
            "yahoo":   _RSS_FEEDS["yahoo"],
        }
        all_items: list[NewsItem] = []
        tasks = {
            src: asyncio.create_task(self._get_feed(src, url))
            for src, url in quick_sources.items()
        }
        for src, task in tasks.items():
            try:
                items = await asyncio.wait_for(task, timeout=6)
                all_items.extend(items)
            except Exception:
                pass

        if not all_items:
            report.trade_action      = "CONTINUE"
            report.trade_size_factor = 1.0
            return report

        all_items.sort(key=lambda x: abs(x.score) + (1 if x.impact == "HIGH" else 0), reverse=True)
        report.items_analyzed = len(all_items)
        report.top_alerts     = all_items[:6]
        report.high_impact_count = sum(1 for i in all_items if i.impact == "HIGH")

        for item in all_items:
            if item.is_cb_event:
                report.cb_detected = True
                report.cb_bank     = item.cb_bank
                report.cb_tone     = item.cb_tone
                report.cb_headline = item.title[:120]
                break
        for item in all_items:
            if item.is_geo_crisis:
                report.geo_risk    = "HIGH"
                report.geo_headline = item.title[:120]
                break

        weight_map = {"HIGH": 3.0, "MEDIUM": 1.5, "LOW": 0.5}
        total_w = sum(weight_map.get(i.impact, 0.5) for i in all_items)
        if total_w > 0:
            report.composite_score = round(
                sum(i.score * weight_map.get(i.impact, 0.5) for i in all_items) / total_w, 3
            )
        report.regime = (
            "RISK_ON"  if report.composite_score > 0.15 else
            "RISK_OFF" if report.composite_score < -0.15 else
            "NEUTRE"
        )
        report.trade_action, report.trade_size_factor, report.block_reason = (
            self._trade_decision(report)
        )
        self._last_report = report
        return report

    # ── Boucle 24/7 ───────────────────────────────────────────────────────────

    async def start_background_loop(self):
        """
        Lance le monitoring 24/7 en tâche de fond.
        Appeler via : asyncio.create_task(engine.start_background_loop())
        """
        self._running = True
        log.info("[SURVEILLANCE] Démarrage monitoring 24/7 — intervalle scan: %ds", self._scan_interval)
        while self._running:
            try:
                report = await self.full_scan()
                _log_report_summary(report)
            except Exception as exc:
                log.warning(f"[SURVEILLANCE] Erreur scan complet: {exc}")
            await asyncio.sleep(self._scan_interval)

    def stop(self):
        self._running = False
        if self._bg_task and not self._bg_task.done():
            self._bg_task.cancel()

    # ── Rapport console ───────────────────────────────────────────────────────

    def print_report(self, report: SurveillanceReport):
        _print_full_report(report)

    def get_last_report(self) -> Optional[SurveillanceReport]:
        return self._last_report


# ══════════════════════════════════════════════════════════════════════════════
# AFFICHAGE
# ══════════════════════════════════════════════════════════════════════════════

def _log_report_summary(report: SurveillanceReport):
    """Log compact du résultat de scan (background loop)."""
    action_sym = {"CONTINUE": "OK", "REDUCE": "~", "PAUSE": "!", "ABORT": "XX"}.get(
        report.trade_action, "?"
    )
    cb_str  = f" | CB:{report.cb_bank} {report.cb_tone}" if report.cb_detected else ""
    geo_str = f" | GEO:{report.geo_risk}" if report.geo_risk != "LOW" else ""
    log.info(
        f"[SURVEILLANCE] [{action_sym}] {report.regime} | score={report.composite_score:+.2f}"
        f" | {report.sources_fetched} sources | {report.high_impact_count} HIGH"
        f"{cb_str}{geo_str}"
    )
    if report.trade_action in ("PAUSE", "ABORT"):
        log.warning(f"[SURVEILLANCE] ALERTE: {report.block_reason}")
    if report.fetch_errors:
        log.debug(f"[SURVEILLANCE] Erreurs fetch: {report.fetch_errors[:3]}")


def _print_full_report(report: SurveillanceReport):
    """Rapport détaille dans les logs (ASCII uniquement — compatible cp1252)."""
    ts = datetime.fromtimestamp(report.timestamp, tz=timezone.utc).strftime("%H:%M:%S UTC")
    sep = "=" * 60
    lines = [
        sep,
        f"  SURVEILLANCE REPORT  {ts}",
        sep,
        f"  Regime  : {report.regime} | Score: {report.composite_score:+.3f}",
        f"  Sources : {report.sources_fetched} | Items: {report.items_analyzed} | HIGH: {report.high_impact_count}",
    ]
    if report.cb_detected:
        lines.append(f"  CB EVENT : [{report.cb_bank}] {report.cb_tone} -- {report.cb_headline[:80]}")
    if report.geo_risk != "LOW":
        lines.append(f"  GEO RISK : {report.geo_risk} -- {report.geo_headline[:80]}")
    lines.append(f"  ACTION   : {report.trade_action} (x{report.trade_size_factor:.1f})")
    if report.block_reason:
        lines.append(f"  REASON   : {report.block_reason}")
    if report.top_alerts:
        lines.append("  TOP NEWS :")
        for i, item in enumerate(report.top_alerts[:5], 1):
            sentiment_tag = f"[{item.sentiment}]" if item.sentiment != "NEUTRE" else ""
            lines.append(
                f"    {i}. [{item.impact}] {sentiment_tag} {item.title[:90]}"
            )
            if item.impact_nq >= 5:
                lines.append(
                    f"       Impact -> NQ:{item.impact_nq:.0f} VIX:{item.impact_vix:.0f} "
                    f"DXY:{item.impact_dxy:.0f} GOLD:{item.impact_gold:.0f}"
                )
    lines.append(sep)
    for line in lines:
        log.info(line)


# ══════════════════════════════════════════════════════════════════════════════
# TEST STANDALONE
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    # Force UTF-8 pour eviter UnicodeEncodeError sur Windows cp1252
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    async def _test():
        engine = NewsSurveillanceEngine()
        print("=== Scan complet en cours... ===")
        report = await engine.full_scan()
        engine.print_report(report)
        print(f"\nQuick check LONG: {await engine.quick_check('LONG')}")
        print(f"Quick check SHORT: {await engine.quick_check('SHORT')}")

    asyncio.run(_test())
