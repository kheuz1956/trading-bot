#!/usr/bin/env python3
"""
Institutional Signals Engine — Comportement des gros acteurs sur NQ/US100.

Données gratuites (yfinance + CFTC.gov + CBOE) :
  1. VIX Gate           — Fear & Greed index proxy
  2. Yield Curve        — 10Y-2Y spread (inversion = risk-off)
  3. DXY Correlation    — dollar fort = NQ faible
  4. COT NQ Futures     — CFTC weekly positioning des large speculators
  5. Put/Call Ratio     — sentiment options marché
  6. Sector Breadth     — % Nasdaq stocks au-dessus de la MA20
  7. Composite Score    — score global -1 (bear) à +1 (bull)

Intégration : signal_runner.py appelle get_institutional_filter()
avant chaque trade pour bloquer ou valider.
"""

import csv
import io
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import requests
import yfinance as yf

import config

log = logging.getLogger("xtb_pw")

# ── Cache (évite de re-fetcher à chaque scan de 20s) ─────────────────────────
_CACHE_TTL   = 300   # 5 min pour VIX/yields/DXY
_COT_TTL     = 3600  # 1h pour COT (données hebdo)
_PC_TTL      = 900   # 15 min pour put/call

_cache: dict = {}


def _cached(key: str, ttl: float, fn):
    """Exécute fn() si le cache est expiré, sinon retourne la valeur cachée."""
    now = time.time()
    if key in _cache and now - _cache[key]["ts"] < ttl:
        return _cache[key]["val"]
    try:
        val = fn()
        _cache[key] = {"val": val, "ts": now}
        return val
    except Exception as e:
        log.debug(f"[INST] cache miss {key}: {e}")
        if key in _cache:
            return _cache[key]["val"]
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 1. VIX
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_vix() -> Optional[float]:
    t = yf.Ticker("^VIX")
    hist = t.history(period="1d", interval="5m")
    if hist.empty:
        return None
    return float(hist["Close"].iloc[-1])


def get_vix() -> tuple[float, str]:
    """Retourne (vix_level, régime)."""
    vix = _cached("vix", _CACHE_TTL, _fetch_vix)
    if vix is None:
        return 0.0, "UNKNOWN"

    vix_extreme = getattr(config, "VIX_EXTREME_THRESHOLD", 35.0)
    vix_high    = getattr(config, "VIX_HIGH_THRESHOLD",    25.0)

    if vix >= vix_extreme:
        regime = "PANIC"
    elif vix >= vix_high:
        regime = "FEAR"
    elif vix >= 18:
        regime = "ELEVATED"
    else:
        regime = "CALM"

    return vix, regime


# ══════════════════════════════════════════════════════════════════════════════
# 2. COURBE DES TAUX (Yield Curve)
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_yields() -> dict:
    tickers = {"10Y": "^TNX", "2Y": "^IRX", "30Y": "^TYX", "5Y": "^FVX"}
    result = {}
    for name, sym in tickers.items():
        try:
            h = yf.Ticker(sym).history(period="1d", interval="5m")
            if not h.empty:
                result[name] = float(h["Close"].iloc[-1])
        except Exception:
            pass
    return result


def get_yield_curve() -> tuple[dict, str, float]:
    """Retourne (yields_dict, bias, spread_10y_2y).
    spread > 0  → normale → favorable
    spread < 0  → inversion → récession/risk-off → éviter LONG NQ
    """
    yields = _cached("yields", _CACHE_TTL, _fetch_yields) or {}
    y10 = yields.get("10Y", 0.0)
    y2  = yields.get("2Y",  0.0)

    # Le ^IRX est la T-bill à 13 semaines, pas le 2Y — proxy acceptable
    # La courbe vraie serait ^IRX / 2Y-note mais yfinance gratuit ne l'offre pas directement
    spread = y10 - y2

    if y10 == 0 and y2 == 0:
        bias = "UNKNOWN"
    elif spread < -0.5:
        bias = "INVERTED_DEEP"     # récession signal fort
    elif spread < 0:
        bias = "INVERTED"          # léger risk-off
    elif spread < 1.0:
        bias = "FLAT"              # neutre
    else:
        bias = "NORMAL"            # courbe saine

    return yields, bias, spread


# ══════════════════════════════════════════════════════════════════════════════
# 3. DXY — DOLLAR INDEX
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_dxy() -> Optional[float]:
    # DX-Y.NYB = Dollar Index (ICE)
    for sym in ("DX-Y.NYB", "USDOLLAR"):
        try:
            h = yf.Ticker(sym).history(period="2d", interval="5m")
            if not h.empty:
                return float(h["Close"].iloc[-1])
        except Exception:
            pass
    return None


