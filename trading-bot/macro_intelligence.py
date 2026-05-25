#!/usr/bin/env python3
"""
Macro Intelligence Engine — Surveillance institutionnelle avancée.

Modules :
  1. CentralBankMonitor   — Fed/ECB/BOE/BOJ hawkish/dovish scoring
  2. CorrelationMatrix    — DXY/VIX/Or/Pétrole/Bonds vs NQ
  3. LiquidityFlowDetector — Où va la liquidité mondiale ?
  4. MacroDashboard        — Rapport complet avant chaque trade
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

log = logging.getLogger("xtb_pw")

# ══════════════════════════════════════════════════════════════════════════════
# 1. LEXIQUE BANQUES CENTRALES — HAWKISH / DOVISH
# ══════════════════════════════════════════════════════════════════════════════

# Mots-clés des gouverneurs et membres votants
CB_MEMBERS = {
    "FED": [
        "powell", "waller", "jefferson", "williams", "daly", "kashkari",
        "bostic", "barr", "cook", "kugler", "mester", "goolsbee",
        "federal reserve", "fed", "fomc", "central bank us",
    ],
    "ECB": [
        "lagarde", "de guindos", "lane", "schnabel", "knot", "nagel",
        "villeroy", "centeno", "european central bank", "ecb", "bce",
    ],
    "BOE": [
        "bailey", "broadbent", "cunliffe", "ramsden", "mann", "haskel",
        "bank of england", "boe", "mpc",
    ],
    "BOJ": [
        "ueda", "himino", "uchida", "bank of japan", "boj", "boj governor",
    ],
}

HAWKISH_SIGNALS = [
    # Politique monétaire restrictive
    "rate hike", "tighten", "tightening", "hawkish", "restrictive",
    "higher for longer", "above neutral", "not cutting soon", "patience",
    "inflation too high", "above target", "persistent inflation",
    "strong labor market", "overheating", "balance sheet reduction",
    "quantitative tightening", "qt", "data dependent", "further increases",
    "not yet confident", "more work to do",
    # Signaux implicites
    "upside risk", "inflation surprise", "wage growth", "core sticky",
    "services inflation", "shelter inflation",
]

DOVISH_SIGNALS = [
    # Politique monétaire accommodante
    "rate cut", "easing", "dovish", "accommodative", "stimulus",
    "pivot", "pause", "hold", "cut rates", "lower rates",
    "inflation cooling", "disinflation", "below target",
    "labor market softening", "unemployment rising", "job losses",
    "recession risk", "downside risk", "financial stability",
    "quantitative easing", "qe", "balance sheet expansion",
    "emergency", "crisis", "systemic risk",
    # Signaux implicites
    "confidence inflation", "progress made", "sustainable path",
    "mission accomplished", "neutral rate", "normalization",
]

UNCERTAINTY_SIGNALS = [
    "uncertain", "uncertainty", "data dependent", "meeting by meeting",
    "cautious", "careful", "gradual", "flexible", "watch closely",
    "monitor", "assess", "evaluate", "unclear", "complex",
]


# ══════════════════════════════════════════════════════════════════════════════
# 2. ACTIFS CORRÉLÉS — UNIVERS DE SURVEILLANCE
# ══════════════════════════════════════════════════════════════════════════════

CORRELATED_ASSETS = {
    "VIX":      ("^VIX",    "Volatilité (peur)",         "inverse"),   # VIX haut = NQ bas
    "DXY":      ("DX-Y.NYB","Dollar Index",              "inverse"),   # DXY fort = NQ bas généralement
    "GOLD":     ("GC=F",    "Or (refuge)",               "mixed"),     # Or fort = risk-off parfois
    "OIL":      ("CL=F",    "Pétrole (WTI)",             "positive"),  # Pétrole reflet de l'économie
    "TNX":      ("^TNX",    "Taux 10 ans US",            "inverse"),   # Taux haut = NQ pression
    "SP500":    ("^GSPC",   "S&P 500",                   "positive"),  # Très corrélé NQ
    "BONDS":    ("TLT",     "ETF Obligations 20Y",       "mixed"),
    "SEMIS":    ("SOXX",    "Semiconducteurs (ETF)",     "positive"),  # Très corrélé NQ
    "EUR_USD":  ("EURUSD=X","EUR/USD",                   "positive"),  # Risk sentiment
    "BITCOIN":  ("BTC-USD", "Bitcoin (risk sentiment)",  "positive"),  # Risk-on proxy
}

# ══════════════════════════════════════════════════════════════════════════════
# 3. DATACLASSES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class CentralBankSignal:
    institution: str = ""
    tone: str = "NEUTRE"          # "HAWKISH" | "DOVISH" | "NEUTRE" | "TRES_HAWKISH" | "TRES_DOVISH"
    score: float = 0.0            # -1 (très dovish) → +1 (très hawkish)
    key_phrases: list[str] = field(default_factory=list)
    impact_on_nq: str = "NEUTRE"  # "POSITIF" | "NEGATIF" | "NEUTRE"
    news_count: int = 0

@dataclass
class CorrelationSnapshot:
    asset: str
    name: str
    current_value: float
    change_pct: float      # variation 1 jour
    signal: str            # "RISK_ON" | "RISK_OFF" | "NEUTRE"
    nq_implication: str    # impact probable sur NQ

@dataclass
class LiquidityFlow:
    direction: str = "NEUTRE"     # "VERS_RISQUE" | "VERS_SECURITE" | "NEUTRE"
    risk_on_score: float = 0.0    # -1 → +1
    hot_assets: list[str] = field(default_factory=list)    # actifs achetés
    safe_haven: list[str] = field(default_factory=list)   # refuges achetés
    regime: str = "NEUTRE"       # "RISK_ON" | "RISK_OFF" | "TRANSITON" | "NEUTRE"

@dataclass
class MacroDashboard:
    # Banques centrales
    cb_signals: dict[str, CentralBankSignal] = field(default_factory=dict)
    global_cb_tone: str = "NEUTRE"
    global_cb_score: float = 0.0

    # Corrélations
    correlations: list[CorrelationSnapshot] = field(default_factory=list)
    vix: float = 20.0
    vix_change: float = 0.0
    dxy: float = 100.0
    dxy_change: float = 0.0
    tnx: float = 4.5
    tnx_change: float = 0.0

    # Liquidité
    liquidity: LiquidityFlow = field(default_factory=LiquidityFlow)

    # Verdict global
    macro_bias: str = "NEUTRE"       # "HAUSSIER" | "BAISSIER" | "NEUTRE"
    nq_outlook: str = "NEUTRE"
    trade_confirmation: str = "NEUTRE"  # "CONFIRME" | "CONTRE" | "NEUTRE"
    risk_adjusted: bool = True

    # Meta
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    cache_valid_until: float = 0.0


# ══════════════════════════════════════════════════════════════════════════════
# 4. MOTEUR PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

class MacroIntelligenceEngine:

    CB_CACHE_TTL   = 900   # 15 min — banques centrales changent rarement
    CORR_CACHE_TTL = 300   # 5 min — marchés évoluent vite

    def __init__(self):
        self._dashboard_cache: MacroDashboard | None = None

    async def full_analysis(self, technical_signal: str = "SKIP") -> MacroDashboard:
        """Analyse macro complète : CB + corrélations + liquidité + verdict."""
        now = time.monotonic()

        if self._dashboard_cache and now < self._dashboard_cache.cache_valid_until:
            d = self._dashboard_cache
            d.trade_confirmation = self._confirm_trade(d, technical_signal)
            return d

        loop = asyncio.get_event_loop()
        cb_data, corr_data = await asyncio.gather(
            loop.run_in_executor(None, self._fetch_cb_news),
            loop.run_in_executor(None, self._fetch_correlated_assets),
            return_exceptions=True,
        )

        dash = MacroDashboard()
        dash.cache_valid_until = now + self.CORR_CACHE_TTL

        # ── Banques centrales ─────────────────────────────────────────────────
        if isinstance(cb_data, dict):
            dash.cb_signals    = cb_data
            dash.global_cb_score = self._aggregate_cb_score(cb_data)
            dash.global_cb_tone  = self._score_to_tone(dash.global_cb_score)

        # ── Corrélations marché ───────────────────────────────────────────────
        if isinstance(corr_data, dict):
            dash.vix        = corr_data.get("vix_val",  20.0)
            dash.vix_change = corr_data.get("vix_chg",  0.0)
            dash.dxy        = corr_data.get("dxy_val",  100.0)
            dash.dxy_change = corr_data.get("dxy_chg",  0.0)
            dash.tnx        = corr_data.get("tnx_val",  4.5)
            dash.tnx_change = corr_data.get("tnx_chg",  0.0)
            dash.correlations = corr_data.get("snapshots", [])

        # ── Flux de liquidité ─────────────────────────────────────────────────
        dash.liquidity = self._detect_liquidity_flow(dash)

        # ── Biais macro global ────────────────────────────────────────────────
        dash.macro_bias   = self._compute_macro_bias(dash)
        dash.nq_outlook   = self._nq_outlook(dash)
        dash.trade_confirmation = self._confirm_trade(dash, technical_signal)

        self._dashboard_cache = dash
        return dash

    # ── Fetch banques centrales ───────────────────────────────────────────────

    def _fetch_cb_news(self) -> dict[str, CentralBankSignal]:
        """Analyse le ton des banques centrales via les news yfinance."""
        results: dict[str, CentralBankSignal] = {}

        tickers_to_scan = {
            "FED": ["^IRX", "ZB=F"],    # T-Bill 3M et Bond futures
            "ECB": ["EURUSD=X"],
            "BOE": ["GBPUSD=X"],
            "BOJ": ["JPY=X"],
        }

        all_news: list[str] = []
        for institution, tickers in tickers_to_scan.items():
            cb_sig = CentralBankSignal(institution=institution)
            for ticker_sym in tickers + ["^GSPC", "NQ=F"]:
                try:
                    news = yf.Ticker(ticker_sym).news or []
                    for art in news[:10]:
                        title = art.get("title", "").lower()
                        all_news.append(title)
                        cb_sig.news_count += 1

                        # Vérifier si la news concerne cette BC
                        members = CB_MEMBERS.get(institution, [])
                        if not any(m in title for m in members):
                            continue

                        h = sum(1 for kw in HAWKISH_SIGNALS if kw in title)
                        d = sum(1 for kw in DOVISH_SIGNALS   if kw in title)
                        cb_sig.score += (h - d) * 0.15

                        if h > 0:
                            cb_sig.key_phrases.extend(
                                [kw for kw in HAWKISH_SIGNALS if kw in title][:2]
                            )
                        if d > 0:
                            cb_sig.key_phrases.extend(
                                [kw for kw in DOVISH_SIGNALS if kw in title][:2]
                            )
                except Exception:
                    continue

            cb_sig.score = max(-1.0, min(1.0, cb_sig.score))
            cb_sig.tone  = self._score_to_tone(cb_sig.score)

            # Impact sur NQ : hawkish = baissier pour NQ, dovish = haussier
            if cb_sig.score > 0.2:
                cb_sig.impact_on_nq = "NEGATIF (taux haut = pression NQ)"
            elif cb_sig.score < -0.2:
                cb_sig.impact_on_nq = "POSITIF (assouplissement = soutien NQ)"
            else:
                cb_sig.impact_on_nq = "NEUTRE"

            cb_sig.key_phrases = list(dict.fromkeys(cb_sig.key_phrases))[:4]
            results[institution] = cb_sig

        return results

    # ── Fetch actifs corrélés ─────────────────────────────────────────────────

    def _fetch_correlated_assets(self) -> dict:
        """Télécharge les données des actifs corrélés et calcule les signaux."""
        snapshots: list[CorrelationSnapshot] = []
        data_out: dict = {}

        fetch_map = {
            "VIX":  "^VIX",
            "DXY":  "DX-Y.NYB",
            "TNX":  "^TNX",
            "GOLD": "GC=F",
            "OIL":  "CL=F",
            "SP500":"^GSPC",
            "BTC":  "BTC-USD",
        }

        for key, symbol in fetch_map.items():
            try:
                raw = yf.download(symbol, period="3d", interval="1h",
                                  progress=False, auto_adjust=True)
                if raw.empty or len(raw) < 2:
                    continue
                if isinstance(raw.columns, pd.MultiIndex):
                    raw.columns = raw.columns.get_level_values(0)
                cl = raw["Close"].to_numpy().ravel()
                last = float(cl[-1])
                prev = float(cl[-25]) if len(cl) >= 25 else float(cl[0])
                chg  = (last - prev) / max(abs(prev), 0.01) * 100

                # Stocker les valeurs clés
                if key == "VIX":
                    data_out["vix_val"] = round(last, 2)
                    data_out["vix_chg"] = round(chg, 2)
                elif key == "DXY":
                    data_out["dxy_val"] = round(last, 2)
                    data_out["dxy_chg"] = round(chg, 2)
                elif key == "TNX":
                    data_out["tnx_val"] = round(last, 3)
                    data_out["tnx_chg"] = round(chg, 4)

                # Générer signal
                _, _, correlation, implication = CORRELATED_ASSETS.get(
                    key, (symbol, key, "mixed", "neutre")
                )
                signal, impl = self._asset_signal(key, last, chg)
                snap = CorrelationSnapshot(
                    asset=key,
                    name=CORRELATED_ASSETS.get(key, ("", key))[1],
                    current_value=round(last, 2),
                    change_pct=round(chg, 2),
                    signal=signal,
                    nq_implication=impl,
                )
                snapshots.append(snap)
            except Exception:
                continue

        data_out["snapshots"] = snapshots
        return data_out

    def _asset_signal(self, key: str, value: float, change: float) -> tuple[str, str]:
        """Détermine le signal d'un actif et son implication pour NQ."""
        if key == "VIX":
            if value >= 30:
                return "RISK_OFF", "TRES NEGATIF — panique marché"
            if value >= 20 and change > 5:
                return "RISK_OFF", "NEGATIF — volatilité montante"
            if value < 15 and change < 0:
                return "RISK_ON",  "POSITIF — volatilité comprimée"
            return "NEUTRE", "NEUTRE"

        if key == "DXY":
            if change > 0.5:
                return "RISK_OFF", "NEGATIF — dollar fort pénalise NQ"
            if change < -0.5:
                return "RISK_ON",  "POSITIF — dollar faible soutient NQ"
            return "NEUTRE", "NEUTRE"

        if key == "TNX":
            if value > 4.5 and change > 0.05:
                return "RISK_OFF", "NEGATIF — taux hauts pressent valorisations tech"
            if change < -0.05:
                return "RISK_ON",  "POSITIF — taux baissent, NQ soutenu"
            return "NEUTRE", "NEUTRE"

        if key == "GOLD":
            if change > 1:
                return "RISK_OFF", "ATTENTION — refuge or actif"
            if change < -1:
                return "RISK_ON",  "POSITIF — or baisse = appétit risque"
            return "NEUTRE", "NEUTRE"

        if key == "SP500":
            if change > 0.5:
                return "RISK_ON",  "POSITIF — SP500 haussier confirme NQ"
            if change < -0.5:
                return "RISK_OFF", "NEGATIF — SP500 baissier confirme pression NQ"
            return "NEUTRE", "NEUTRE"

        if key == "BTC":
            if change > 3:
                return "RISK_ON",  "POSITIF — BTC haussier = appétit risque"
            if change < -3:
                return "RISK_OFF", "NEGATIF — BTC baissier = aversion risque"
            return "NEUTRE", "NEUTRE"

        if key == "OIL":
            if change > 2:
                return "RISK_ON", "MIXTE — pétrole haut = économie chaude"
            if change < -2:
                return "RISK_OFF", "NEGATIF — pétrole bas = contraction"
            return "NEUTRE", "NEUTRE"

        return "NEUTRE", "NEUTRE"

    # ── Flux de liquidité ─────────────────────────────────────────────────────

    def _detect_liquidity_flow(self, dash: MacroDashboard) -> LiquidityFlow:
        """Détermine où va la liquidité mondiale."""
        flow = LiquidityFlow()
        risk_on_count  = 0
        risk_off_count = 0

        for snap in dash.correlations:
            if snap.signal == "RISK_ON":
                risk_on_count += 1
                flow.hot_assets.append(f"{snap.asset}({snap.change_pct:+.1f}%)")
            elif snap.signal == "RISK_OFF":
                risk_off_count += 1
                flow.safe_haven.append(f"{snap.asset}({snap.change_pct:+.1f}%)")

        total = risk_on_count + risk_off_count
        if total == 0:
            flow.regime = "NEUTRE"
            flow.risk_on_score = 0.0
        else:
            flow.risk_on_score = round((risk_on_count - risk_off_count) / max(total, 1), 2)
            if flow.risk_on_score > 0.3:
                flow.direction = "VERS_RISQUE"
                flow.regime    = "RISK_ON"
            elif flow.risk_on_score < -0.3:
                flow.direction = "VERS_SECURITE"
                flow.regime    = "RISK_OFF"
            else:
                flow.regime = "TRANSITION"
                flow.direction = "NEUTRE"

        return flow

    # ── Biais macro global ────────────────────────────────────────────────────

    def _compute_macro_bias(self, dash: MacroDashboard) -> str:
        """Calcule le biais macro global (haussier/baissier pour NQ)."""
        score = 0.0

        # CB dovish = haussier NQ, hawkish = baissier NQ
        score -= dash.global_cb_score * 0.4

        # Liquidity flow
        score += dash.liquidity.risk_on_score * 0.4

        # VIX
        if dash.vix < 15:
            score += 0.2
        elif dash.vix > 25:
            score -= 0.3
        elif dash.vix > 20:
            score -= 0.15

        # DXY
        if dash.dxy_change > 0.5:
            score -= 0.15
        elif dash.dxy_change < -0.5:
            score += 0.15

        # TNX
        if dash.tnx > 4.5 and dash.tnx_change > 0:
            score -= 0.15

        if score > 0.2:
            return "HAUSSIER"
        if score < -0.2:
            return "BAISSIER"
        return "NEUTRE"

    def _nq_outlook(self, dash: MacroDashboard) -> str:
        bias = dash.macro_bias
        liq  = dash.liquidity.regime
        if bias == "HAUSSIER" and liq in ("RISK_ON", "NEUTRE"):
            return "POSITIF — conditions favorables NQ"
        if bias == "BAISSIER" and liq in ("RISK_OFF", "NEUTRE"):
            return "NEGATIF — conditions défavorables NQ"
        if liq == "RISK_OFF":
            return "SOUS PRESSION — liquidité vers refuges"
        if liq == "RISK_ON":
            return "SOUTENU — liquidité vers actifs risqués"
        return "NEUTRE — signal mixte"

    def _confirm_trade(self, dash: MacroDashboard, signal: str) -> str:
        if signal == "SKIP":
            return "NEUTRE"
        bias = dash.macro_bias
        liq  = dash.liquidity.regime
        if signal == "SHORT":
            if bias == "BAISSIER" or liq == "RISK_OFF":
                return "CONFIRME — macro aligne SHORT"
            if bias == "HAUSSIER" and liq == "RISK_ON":
                return "CONTRE — macro contredit SHORT"
        if signal == "LONG":
            if bias == "HAUSSIER" or liq == "RISK_ON":
                return "CONFIRME — macro aligne LONG"
            if bias == "BAISSIER" and liq == "RISK_OFF":
                return "CONTRE — macro contredit LONG"
        return "NEUTRE — signal mixte"

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _aggregate_cb_score(self, cb_signals: dict) -> float:
        if not cb_signals:
            return 0.0
        weights = {"FED": 0.5, "ECB": 0.25, "BOE": 0.15, "BOJ": 0.10}
        total_w, total_s = 0.0, 0.0
        for inst, sig in cb_signals.items():
            w = weights.get(inst, 0.1)
            total_w += w
            total_s += sig.score * w
        return round(total_s / max(total_w, 0.01), 3)

    def _score_to_tone(self, score: float) -> str:
        if score >  0.5: return "TRES_HAWKISH"
        if score >  0.2: return "HAWKISH"
        if score < -0.5: return "TRES_DOVISH"
        if score < -0.2: return "DOVISH"
        return "NEUTRE"

    # ── Rapport complet ───────────────────────────────────────────────────────

    def print_dashboard(self, dash: MacroDashboard):
        sep = "─" * 56
        log.info(sep)
        log.info("  MACRO INTELLIGENCE DASHBOARD")
        log.info(sep)

        # Banques centrales
        log.info(f"  [BANQUES CENTRALES] Ton global: {dash.global_cb_tone} ({dash.global_cb_score:+.2f})")
        for inst, sig in dash.cb_signals.items():
            if sig.tone != "NEUTRE" or sig.news_count > 0:
                kp = " | ".join(sig.key_phrases[:2]) if sig.key_phrases else "aucun signal"
                log.info(f"    {inst:4s}: {sig.tone:12s} → {sig.impact_on_nq}")
                if sig.key_phrases:
                    log.info(f"           Signaux: {kp}")

        # Marchés corrélés
        log.info(f"  [MARCHES CORRELES]")
        log.info(
            f"    VIX:  {dash.vix:.1f} ({dash.vix_change:+.1f}%)  | "
            f"DXY: {dash.dxy:.2f} ({dash.dxy_change:+.2f}%)  | "
            f"TNX: {dash.tnx:.2f}% ({dash.tnx_change:+.3f}%)"
        )
        risk_off_snaps = [s for s in dash.correlations if s.signal == "RISK_OFF"]
        risk_on_snaps  = [s for s in dash.correlations if s.signal == "RISK_ON"]
        if risk_off_snaps:
            names = ", ".join(f"{s.asset}({s.change_pct:+.1f}%)" for s in risk_off_snaps)
            log.info(f"    RISK-OFF: {names}")
        if risk_on_snaps:
            names = ", ".join(f"{s.asset}({s.change_pct:+.1f}%)" for s in risk_on_snaps)
            log.info(f"    RISK-ON:  {names}")

        # Liquidité
        log.info(
            f"  [LIQUIDITE]   Regime: {dash.liquidity.regime} | "
            f"Score: {dash.liquidity.risk_on_score:+.2f}"
        )
        if dash.liquidity.hot_assets:
            log.info(f"    Vers risque: {', '.join(dash.liquidity.hot_assets[:4])}")
        if dash.liquidity.safe_haven:
            log.info(f"    Refuges:     {', '.join(dash.liquidity.safe_haven[:4])}")

        # Verdict
        log.info(sep)
        log.info(f"  BIAIS MACRO NQ : {dash.macro_bias}")
        log.info(f"  OUTLOOK        : {dash.nq_outlook}")
        log.info(f"  CONFIRMATION   : {dash.trade_confirmation}")
        log.info(sep)
