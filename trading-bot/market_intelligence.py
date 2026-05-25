#!/usr/bin/env python3
"""
Module d'intelligence de marché — surveillance news, sentiment, régime macro.
Intégré dans le bot avant chaque décision de trade.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import yfinance as yf

log = logging.getLogger("xtb_pw")

# ── Lexique de sentiment US100 / Nasdaq ──────────────────────────────────────

_BEARISH = [
    "recession", "inflation", "rate hike", "hawkish", "tariff", "sanction",
    "war", "conflict", "crash", "bubble", "default", "crisis", "collapse",
    "sell-off", "selloff", "dump", "fear", "panic", "layoffs", "miss",
    "guidance cut", "trade war", "geopolitical", "uncertainty", "downgrade",
    "contraction", "stagflation", "debt ceiling", "shutdown", "impeach",
    "ban", "restrict", "export control", "chip ban", "tech war", "vix spike",
    "correction", "bear market", "fed tightening", "quantitative tighten",
    "yield curve inversion", "inverted", "job loss", "unemployment rise",
    "margin call", "liquidation", "deleveraging", "contagion",
    "trump tariff", "china tariff", "25%", "145%", "100%",  # tariff numbers
]

_BULLISH = [
    "rate cut", "dovish", "stimulus", "rally", "surge", "boom", "all-time high",
    "earnings beat", "revenue beat", "guidance raise", "buyback", "dividend",
    "deal", "agreement", "ceasefire", "trade deal", "fed pivot", "pause",
    "soft landing", "ai", "artificial intelligence", "nvidia", "microsoft",
    "apple", "magnificent seven", "innovation", "growth", "expansion",
    "gdp beat", "jobs beat", "nfp beat", "consumer confidence",
    "de-escalation", "truce", "tariff exemption", "tariff reduction",
    "rate relief", "quantitative ease", "qe", "buyback", "m&a",
    "ipo", "unicorn", "blockbuster", "blowout", "record", "outperform",
]

_HIGH_IMPACT = [
    "fed", "fomc", "powell", "ecb", "boj", "cpi", "pce", "nfp",
    "gdp", "trump", "china", "russia", "ukraine", "israel", "iran",
    "nvidia", "apple", "microsoft", "meta", "google", "amazon",
    "recession", "rate", "tariff", "war", "emergency",
]

# ── Sources de données gratuites ──────────────────────────────────────────────

_TICKERS_TO_MONITOR = ["^IXIC", "^GSPC", "^VIX", "NQ=F", "QQQ", "SPY"]

# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class NewsItem:
    title: str
    source: str
    score: float    # -1.0 (très baissier) → +1.0 (très haussier)
    impact: str     # "HIGH" | "MEDIUM" | "LOW"
    timestamp: int  # unix

@dataclass
class MarketIntelligence:
    # Sentiment global
    sentiment_score: float = 0.0          # -1 → +1
    regime: str = "NEUTRE"                # RISK-ON | RISK-OFF | NEUTRE | VOLATILE
    bias: str = "NEUTRE"                  # HAUSSIER | BAISSIER | NEUTRE

    # News
    top_news: list[NewsItem] = field(default_factory=list)
    news_summary: str = ""
    high_impact_count: int = 0

    # Marché
    vix_level: float = 0.0
    vix_regime: str = ""        # FAIBLE | MODERE | ELEVE | EXTREME
    dxy_bias: str = ""          # FORT | NEUTRE | FAIBLE
    nasdaq_trend: str = ""      # HAUSSIER | BAISSIER | LATERAL

    # Décision
    signal_reinforced: bool = False   # sentiment aligne avec signal technique
    signal_contradicted: bool = False # sentiment contredit le signal
    trade_allowed: bool = True        # False si macro trop défavorable

    # Meta
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    cache_valid_until: float = 0.0    # monotonic time


# ── Analyseur principal ───────────────────────────────────────────────────────

class MarketIntelligenceEngine:

    CACHE_TTL = 600  # 10 minutes — évite de spammer yfinance

    def __init__(self):
        self._cache: MarketIntelligence | None = None

    async def analyze(self, technical_signal: str = "SKIP") -> MarketIntelligence:
        """Analyse complète marché + news + sentiment."""
        now = time.monotonic()

        # Utiliser le cache si encore valide
        if self._cache and now < self._cache.cache_valid_until:
            mi = self._cache
            mi.signal_reinforced  = self._check_alignment(mi.bias, technical_signal)
            mi.signal_contradicted = self._check_contradiction(mi.bias, technical_signal)
            mi.trade_allowed      = self._trade_allowed(mi)
            return mi

        mi = MarketIntelligence()
        mi.cache_valid_until = now + self.CACHE_TTL

        # Récupération données en parallèle
        news_items, market_data = await asyncio.gather(
            self._fetch_news(),
            self._fetch_market_data(),
            return_exceptions=True,
        )

        if isinstance(news_items, list):
            mi.top_news         = news_items
            mi.sentiment_score  = self._aggregate_sentiment(news_items)
            mi.high_impact_count= sum(1 for n in news_items if n.impact == "HIGH")
            mi.news_summary     = self._summarize(news_items)

        if isinstance(market_data, dict):
            mi.vix_level    = market_data.get("vix", 20.0)
            mi.vix_regime   = self._vix_regime(mi.vix_level)
            mi.nasdaq_trend = market_data.get("nasdaq_trend", "LATERAL")
            mi.dxy_bias     = market_data.get("dxy_bias", "NEUTRE")

        # Régime global
        mi.regime = self._classify_regime(mi.sentiment_score, mi.vix_level)
        mi.bias   = self._classify_bias(mi.sentiment_score, mi.nasdaq_trend)

        # Décision
        mi.signal_reinforced   = self._check_alignment(mi.bias, technical_signal)
        mi.signal_contradicted = self._check_contradiction(mi.bias, technical_signal)
        mi.trade_allowed       = self._trade_allowed(mi)

        self._cache = mi
        return mi

    # ── Données marché ────────────────────────────────────────────────────────

    async def _fetch_market_data(self) -> dict:
        """Récupère VIX, tendance Nasdaq depuis yfinance."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._fetch_market_data_sync)

    def _fetch_market_data_sync(self) -> dict:
        result = {}
        try:
            vix = yf.download("^VIX", period="2d", interval="1h",
                              progress=False, auto_adjust=True)
            if not vix.empty:
                cols = vix.columns.get_level_values(0) if hasattr(vix.columns, "get_level_values") else vix.columns
                vix.columns = cols
                result["vix"] = float(vix["Close"].iloc[-1])
        except Exception:
            result["vix"] = 20.0

        try:
            nq = yf.download("NQ=F", period="5d", interval="1h",
                             progress=False, auto_adjust=True)
            if not nq.empty:
                cols = nq.columns.get_level_values(0) if hasattr(nq.columns, "get_level_values") else nq.columns
                nq.columns = cols
                cl = nq["Close"].to_numpy().ravel()
                ema20 = float(nq["Close"].ewm(span=20, adjust=False).mean().iloc[-1])
                last  = float(cl[-1])
                result["nasdaq_trend"] = "HAUSSIER" if last > ema20 else "BAISSIER"
        except Exception:
            result["nasdaq_trend"] = "LATERAL"

        result["dxy_bias"] = "NEUTRE"  # DXY nécessite abonnement — neutre par défaut
        return result

    # ── News ──────────────────────────────────────────────────────────────────

    async def _fetch_news(self) -> list[NewsItem]:
        """Récupère les news depuis yfinance (gratuit, pas de quota)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._fetch_news_sync)

    def _fetch_news_sync(self) -> list[NewsItem]:
        items: list[NewsItem] = []
        seen: set[str] = set()

        for ticker_sym in ["NQ=F", "QQQ", "^GSPC", "^IXIC"]:
            try:
                ticker = yf.Ticker(ticker_sym)
                news   = ticker.news or []
                for art in news[:8]:
                    title = art.get("title", "")
                    if not title or title in seen:
                        continue
                    seen.add(title)
                    score  = self._score_title(title)
                    impact = self._impact_level(title)
                    items.append(NewsItem(
                        title=title,
                        source=art.get("publisher", ticker_sym),
                        score=score,
                        impact=impact,
                        timestamp=art.get("providerPublishTime", 0),
                    ))
            except Exception:
                continue

        # Trier par impact puis par score absolu
        items.sort(key=lambda x: (x.impact == "HIGH", abs(x.score)), reverse=True)
        return items[:12]

    # ── Scoring ───────────────────────────────────────────────────────────────

    def _score_title(self, title: str) -> float:
        """Score de -1.0 à +1.0 basé sur les mots-clés."""
        t = title.lower()
        bear = sum(1 for kw in _BEARISH if kw in t)
        bull = sum(1 for kw in _BULLISH if kw in t)
        raw  = bull - bear
        return float(max(-1.0, min(1.0, raw * 0.25)))

    def _impact_level(self, title: str) -> str:
        t = title.lower()
        hi = sum(1 for kw in _HIGH_IMPACT if kw in t)
        return "HIGH" if hi >= 2 else ("MEDIUM" if hi == 1 else "LOW")

    def _aggregate_sentiment(self, items: list[NewsItem]) -> float:
        if not items:
            return 0.0
        # Pondérer HIGH×3, MEDIUM×1.5, LOW×1
        weights = {"HIGH": 3.0, "MEDIUM": 1.5, "LOW": 1.0}
        total_w, total_s = 0.0, 0.0
        for item in items:
            w = weights[item.impact]
            total_w += w
            total_s += item.score * w
        return round(total_s / max(total_w, 1), 3)

    def _summarize(self, items: list[NewsItem]) -> str:
        high = [n for n in items if n.impact == "HIGH"][:3]
        if not high:
            high = items[:2]
        return " | ".join(n.title[:60] for n in high) if high else "Aucune news significative"

    # ── Classification ────────────────────────────────────────────────────────

    def _vix_regime(self, vix: float) -> str:
        if vix < 15:  return "FAIBLE (calme)"
        if vix < 20:  return "MODERE"
        if vix < 30:  return "ELEVE (prudence)"
        return "EXTREME (danger)"

    def _classify_regime(self, score: float, vix: float) -> str:
        if vix >= 30:
            return "VOLATILE"
        if score > 0.2:
            return "RISK-ON"
        if score < -0.2:
            return "RISK-OFF"
        return "NEUTRE"

    def _classify_bias(self, score: float, nasdaq_trend: str) -> str:
        if score > 0.15 or nasdaq_trend == "HAUSSIER":
            if score > 0.15 and nasdaq_trend == "HAUSSIER":
                return "HAUSSIER"
            return "LEGEREMENT HAUSSIER"
        if score < -0.15 or nasdaq_trend == "BAISSIER":
            if score < -0.15 and nasdaq_trend == "BAISSIER":
                return "BAISSIER"
            return "LEGEREMENT BAISSIER"
        return "NEUTRE"

    def _check_alignment(self, bias: str, signal: str) -> bool:
        if signal == "SKIP":
            return False
        if signal == "SHORT" and "BAISSIER" in bias:
            return True
        if signal == "LONG" and "HAUSSIER" in bias:
            return True
        return False

    def _check_contradiction(self, bias: str, signal: str) -> bool:
        if signal == "SKIP":
            return False
        if signal == "SHORT" and "HAUSSIER" in bias:
            return True
        if signal == "LONG" and "BAISSIER" in bias:
            return True
        return False

    def _trade_allowed(self, mi: MarketIntelligence) -> bool:
        # Bloquer si VIX extrême ET sentiment très négatif
        if mi.vix_level >= 40 and mi.sentiment_score < -0.6:
            return False
        return True

    # ── Rapport pré-trade ─────────────────────────────────────────────────────

    def print_report(self, mi: MarketIntelligence, signal: str, levels: dict):
        sep = "─" * 56

        def align_icon(signal_confirmed: bool, contradicted: bool) -> str:
            if contradicted: return "⚠"
            if signal_confirmed: return "✓"
            return "~"

        tech_ok   = signal != "SKIP"
        macro_ok  = not mi.signal_contradicted
        regime_ok = mi.regime != "VOLATILE"

        log.info(sep)
        log.info("  PRE-TRADE ANALYSIS")
        log.info(sep)

        # Technique
        log.info(f"  [TECHNIQUE]     {signal:5s}  — Ichimoku + MACD + ADX + RSI")

        # Fondamental / Macro
        log.info(f"  [MACRO]         Bias: {mi.bias}  | Regime: {mi.regime}")
        log.info(f"  [VIX]           {mi.vix_level:.1f}  {mi.vix_regime}")
        log.info(f"  [NASDAQ TREND]  {mi.nasdaq_trend}")

        # Sentiment
        score_bar = self._score_bar(mi.sentiment_score)
        log.info(f"  [SENTIMENT]     {mi.sentiment_score:+.2f}  {score_bar}")
        if mi.high_impact_count:
            log.info(f"  [NEWS IMPACT]   {mi.high_impact_count} news HIGH impact detectees")
        if mi.news_summary:
            log.info(f"  [TOP NEWS]      {mi.news_summary[:80]}")

        # Risk
        if levels:
            log.info(f"  [RISQUE]        SL={levels['sl']}  TP1={levels['tp1']}  TP2={levels['tp2']}  R:R={levels['rr']}")

        # Alignement signal/macro
        if mi.signal_reinforced:
            log.info(f"  [ALIGNEMENT]    Signal TECHNIQUE + MACRO alignes — CONVICTION HAUTE")
        elif mi.signal_contradicted:
            log.info(f"  [ALIGNEMENT]  ! Signal contredit par macro — PRUDENCE")
        else:
            log.info(f"  [ALIGNEMENT]    Macro neutre — signal technique seul")

        # Verdict
        go    = tech_ok and mi.trade_allowed
        verd  = "EXECUTION" if go else "SKIP (macro)"
        log.info(sep)
        log.info(f"  DECISION : {verd}")
        log.info(sep)

    def _score_bar(self, score: float) -> str:
        """Barre visuelle -1 à +1."""
        filled = int((score + 1) / 2 * 10)
        bar    = "[" + "#" * filled + "." * (10 - filled) + "]"
        label  = "BEARISH" if score < -0.2 else ("BULLISH" if score > 0.2 else "NEUTRE")
        return f"{bar} {label}"