def get_dxy() -> tuple[float, str]:
    """Retourne (niveau_dxy, biais). DXY fort = pression sur NQ."""
    dxy = _cached("dxy", _CACHE_TTL, _fetch_dxy)
    if not dxy:
        return 0.0, "UNKNOWN"

    # Variation sur 5 bougies (25 min) pour détecter le momentum
    try:
        h = yf.Ticker("DX-Y.NYB").history(period="1d", interval="5m")
        if len(h) >= 5:
            delta = float(h["Close"].iloc[-1]) - float(h["Close"].iloc[-5])
            if delta > 0.15:
                bias = "DXY_SURGING"    # fort headwind pour NQ
            elif delta > 0.05:
                bias = "DXY_RISING"
            elif delta < -0.05:
                bias = "DXY_FALLING"    # tailwind pour NQ
            else:
                bias = "DXY_STABLE"
        else:
            bias = "DXY_STABLE"
    except Exception:
        bias = "UNKNOWN"

    return dxy, bias


# ══════════════════════════════════════════════════════════════════════════════
# 4. COT CFTC — NASDAQ 100 FUTURES
# ══════════════════════════════════════════════════════════════════════════════

# Contract name dans le fichier CFTC
_COT_NQ_NAMES = ("NASDAQ-100 STOCK INDEX - CHICAGO MERCANTILE EXCHANGE",
                  "NASDAQ-100 (MINI)",
                  "E-MINI NASDAQ-100")
_CFTC_BASE_URL = "https://www.cftc.gov/dea/futures/deacmesf.htm"


def _fetch_cot_nq() -> Optional[dict]:
    """Télécharge le rapport COT le plus récent et extrait le NQ."""
    import urllib.request
    # Le fichier CSV complet trimestriel est plus fiable
    cot_csv_url = "https://www.cftc.gov/files/dea/history/deacot_current.zip"
    try:
        import zipfile
        resp = requests.get(cot_csv_url, timeout=15)
        if resp.status_code != 200:
            return None
        z = zipfile.ZipFile(io.BytesIO(resp.content))
        fname = [n for n in z.namelist() if n.endswith(".txt") or n.endswith(".csv")]
        if not fname:
            return None
        with z.open(fname[0]) as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"))
            rows = list(reader)
        # Chercher NQ parmi les dernières lignes
        nq_rows = [r for r in rows
                   if any(k in r.get("Market_and_Exchange_Names", "").upper()
                          for k in ("NASDAQ-100", "NASDAQ 100", "E-MINI NQ"))]
        if not nq_rows:
            return None
        latest = nq_rows[-1]
        long_nc  = float(latest.get("NonComm_Positions_Long_All",  0))
        short_nc = float(latest.get("NonComm_Positions_Short_All", 0))
        oi       = float(latest.get("Open_Interest_All", 1)) or 1
        net      = long_nc - short_nc
        net_pct  = net / oi * 100
        return {
            "long_nc":  long_nc,
            "short_nc": short_nc,
            "net":      net,
            "net_pct":  net_pct,
            "oi":       oi,
            "date":     latest.get("Report_Date_as_YYYY-MM-DD", ""),
        }
    except Exception as e:
        log.debug(f"[COT] fetch error: {e}")
        return None


def get_cot_nq() -> tuple[float, str]:
    """Retourne (net_pct, biais).
    net_pct > 0  → large speculators net long (institutions bull)
    net_pct < 0  → net short (institutions bear)
    """
    cot = _cached("cot_nq", _COT_TTL, _fetch_cot_nq)
    if not cot:
        return 0.0, "UNKNOWN"

    threshold = getattr(config, "COT_CONVICTION_THRESHOLD", 30.0)
    net_pct = cot["net_pct"]

    if net_pct > threshold:
        bias = "INSTITUTIONAL_LONG"
    elif net_pct > 10:
        bias = "MILDLY_LONG"
    elif net_pct < -threshold:
        bias = "INSTITUTIONAL_SHORT"
    elif net_pct < -10:
        bias = "MILDLY_SHORT"
    else:
        bias = "NEUTRAL"

    return net_pct, bias


# ══════════════════════════════════════════════════════════════════════════════
# 5. PUT/CALL RATIO — CBOE
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_put_call_ratio() -> Optional[float]:
    """CBOE equity put/call ratio (gratuit, mis à jour intraday)."""
    try:
        resp = requests.get(
            "https://www.cboe.com/publish/scheduledtask/mktdata/cboesymboldata/options_pcr.csv",
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        if resp.status_code != 200:
            return None
        lines = resp.text.strip().split("\n")
        # Format : DATE,CALL,PUT,TOTAL,P/C RATIO
        for line in reversed(lines):
            parts = line.strip().split(",")
            if len(parts) >= 5:
                try:
                    return float(parts[4])
                except ValueError:
                    continue
    except Exception as e:
        log.debug(f"[PC] fetch error: {e}")
    return None


def get_put_call_ratio() -> tuple[float, str]:
    """Retourne (ratio, biais).
    ratio > 1.0 → plus de puts que de calls → sentiment bear/prudence
    ratio < 0.7 → trop de calls → euphorie → contrarian bear
    """
    pc = _cached("put_call", _PC_TTL, _fetch_put_call_ratio)
    if pc is None:
        return 0.0, "UNKNOWN"

    if pc > 1.2:
        bias = "EXTREME_FEAR"
    elif pc > 0.9:
        bias = "BEARISH_SENTIMENT"
    elif pc < 0.5:
        bias = "EXTREME_GREED"   # contrarian warning
    elif pc < 0.7:
        bias = "BULLISH_SENTIMENT"
    else:
        bias = "NEUTRAL"

    return pc, bias


# ══════════════════════════════════════════════════════════════════════════════
# 6. SECTOR BREADTH — % NQ 100 stocks > MA20
# ══════════════════════════════════════════════════════════════════════════════

_NQ100_ETFS = {
    "QQQ":  "Nasdaq 100 ETF",
    "XLK":  "Tech sector",
    "SMH":  "Semiconductors",
    "IGV":  "Software",
    "SOXX": "Semiconductors (iShares)",
}

def _fetch_sector_breadth() -> Optional[dict]:
    result = {}
    for sym, name in _NQ100_ETFS.items():
        try:
            h = yf.Ticker(sym).history(period="1mo", interval="1d")
            if len(h) >= 20:
                close = float(h["Close"].iloc[-1])
                ma20  = float(h["Close"].rolling(20).mean().iloc[-1])
                pct_vs_ma = (close - ma20) / ma20 * 100
                result[sym] = {"close": close, "ma20": ma20, "pct_vs_ma": pct_vs_ma}
        except Exception:
            pass
    return result if result else None


def get_sector_breadth() -> tuple[dict, str, float]:
    """Retourne (data_dict, biais, qqq_vs_ma20_pct)."""
    data = _cached("breadth", _CACHE_TTL, _fetch_sector_breadth) or {}
    qqq_pct = data.get("QQQ", {}).get("pct_vs_ma", 0.0)

    if qqq_pct > 3:
        bias = "STRONG_BULL"
    elif qqq_pct > 1:
        bias = "BULL"
    elif qqq_pct > -1:
        bias = "NEUTRAL"
    elif qqq_pct > -3:
        bias = "BEAR"
    else:
        bias = "STRONG_BEAR"

    return data, bias, qqq_pct


# ══════════════════════════════════════════════════════════════════════════════
# 7. COMPOSITE INSTITUTIONNEL
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class InstitutionalContext:
    # VIX
    vix:            float = 0.0
    vix_regime:     str   = "UNKNOWN"
    # Yields
    yield_10y:      float = 0.0
    yield_2y:       float = 0.0
    yield_spread:   float = 0.0
    yield_bias:     str   = "UNKNOWN"
    # DXY
    dxy:            float = 0.0
    dxy_bias:       str   = "UNKNOWN"
    # COT
    cot_net_pct:    float = 0.0
    cot_bias:       str   = "UNKNOWN"
    # Put/Call
    put_call:       float = 0.0
    pc_bias:        str   = "UNKNOWN"
    # Breadth
    qqq_vs_ma20:    float = 0.0
    breadth_bias:   str   = "UNKNOWN"
    # Composite
    composite_score: float = 0.0   # -1.0 (bear) to +1.0 (bull)
    can_trade:      bool  = True
    block_reason:   str   = ""
    timestamp:      float = field(default_factory=time.time)


def get_institutional_filter(direction: str = "LONG") -> InstitutionalContext:
    """
    Point d'entrée principal. Retourne InstitutionalContext.
    direction : "LONG" | "SHORT" — utilisé pour ajuster les règles de blocage.
    """
    ctx = InstitutionalContext()

    # ── Collecter (en parallèle si possible) ─────────────────────────────────
    ctx.vix, ctx.vix_regime = get_vix()
    yields, ctx.yield_bias, ctx.yield_spread = get_yield_curve()
    ctx.yield_10y = yields.get("10Y", 0.0)
    ctx.yield_2y  = yields.get("2Y",  0.0)
    ctx.dxy, ctx.dxy_bias          = get_dxy()
    ctx.cot_net_pct, ctx.cot_bias  = get_cot_nq()
    ctx.put_call, ctx.pc_bias      = get_put_call_ratio()
    _, ctx.breadth_bias, ctx.qqq_vs_ma20 = get_sector_breadth()

    # ── Score composite ───────────────────────────────────────────────────────
    score = 0.0

    # VIX : -0.3 (PANIC) à 0 (CALM) — pénalise les trades dans la peur
    vix_scores = {"CALM": 0.1, "ELEVATED": 0.0, "FEAR": -0.2, "PANIC": -0.5, "UNKNOWN": 0.0}
    score += vix_scores.get(ctx.vix_regime, 0.0)

    # Yield curve : inversion = bear pour NQ
    if ctx.yield_bias in ("INVERTED_DEEP", "INVERTED"):
        score -= 0.15
    elif ctx.yield_bias == "NORMAL":
        score += 0.05

    # DXY : hausse du dollar = pressure sur NQ
    dxy_scores = {"DXY_SURGING": -0.2, "DXY_RISING": -0.1, "DXY_STABLE": 0.0,
                  "DXY_FALLING": 0.1, "UNKNOWN": 0.0}
    score += dxy_scores.get(ctx.dxy_bias, 0.0)

    # COT : positioning institutionnel
    cot_scores = {"INSTITUTIONAL_LONG": 0.2, "MILDLY_LONG": 0.1, "NEUTRAL": 0.0,
                  "MILDLY_SHORT": -0.1, "INSTITUTIONAL_SHORT": -0.2, "UNKNOWN": 0.0}
    score += cot_scores.get(ctx.cot_bias, 0.0)

    # Put/call
    pc_scores = {"EXTREME_FEAR": 0.1,  # contrarian: peur extrême → bottom proche
                 "BEARISH_SENTIMENT": -0.05, "NEUTRAL": 0.0,
                 "BULLISH_SENTIMENT": 0.05, "EXTREME_GREED": -0.1,
                 "UNKNOWN": 0.0}
    score += pc_scores.get(ctx.pc_bias, 0.0)

    # Breadth
    breadth_scores = {"STRONG_BULL": 0.1, "BULL": 0.05, "NEUTRAL": 0.0,
                      "BEAR": -0.05, "STRONG_BEAR": -0.1}
    score += breadth_scores.get(ctx.breadth_bias, 0.0)

    ctx.composite_score = max(-1.0, min(1.0, score))

    # ── Règles de blocage ─────────────────────────────────────────────────────
    ctx.can_trade = True
    ctx.block_reason = ""

    # VIX extrême : stop trading (cohérent avec config.py)
    if ctx.vix_regime == "PANIC":
        ctx.can_trade    = False
        ctx.block_reason = f"VIX={ctx.vix:.1f} — PANIC (>{config.VIX_EXTREME_THRESHOLD})"

    # COT contre le trade (institutionnels nets à l'opposé avec forte conviction)
    copy_smart_money = getattr(config, "COPY_SMART_MONEY", True)
    threshold        = getattr(config, "COT_CONVICTION_THRESHOLD", 30.0)
    if copy_smart_money and abs(ctx.cot_net_pct) > threshold:
        if direction == "LONG"  and ctx.cot_bias == "INSTITUTIONAL_SHORT":
            ctx.can_trade    = False
            ctx.block_reason = (f"COT: institutionnels nets SHORT {ctx.cot_net_pct:.1f}% "
                                f"(seuil >{threshold:.0f}%) — LONG bloqué")
        elif direction == "SHORT" and ctx.cot_bias == "INSTITUTIONAL_LONG":
            ctx.can_trade    = False
            ctx.block_reason = (f"COT: institutionnels nets LONG {ctx.cot_net_pct:.1f}% "
                                f"(seuil >{threshold:.0f}%) — SHORT bloqué")

    return ctx


def log_institutional_context(ctx: InstitutionalContext) -> None:
    """Log compact de l'analyse institutionnelle."""
    score_str = f"{ctx.composite_score:+.2f}"
    log.info(
        f"  [INST] VIX={ctx.vix:.1f}({ctx.vix_regime}) | "
        f"Yields 10Y={ctx.yield_10y:.2f}% 2Y={ctx.yield_2y:.2f}%({ctx.yield_bias}) | "
        f"DXY={ctx.dxy:.1f}({ctx.dxy_bias}) | "
        f"COT={ctx.cot_net_pct:.1f}%({ctx.cot_bias}) | "
        f"PC={ctx.put_call:.2f}({ctx.pc_bias}) | "
        f"Breadth({ctx.breadth_bias}) | Score={score_str}"
    )
    if not ctx.can_trade:
        log.warning(f"  [INST] BLOCAGE INSTITUTIONNEL: {ctx.block_reason}")
