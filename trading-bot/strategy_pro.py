#!/usr/bin/env python3
"""
Stratégie PRO — Meilleur Trader du Monde
Concepts : Multi-Timeframe + Order Blocks + Fair Value Gaps + Kill Zones + Scoring A+

Philosophie :
  - D1  → Biais directionnel (tendance macro)
  - H4  → Structure de marché + Order Blocks
  - H1  → Entrée précise (Ichimoku + RSI + MACD)
  - M15 → Timing d'exécution optimal

Règle d'or : N'entrer QUE sur des setups A+ (≥4 confluences alignées).
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

import config

log = logging.getLogger("xtb_pw")

# ── Kill Zones UTC (liquidité institutionnelle maximale) ──────────────────────
KILL_ZONES = {
    "LONDON_OPEN":    (7 * 60,       10 * 60),    # 07:00 – 10:00 UTC (pré-London + ouverture)
    "NY_OPEN":        (13 * 60 + 30, 16 * 60),    # 13:30 – 16:00 UTC
    "NY_AFTERNOON":   (16 * 60,      20 * 60),    # 16:00 – 20:00 UTC (session NY active)
    "NY_CLOSE":       (20 * 60,      21 * 60),    # 20:00 – 21:00 UTC (clôture, éviter)
}

# ── Score minimal pour ouvrir un trade ────────────────────────────────────────
MIN_SCORE_A_PLUS = 5   # A+ setup : exécution immédiate (confluences maximales)
MIN_SCORE_A      = 3   # A setup  : exécution normale
MIN_SCORE_B      = 3   # B setup  : seuil relevé 2→3 (filtrage plus strict)

# ── Filtre de proximité entrée ─────────────────────────────────────────────────
# Bloque le trade si le prix actuel est à plus de MAX_ENTRY_SLIPPAGE_ATR × ATR
# de l'entrée calculée (évite d'entrer trop loin d'un niveau technique clé)
MAX_ENTRY_SLIPPAGE_ATR = 0.4   # 40% de l'ATR maximum de slippage acceptable


# ── Dataclass signal ──────────────────────────────────────────────────────────

@dataclass
class ProSignal:
    direction: str = "SKIP"      # "LONG" | "SHORT" | "SKIP"
    grade: str     = "SKIP"      # "A+" | "A" | "B" | "SKIP"
    score: int     = 0           # nombre de confluences
    confluences: list[str]  = field(default_factory=list)
    warnings: list[str]     = field(default_factory=list)
    skip_reasons: list[str] = field(default_factory=list)

    # Prix
    entry: float  = 0.0
    sl:    float  = 0.0
    tp1:   float  = 0.0
    tp2:   float  = 0.0
    tp3:   float  = 0.0          # Extension 1:3 pour les A+
    rr:    str    = ""
    atr:   float  = 0.0

    # Contexte
    d1_bias:       str = ""
    h4_structure:  str = ""
    h1_signal:     str = ""
    kill_zone:     str = ""
    order_block:   bool = False
    fvg_present:   bool = False
    key_level_hit: bool = False

    def to_levels(self) -> dict:
        return dict(
            entry=self.entry, sl=self.sl,
            tp1=self.tp1, tp2=self.tp2,
            risk=round(abs(self.sl - self.entry), 2),
            rr=self.rr,
        )


# ── Chargement multi-timeframe ────────────────────────────────────────────────

_TICKERS = ["NQ=F", "^NDX", "QQQ"]  # fallback chain si yfinance indisponible

def _download(period: str, interval: str) -> pd.DataFrame:
    for ticker in _TICKERS:
        try:
            raw = yf.download(ticker, period=period, interval=interval,
                              progress=False, auto_adjust=True)
            if raw.empty:
                continue
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            idx = raw.index.get_level_values(0) if isinstance(raw.index, pd.MultiIndex) else raw.index
            df = pd.DataFrame({
                "Open":   raw["Open"].to_numpy().ravel(),
                "High":   raw["High"].to_numpy().ravel(),
                "Low":    raw["Low"].to_numpy().ravel(),
                "Close":  raw["Close"].to_numpy().ravel(),
                "Volume": raw["Volume"].to_numpy().ravel(),
            }, index=pd.to_datetime(idx, utc=True))
            df = df.dropna()
            if not df.empty:
                return df
        except Exception:
            continue
    return pd.DataFrame()


def load_mtf() -> dict[str, pd.DataFrame]:
    """Charge D1, H4, H1, M15 en parallèle via yfinance."""
    return {
        "D1":  _download("60d", "1d"),
        "H4":  _download("30d", "4h"),
        "H1":  _download("5d",  "1h"),
        "M15": _download("2d",  "15m"),
        "M5":  _download("1d",  "5m"),
    }


def analyze_m15(df: pd.DataFrame) -> dict:
    """Signal M15 pour compléter H1 en range (Kumo) — EMA 9/21/50 + MACD + ADX."""
    if df is None or len(df) < 55:
        return {"signal": "SKIP", "reason": "Données M15 insuffisantes"}

    cl = df["Close"]
    e9  = _ema(cl, 9).iloc[-2]
    e21 = _ema(cl, 21).iloc[-2]
    e50 = _ema(cl, 50).iloc[-2]
    macd_h = _macd_hist(cl).iloc[-2]
    adx_v  = _adx(df).iloc[-2]
    rsi_v  = _rsi(cl).iloc[-2]
    atr_v  = _atr(df).iloc[-1]
    last   = float(cl.iloc[-2])

    long_ok  = (last > e9 > e21 and macd_h > 0 and adx_v >= 30 and rsi_v < 75)
    short_ok = (last < e9 < e21 and macd_h < 0 and adx_v >= 30 and rsi_v > 25)

    direction = "LONG" if long_ok else ("SHORT" if short_ok else "SKIP")
    return {
        "signal": direction,
        "close": round(last, 2),
        "ema9":  round(float(e9),  2),
        "ema21": round(float(e21), 2),
        "ema50": round(float(e50), 2),
        "macd":  round(float(macd_h), 2),
        "adx":   round(float(adx_v),  1),
        "rsi":   round(float(rsi_v),  1),
        "atr":   round(float(atr_v),  1),
    }


def analyze_m5(df: pd.DataFrame) -> dict:
    """
    Signal scalping M5 — EMA 5/13/34 + MACD + ADX + momentum 3/5 bougies.
    Conditions plus souples qu'en H1 (ADX >= SCALP_ADX_MIN, RSI 25-75).
    Utilisé uniquement si config.SCALP_MODE=True et que H1+M15 sont SKIP.
    """
    if df is None or len(df) < 40:
        return {"signal": "SKIP", "reason": "Donnees M5 insuffisantes"}

    cl  = df["Close"]
    op  = df["Open"]
    e5  = _ema(cl, 5).iloc[-2]
    e13 = _ema(cl, 13).iloc[-2]
    e34 = _ema(cl, 34).iloc[-2]
    macd_h = _macd_hist(cl).iloc[-2]
    adx_v  = _adx(df).iloc[-2]
    rsi_v  = _rsi(cl).iloc[-2]
    atr_v  = _atr(df).iloc[-1]
    last   = float(cl.iloc[-2])

    # Momentum : 3 des 5 dernières bougies M5 fermées dans la direction
    m5_cl  = cl.iloc[-6:-1]
    m5_op  = op.iloc[-6:-1]
    bull_n = int((m5_cl > m5_op).sum())
    bear_n = 5 - bull_n

    long_ok  = (
        last > e5 > e13
        and macd_h > 0
        and adx_v >= config.SCALP_ADX_MIN
        and rsi_v < 72
        and bull_n >= 3
    )
    short_ok = (
        last < e5 < e13
        and macd_h < 0
        and adx_v >= config.SCALP_ADX_MIN
        and rsi_v > 28
        and bear_n >= 3
    )

    direction = "LONG" if long_ok else ("SHORT" if short_ok else "SKIP")
    reason = ""
    if direction == "SKIP":
        if adx_v < config.SCALP_ADX_MIN:
            reason = f"ADX M5 trop faible ({adx_v:.0f} < {config.SCALP_ADX_MIN})"
        elif bull_n < 3 and bear_n < 3:
            reason = f"Momentum M5 insuffisant ({bull_n}/5 bull, {bear_n}/5 bear)"
        else:
            reason = "Pas d'alignement EMA5/13 + MACD M5"

    return {
        "signal":   direction,
        "close":    round(last, 2),
        "ema5":     round(float(e5),  2),
        "ema13":    round(float(e13), 2),
        "ema34":    round(float(e34), 2),
        "macd":     round(float(macd_h), 3),
        "adx":      round(float(adx_v),  1),
        "rsi":      round(float(rsi_v),  1),
        "atr":      round(float(atr_v),  1),
        "bull_n":   bull_n,
        "bear_n":   bear_n,
        "reason":   reason,
    }


# ── Indicateurs de base ───────────────────────────────────────────────────────

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift()).abs(),
        (df["Low"]  - df["Close"].shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()

def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    d = close.diff()
    g = d.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, np.nan))

def _macd_hist(close: pd.Series, fast=12, slow=26, sig=9) -> pd.Series:
    m = _ema(close, fast) - _ema(close, slow)
    return m - m.ewm(span=sig, adjust=False).mean()

def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hi, lo, cl = df["High"], df["Low"], df["Close"]
    tr   = pd.concat([(hi - lo), (hi - cl.shift()).abs(), (lo - cl.shift()).abs()], axis=1).max(axis=1)
    dmp  = (hi - hi.shift()).clip(lower=0)
    dmm  = (lo.shift() - lo).clip(lower=0)
    both = (dmp > 0) & (dmm > 0)
    dmp  = dmp.where(~both | (dmp >= dmm), 0.0)
    dmm  = dmm.where(~both | (dmm > dmp),  0.0)
    atr_s = tr.ewm(span=period, adjust=False).mean()
    di_p  = (dmp.ewm(span=period, adjust=False).mean() / atr_s.replace(0, np.nan)) * 100
    di_m  = (dmm.ewm(span=period, adjust=False).mean() / atr_s.replace(0, np.nan)) * 100
    dx    = ((di_p - di_m).abs() / (di_p + di_m).replace(0, np.nan)) * 100
    return dx.ewm(span=period, adjust=False).mean()

def _ichimoku(df: pd.DataFrame) -> pd.DataFrame:
    hi, lo, cl = df["High"], df["Low"], df["Close"]
    t  = (hi.rolling(config.TENKAN_PERIOD).max()    + lo.rolling(config.TENKAN_PERIOD).min())    / 2
    k  = (hi.rolling(config.KIJUN_PERIOD).max()     + lo.rolling(config.KIJUN_PERIOD).min())     / 2
    sa = ((t + k) / 2).shift(config.DISPLACEMENT)
    sb = ((hi.rolling(config.SENKOU_B_PERIOD).max() + lo.rolling(config.SENKOU_B_PERIOD).min()) / 2).shift(config.DISPLACEMENT)
    # Chikou Span : close décalé en arrière de DISPLACEMENT périodes pour comparaison
    chikou = cl.shift(-config.DISPLACEMENT)
    return pd.DataFrame({"tenkan": t, "kijun": k, "sa": sa, "sb": sb, "chikou": chikou})


# ── Analyse D1 — Biais directionnel ──────────────────────────────────────────

def analyze_d1(df: pd.DataFrame) -> dict:
    """Tendance macro sur D1 via EMA 20/50/200 + structure HH/HL."""
    if len(df) < 50:
        return {"bias": "NEUTRE", "trend_strength": "FAIBLE"}

    cl   = df["Close"]
    e20  = float(_ema(cl, 20).iloc[-1])
    e50  = float(_ema(cl, 50).iloc[-1])
    e200 = float(_ema(cl, 200).iloc[-1]) if len(df) >= 200 else e50
    last = float(cl.iloc[-1])

    # Structure : Higher Highs / Higher Lows ou Lower Highs / Lower Lows
    highs = df["High"].rolling(5).max().dropna()
    lows  = df["Low"].rolling(5).min().dropna()
    hh = highs.iloc[-1] > highs.iloc[-3] if len(highs) >= 3 else False
    hl = lows.iloc[-1]  > lows.iloc[-3]  if len(lows)  >= 3 else False
    lh = highs.iloc[-1] < highs.iloc[-3] if len(highs) >= 3 else False
    ll = lows.iloc[-1]  < lows.iloc[-3]  if len(lows)  >= 3 else False

    bullish = (last > e20 > e50) and (hh and hl)
    bearish = (last < e20 < e50) and (lh and ll)

    # Force de tendance
    dist_200 = abs(last - e200) / e200 * 100
    strength = "FORT" if dist_200 > 5 else ("MODERE" if dist_200 > 2 else "FAIBLE")

    # ── Détection divergence MACD D1 ─────────────────────────────────────────
    # Bearish divergence : prix fait un nouveau sommet mais MACD fait un sommet plus bas
    # → signal d'essoufflement haussier (pénalise les signaux LONG)
    # Bullish divergence : prix fait un nouveau creux mais MACD fait un creux moins bas
    # → signal d'essoufflement baissier (pénalise les signaux SHORT)
    macd_divergence = "NONE"
    try:
        macd_h = _macd_hist(cl)
        n = min(20, len(cl) - 2)
        price_slice = cl.iloc[-n:]
        macd_slice  = macd_h.iloc[-n:]
        # Index du pic de prix dans la fenêtre récente (excluant la dernière barre)
        peak_idx  = int(price_slice.iloc[:-1].values.argmax())
        trough_idx = int(price_slice.iloc[:-1].values.argmin())
        price_at_peak   = float(price_slice.iloc[peak_idx])
        price_at_trough = float(price_slice.iloc[trough_idx])
        macd_at_peak    = float(macd_slice.iloc[peak_idx])
        macd_at_trough  = float(macd_slice.iloc[trough_idx])
        macd_last = float(macd_h.iloc[-1])
        price_last = float(cl.iloc[-1])
        # Bearish div : prix >= ancien pic ET MACD < MACD au pic ET MACD > 0
        if price_last >= price_at_peak * 0.998 and macd_last < macd_at_peak and macd_at_peak > 0:
            macd_divergence = "BEARISH"
        # Bullish div : prix <= ancien creux ET MACD > MACD au creux ET MACD < 0
        elif price_last <= price_at_trough * 1.002 and macd_last > macd_at_trough and macd_at_trough < 0:
            macd_divergence = "BULLISH"
    except Exception:
        pass  # Ne jamais bloquer l'analyse sur erreur indicateur

    return {
        "bias":             "HAUSSIER" if bullish else ("BAISSIER" if bearish else "NEUTRE"),
        "trend_strength":   strength,
        "ema20":            round(e20, 2),
        "ema50":            round(e50, 2),
        "price":            round(last, 2),
        "above_ema20":      last > e20,
        "hh_hl":            hh and hl,
        "lh_ll":            lh and ll,
        "macd_divergence":  macd_divergence,
    }


# ── Order Blocks ──────────────────────────────────────────────────────────────

def detect_order_blocks(df: pd.DataFrame, lookback: int = 20) -> list[dict]:
    """
    Order Block (ICT) : dernière bougie opposée avant un mouvement impulsif.
    Bearish OB : dernière bougie haussière avant forte baisse
    Bullish OB : dernière bougie baissière avant forte hausse
    """
    blocks = []
    if len(df) < lookback + 5:
        return blocks

    atr_val = float(_atr(df).iloc[-1])
    imp_threshold = atr_val * 1.5   # mouvement considéré impulsif

    for i in range(lookback, len(df) - 2):
        candle = df.iloc[i]
        next2  = df.iloc[i + 1: i + 4]

        bull_body = candle["Close"] > candle["Open"]
        bear_body = candle["Close"] < candle["Open"]

        # Bearish OB : bougie haussière suivie d'une forte baisse
        if bull_body:
            move_down = candle["High"] - next2["Low"].min()
            if move_down >= imp_threshold:
                blocks.append({
                    "type": "BEARISH_OB",
                    "high": round(candle["High"], 2),
                    "low":  round(candle["Low"],  2),
                    "mid":  round((candle["High"] + candle["Low"]) / 2, 2),
                    "time": df.index[i],
                })

        # Bullish OB : bougie baissière suivie d'une forte hausse
        if bear_body:
            move_up = next2["High"].max() - candle["Low"]
            if move_up >= imp_threshold:
                blocks.append({
                    "type": "BULLISH_OB",
                    "high": round(candle["High"], 2),
                    "low":  round(candle["Low"],  2),
                    "mid":  round((candle["High"] + candle["Low"]) / 2, 2),
                    "time": df.index[i],
                })

    return blocks[-6:]  # 6 OB les plus récents


def price_in_ob(price: float, blocks: list[dict], direction: str) -> dict | None:
    """Vérifie si le prix actuel est dans un Order Block pertinent."""
    ob_type = "BEARISH_OB" if direction == "SHORT" else "BULLISH_OB"
    for ob in reversed(blocks):
        if ob["type"] == ob_type:
            if ob["low"] <= price <= ob["high"]:
                return ob
    return None


# ── Fair Value Gaps (FVG / Imbalance) ────────────────────────────────────────

def detect_fvg(df: pd.DataFrame, min_size_atr: float = 0.3) -> list[dict]:
    """
    FVG (3-candle pattern) :
    Bearish FVG : High[i+2] < Low[i]  → gap baissier
    Bullish FVG : Low[i+2]  > High[i] → gap haussier
    """
    fvgs = []
    if len(df) < 5:
        return fvgs

    atr_val = float(_atr(df).iloc[-1])
    min_size = atr_val * min_size_atr

    for i in range(len(df) - 3):
        c0, c2 = df.iloc[i], df.iloc[i + 2]

        # Bearish FVG
        if c2["High"] < c0["Low"]:
            size = c0["Low"] - c2["High"]
            if size >= min_size:
                fvgs.append({
                    "type": "BEARISH_FVG",
                    "top":    round(c0["Low"],  2),
                    "bottom": round(c2["High"], 2),
                    "mid":    round((c0["Low"] + c2["High"]) / 2, 2),
                    "time":   df.index[i + 1],
                })

        # Bullish FVG
        if c2["Low"] > c0["High"]:
            size = c2["Low"] - c0["High"]
            if size >= min_size:
                fvgs.append({
                    "type": "BULLISH_FVG",
                    "top":    round(c2["Low"],  2),
                    "bottom": round(c0["High"], 2),
                    "mid":    round((c2["Low"] + c0["High"]) / 2, 2),
                    "time":   df.index[i + 1],
                })

    return fvgs[-8:]


def price_in_fvg(price: float, fvgs: list[dict], direction: str) -> dict | None:
    fvg_type = "BEARISH_FVG" if direction == "SHORT" else "BULLISH_FVG"
    for fvg in reversed(fvgs):
        if fvg["type"] == fvg_type:
            if fvg["bottom"] <= price <= fvg["top"]:
                return fvg
    return None


# ── Niveaux clés (Previous High/Low, Round Numbers) ──────────────────────────

def detect_key_levels(df_h1: pd.DataFrame, df_d1: pd.DataFrame) -> list[float]:
    """Previous Day High/Low + Weekly High/Low + Round Numbers."""
    levels = []

    if len(df_d1) >= 2:
        levels.append(float(df_d1["High"].iloc[-2]))  # Previous Day High
        levels.append(float(df_d1["Low"].iloc[-2]))   # Previous Day Low
    if len(df_d1) >= 6:
        levels.append(float(df_d1["High"].iloc[-6:-1].max()))  # Weekly High
        levels.append(float(df_d1["Low"].iloc[-6:-1].min()))   # Weekly Low

    # Round numbers (multiples de 100 proches du prix)
    price = float(df_h1["Close"].iloc[-1])
    base  = round(price / 100) * 100
    for r in range(-3, 4):
        levels.append(base + r * 100)

    return sorted(set(round(l, 2) for l in levels))


def near_key_level(price: float, levels: list[float], atr: float) -> bool:
    """Prix à moins de 0.5 ATR d'un niveau clé."""
    threshold = atr * 0.5
    return any(abs(price - lvl) <= threshold for lvl in levels)


# ══════════════════════════════════════════════════════════════════════════════
# SKILL 1 : SESSION VWAP — biais institutionnel intraday
# ══════════════════════════════════════════════════════════════════════════════

def session_vwap(df_m15: pd.DataFrame) -> dict:
    """
    VWAP de la session courante (réinitialisé à l'ouverture NY 13:30 UTC).
    - Prix > VWAP → biais acheteur institutionnel → confluence LONG
    - Prix < VWAP → biais vendeur institutionnel → confluence SHORT
    - Écart > 1 ATR → extension potentielle (risque de mean-reversion)
    """
    if df_m15 is None or len(df_m15) < 4:
        return {"vwap": None, "bias": "NEUTRE", "dist_atr": 0.0, "overextended": False}

    now_utc = datetime.now(timezone.utc)
    session_start_h = 13  # NY open 13:30 UTC
    session_start   = now_utc.replace(hour=session_start_h, minute=30, second=0, microsecond=0)
    if now_utc < session_start:
        # Avant NY — utiliser l'ouverture London 07:00
        session_start = now_utc.replace(hour=7, minute=0, second=0, microsecond=0)

    # Filtrer les bougies de la session courante
    sess = df_m15[df_m15.index >= session_start] if hasattr(df_m15.index, 'tz') else df_m15.iloc[-32:]
    if len(sess) < 2:
        sess = df_m15.iloc[-32:]

    tp   = (sess["High"] + sess["Low"] + sess["Close"]) / 3   # Typical price
    vol  = sess["Volume"].replace(0, 1)                         # Évite division par 0
    vwap = float((tp * vol).cumsum().iloc[-1] / vol.cumsum().iloc[-1])

    price   = float(sess["Close"].iloc[-1])
    atr_val = float(_atr(df_m15).iloc[-1])
    dist    = price - vwap
    dist_atr = dist / max(atr_val, 1.0)

    bias = "LONG" if price > vwap else ("SHORT" if price < vwap else "NEUTRE")
    overextended = abs(dist_atr) > 1.2   # > 1.2× ATR du VWAP = extension potentielle

    return {
        "vwap":         round(vwap, 2),
        "price":        round(price, 2),
        "dist":         round(dist, 2),
        "dist_atr":     round(dist_atr, 2),
        "bias":         bias,
        "overextended": overextended,
    }


# ══════════════════════════════════════════════════════════════════════════════
# SKILL 2 : BOS / CHoCH — Break of Structure / Change of Character (ICT)
# ══════════════════════════════════════════════════════════════════════════════

def detect_bos_choch(df_h1: pd.DataFrame, lookback: int = 20) -> dict:
    """
    Break of Structure (BOS) : confirmation de continuation de tendance.
      - BULLISH BOS : nouveau Higher High (cassure du dernier swing high)
      - BEARISH BOS : nouveau Lower Low (cassure du dernier swing low)

    Change of Character (CHoCH) : premier signal d'inversion.
      - BULLISH CHoCH : cassure du dernier Lower High en downtrend
      - BEARISH CHoCH : cassure du dernier Higher Low en uptrend

    Retourne: bos_type, choch_type, dernier swing high/low, niveau cassé.
    """
    if df_h1 is None or len(df_h1) < lookback + 5:
        return {"bos": "NONE", "choch": "NONE", "swing_high": None, "swing_low": None}

    hi = df_h1["High"]
    lo = df_h1["Low"]
    cl = df_h1["Close"]

    # Identifier les swing highs et lows (local max/min sur 3 barres)
    swing_highs, swing_lows = [], []
    for i in range(2, len(df_h1) - 1):
        if hi.iloc[i] > hi.iloc[i-1] and hi.iloc[i] > hi.iloc[i+1]:
            swing_highs.append((i, float(hi.iloc[i])))
        if lo.iloc[i] < lo.iloc[i-1] and lo.iloc[i] < lo.iloc[i+1]:
            swing_lows.append((i, float(lo.iloc[i])))

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return {"bos": "NONE", "choch": "NONE", "swing_high": None, "swing_low": None}

    last_sh = swing_highs[-1][1]   # Dernier swing high
    prev_sh = swing_highs[-2][1]   # Avant-dernier swing high
    last_sl = swing_lows[-1][1]    # Dernier swing low
    prev_sl = swing_lows[-2][1]    # Avant-dernier swing low
    price   = float(cl.iloc[-2])

    bos   = "NONE"
    choch = "NONE"

    # BOS haussier : prix casse le dernier swing high (continuation up)
    if price > last_sh and last_sh > prev_sh:
        bos = "BULLISH"

    # BOS baissier : prix casse le dernier swing low (continuation down)
    elif price < last_sl and last_sl < prev_sl:
        bos = "BEARISH"

    # CHoCH haussier : downtrend (LH/LL) mais price casse le dernier LH
    elif last_sh < prev_sh and price > last_sh:
        choch = "BULLISH"

    # CHoCH baissier : uptrend (HH/HL) mais price casse le dernier HL
    elif last_sl > prev_sl and price < last_sl:
        choch = "BEARISH"

    return {
        "bos":        bos,
        "choch":      choch,
        "swing_high": round(last_sh, 2),
        "swing_low":  round(last_sl, 2),
        "prev_sh":    round(prev_sh, 2),
        "prev_sl":    round(prev_sl, 2),
    }


# ══════════════════════════════════════════════════════════════════════════════
# SKILL 3 : LIQUIDITY SWEEP — détection de stop-hunts institutionnels
# ══════════════════════════════════════════════════════════════════════════════

def detect_liquidity_sweep(df_h1: pd.DataFrame, atr: float) -> dict:
    """
    Liquidity Sweep (stop-hunt) : cassure temporaire d'un niveau clé
    suivie d'un retour rapide dans le range.

    Bullish sweep : pique sous un swing low récent puis remonte aussitôt
    → les institutions ont absorbé les ventes des retail longs stoppés.
    → signal d'achat haute probabilité.

    Bearish sweep : pique au-dessus d'un swing high récent puis descend
    → institutions ont absorbé les achats des retail shorts stoppés.
    → signal de vente haute probabilité.
    """
    if df_h1 is None or len(df_h1) < 10:
        return {"sweep": "NONE", "swept_level": None, "confirmation": False}

    hi = df_h1["High"]
    lo = df_h1["Low"]
    cl = df_h1["Close"]
    op = df_h1["Open"]

    # Swing highs/lows des 10 dernières bougies (excluant les 2 dernières)
    window = df_h1.iloc[-12:-2]
    ref_high = float(window["High"].max())
    ref_low  = float(window["Low"].min())

    last_hi = float(hi.iloc[-2])
    last_lo = float(lo.iloc[-2])
    last_cl = float(cl.iloc[-2])
    last_op = float(op.iloc[-2])

    threshold = atr * 0.25   # Pénétration minimale pour valider le sweep

    # Bullish sweep : bougie qui perce sous ref_low puis clôture AU-DESSUS
    bullish_sweep = (
        last_lo < ref_low - threshold   # Pique sous le niveau
        and last_cl > ref_low            # Clôture au-dessus (rejet)
        and last_cl > last_op            # Bougie haussière (clôture > ouverture)
    )

    # Bearish sweep : bougie qui perce au-dessus ref_high puis clôture EN-DESSOUS
    bearish_sweep = (
        last_hi > ref_high + threshold
        and last_cl < ref_high
        and last_cl < last_op
    )

    if bullish_sweep:
        return {"sweep": "BULLISH", "swept_level": round(ref_low, 2), "confirmation": True}
    if bearish_sweep:
        return {"sweep": "BEARISH", "swept_level": round(ref_high, 2), "confirmation": True}

    return {"sweep": "NONE", "swept_level": None, "confirmation": False}


# ══════════════════════════════════════════════════════════════════════════════
# SKILL 4 : DISPLACEMENT CANDLES — flow institutionnel impulsif
# ══════════════════════════════════════════════════════════════════════════════

def detect_displacement(df_h1: pd.DataFrame, atr: float) -> dict:
    """
    Displacement : bougie avec corps ≥ 1.5× ATR moyen ET clôture aux 75%+ de range.
    Indique un flux institutionnel fort — confirme la direction du prochain mouvement.

    Bullish displacement : grande bougie haussière récente → bias LONG
    Bearish displacement : grande bougie baissière récente → bias SHORT
    """
    if df_h1 is None or len(df_h1) < 5 or atr <= 0:
        return {"displacement": "NONE", "strength": 0.0}

    # Analyser les 3 dernières bougies fermées
    recent = df_h1.iloc[-5:-1]
    avg_range = float((recent["High"] - recent["Low"]).mean())
    threshold = max(atr * 1.3, avg_range * 1.5)

    best_disp = "NONE"
    best_strength = 0.0

    for _, row in recent.iloc[-3:].iterrows():
        body   = abs(row["Close"] - row["Open"])
        rng    = row["High"] - row["Low"]
        if rng < 0.001: continue
        close_pct = (row["Close"] - row["Low"]) / rng   # Position clôture dans le range

        if body >= threshold and close_pct >= 0.75:
            # Bullish displacement
            strength = body / atr
            if strength > best_strength:
                best_disp = "BULLISH"
                best_strength = strength

        elif body >= threshold and close_pct <= 0.25:
            # Bearish displacement
            strength = body / atr
            if strength > best_strength:
                best_disp = "BEARISH"
                best_strength = strength

    return {
        "displacement": best_disp,
        "strength":     round(best_strength, 2),
    }


# ══════════════════════════════════════════════════════════════════════════════
# SKILL 5 : VOLATILITY REGIME — filtre ATR percentile
# ══════════════════════════════════════════════════════════════════════════════

def volatility_regime(df_h1: pd.DataFrame) -> dict:
    """
    Classe le régime de volatilité actuel par rapport aux 20 derniers jours.
    - LOW  (< 25e percentile) : range mort, signaux peu fiables
    - NORMAL (25-75e) : conditions idéales pour trader
    - HIGH (> 75e percentile) : volatilité élevée, SL plus larges requis
    - EXTREME (> 90e) : éviter les nouveaux trades

    Impact :
    - LOW : réduction du volume de 50% (signaux peu fiables)
    - NORMAL : volume normal
    - HIGH : réduction du volume de 25%
    - EXTREME : blocage total des nouvelles entrées
    """
    if df_h1 is None or len(df_h1) < 30:
        return {"regime": "NORMAL", "atr_pct": 50.0, "vol_factor": 1.0}

    atr_series = _atr(df_h1).dropna()
    if len(atr_series) < 10:
        return {"regime": "NORMAL", "atr_pct": 50.0, "vol_factor": 1.0}

    current_atr = float(atr_series.iloc[-1])
    hist_atrs   = atr_series.iloc[-480:]   # ~20 jours de bougies H1 (20×24)

    pct = float((hist_atrs < current_atr).mean() * 100)

    if pct >= 90:
        regime, factor = "EXTREME", 0.0    # Bloquer
    elif pct >= 75:
        regime, factor = "HIGH",    0.75   # Réduire volume
    elif pct >= 25:
        regime, factor = "NORMAL",  1.0    # Conditions idéales
    else:
        regime, factor = "LOW",     0.5    # Réduire volume — range mort

    return {
        "regime":     regime,
        "atr_pct":    round(pct, 1),
        "atr_val":    round(current_atr, 1),
        "vol_factor": factor,
    }


# ══════════════════════════════════════════════════════════════════════════════
# SKILL 6 : EQUAL HIGHS / LOWS — pools de liquidité
# ══════════════════════════════════════════════════════════════════════════════

def detect_equal_highs_lows(df_h1: pd.DataFrame, atr: float, lookback: int = 30) -> dict:
    """
    Equal Highs (EQH) : 2+ swing highs au même niveau (±0.1% ATR).
    Equal Lows  (EQL) : 2+ swing lows au même niveau.

    Ces niveaux concentrent des stops retail → cibles institutionnelles.
    - Prix proche d'un EQH → SHORT potentiel (sweep de liquidité imminent)
    - Prix proche d'un EQL → LONG potentiel (support liquide fort)
    """
    if df_h1 is None or len(df_h1) < lookback or atr <= 0:
        return {"eqh": [], "eql": [], "near_eqh": False, "near_eql": False}

    hi = df_h1["High"].iloc[-lookback:]
    lo = df_h1["Low"].iloc[-lookback:]
    cl = float(df_h1["Close"].iloc[-2])

    tolerance = atr * 0.12   # Niveaux à ±0.12 ATR = "égaux"

    # Swing highs
    s_highs = [float(hi.iloc[i]) for i in range(1, len(hi)-1)
               if hi.iloc[i] > hi.iloc[i-1] and hi.iloc[i] > hi.iloc[i+1]]
    # Swing lows
    s_lows  = [float(lo.iloc[i]) for i in range(1, len(lo)-1)
               if lo.iloc[i] < lo.iloc[i-1] and lo.iloc[i] < lo.iloc[i+1]]

    def cluster(levels: list[float]) -> list[float]:
        """Regroupe les niveaux proches en un seul niveau moyen."""
        clusters = []
        for lvl in sorted(levels):
            merged = False
            for i, c in enumerate(clusters):
                if abs(lvl - c) <= tolerance:
                    clusters[i] = (c + lvl) / 2
                    merged = True
                    break
            if not merged:
                clusters.append(lvl)
        return [c for c in clusters if sum(1 for l in levels if abs(l - c) <= tolerance) >= 2]

    eqh = [round(c, 2) for c in cluster(s_highs)]
    eql = [round(c, 2) for c in cluster(s_lows)]

    near_eqh = any(abs(cl - h) <= atr * 0.3 for h in eqh)
    near_eql  = any(abs(cl - l) <= atr * 0.3 for l in eql)

    return {
        "eqh":      eqh[-3:],   # 3 niveaux les plus récents
        "eql":      eql[-3:],
        "near_eqh": near_eqh,
        "near_eql": near_eql,
    }


# ── Kill Zone ─────────────────────────────────────────────────────────────────

def current_kill_zone() -> str:
    """Retourne le nom de la kill zone active, ou '' si hors zone."""
    now_utc = datetime.now(timezone.utc)
    minutes  = now_utc.hour * 60 + now_utc.minute
    weekday  = now_utc.weekday()

    if weekday >= 5:  # Weekend
        return ""

    for name, (start, end) in KILL_ZONES.items():
        if name == "NY_CLOSE":
            continue  # Clôture NY — on évite les nouveaux trades
        if start <= minutes <= end:
            return name

    return ""


# ── Analyse H4 — Structure de marché ─────────────────────────────────────────

def analyze_h4(df: pd.DataFrame) -> dict:
    """
    Structure de marché H4 via Ichimoku + EMA 20/50 + MACD.
    Retourne: bias (HAUSSIER|BAISSIER|NEUTRE), swing high/low, alignement.
    """
    if df is None or len(df) < 55:
        return {"bias": "NEUTRE", "aligned": False, "signal": "SKIP", "macd_h": 0.0, "adx": 0.0}

    cl   = df["Close"]
    hi   = df["High"]
    lo   = df["Low"]
    idx  = -2  # dernière bougie fermée

    e20  = float(_ema(cl, 20).iloc[idx])
    e50  = float(_ema(cl, 50).iloc[idx])
    last = float(cl.iloc[idx])
    macd_h = float(_macd_hist(cl).iloc[idx])
    adx_v  = float(_adx(df).iloc[idx])

    # Ichimoku H4
    ichi = _ichimoku(df)
    t    = float(ichi["tenkan"].iloc[idx])
    k    = float(ichi["kijun"].iloc[idx])
    sa_raw = ((ichi["tenkan"] + ichi["kijun"]) / 2).iloc[idx]
    sb_raw = ((hi.rolling(config.SENKOU_B_PERIOD).max() + lo.rolling(config.SENKOU_B_PERIOD).min()) / 2).iloc[idx]
    sa   = float(sa_raw)
    sb   = float(sb_raw)
    kumo_top = max(sa, sb)
    kumo_bot = min(sa, sb)
    in_kumo  = kumo_bot <= last <= kumo_top

    # Structure swing (Higher High / Higher Low)
    highs = hi.rolling(5).max().dropna()
    lows  = lo.rolling(5).min().dropna()
    hh = len(highs) >= 3 and highs.iloc[-1] > highs.iloc[-3]
    hl = len(lows)  >= 3 and lows.iloc[-1]  > lows.iloc[-3]
    lh = len(highs) >= 3 and highs.iloc[-1] < highs.iloc[-3]
    ll = len(lows)  >= 3 and lows.iloc[-1]  < lows.iloc[-3]

    bullish = not in_kumo and last > kumo_top and last > e20 and t > k and macd_h > 0 and (hh and hl)
    bearish = not in_kumo and last < kumo_bot and last < e20 and t < k and macd_h < 0 and (lh and ll)

    bias = "HAUSSIER" if bullish else ("BAISSIER" if bearish else "NEUTRE")

    return {
        "bias":     bias,
        "signal":   "LONG" if bullish else ("SHORT" if bearish else "SKIP"),
        "aligned":  bullish or bearish,
        "last":     round(last, 2),
        "e20":      round(e20, 2),
        "e50":      round(e50, 2),
        "kumo_top": round(kumo_top, 2),
        "kumo_bot": round(kumo_bot, 2),
        "macd_h":   round(macd_h, 2),
        "adx":      round(adx_v, 1),
        "hh_hl":    hh and hl,
        "lh_ll":    lh and ll,
    }


# ── Analyse H1 — Signal de base ───────────────────────────────────────────────

def analyze_h1(df: pd.DataFrame) -> dict:
    """Ichimoku + RSI + MACD + ADX sur H1."""
    ichi = _ichimoku(df)
    rsi  = _rsi(df["Close"])
    hist = _macd_hist(df["Close"])
    adx  = _adx(df)
    atr  = _atr(df)

    idx = -2  # Dernière bougie fermée
    cl   = float(df["Close"].iloc[idx])
    t    = float(ichi["tenkan"].iloc[idx])
    k    = float(ichi["kijun"].iloc[idx])
    # Kumo courant = SA/SB NON décalés (le shift(26) est pour l'affichage chart, pas pour les signaux)
    sa   = float(((ichi["tenkan"] + ichi["kijun"]) / 2).iloc[idx])
    sb_raw = ((df["High"].rolling(config.SENKOU_B_PERIOD).max() + df["Low"].rolling(config.SENKOU_B_PERIOD).min()) / 2)
    sb   = float(sb_raw.iloc[idx])
    r    = float(rsi.iloc[idx])
    h    = float(hist.iloc[idx])
    a    = float(adx.iloc[idx])
    atr_v = float(atr.iloc[-1])

    kumo_top = max(sa, sb)
    kumo_bot = min(sa, sb)
    in_kumo  = kumo_bot <= cl <= kumo_top

    # Chikou Span — close actuel vs prix 26 barres en arrière (confirmation institutionnelle)
    # LONG  : Chikou > prix H-26 (momentum haussier confirmé dans le passé)
    # SHORT : Chikou < prix H-26 (momentum baissier confirmé dans le passé)
    disp = config.DISPLACEMENT  # 26
    chikou_ref_idx = idx - disp  # idx=-2, donc -28 depuis la fin
    if len(df) >= abs(chikou_ref_idx):
        chikou_ref_price = float(df["Close"].iloc[chikou_ref_idx])
        chikou_bullish = cl > chikou_ref_price
        chikou_bearish = cl < chikou_ref_price
    else:
        chikou_ref_price = cl
        chikou_bullish = chikou_bearish = False

    # Cloud twist — direction du nuage (SA vs SB non décalés = future cloud)
    # SA > SB → twist haussier (nuage futur bullish)  → confluence LONG
    # SA < SB → twist baissier (nuage futur bearish)  → confluence SHORT
    cloud_bullish_twist = sa > sb
    cloud_bearish_twist = sa < sb

    # Signal primaire : toutes conditions Ichimoku réunies
    short_primary = (not in_kumo and cl < kumo_bot and t < k
                     and cl < t and r <= config.RSI_MAX and h < 0 and a >= config.ADX_MIN)
    long_primary  = (not in_kumo and cl > kumo_top and t > k
                     and cl > t and r >= config.RSI_MIN and h > 0 and a >= config.ADX_MIN)

    # Signal pullback : entrée sur retracement vers le Tenkan (setup institutionnel)
    # SHORT pullback : prix sous kumo + T<K + pullback vers/au-dessus Tenkan + RSI pas survendu
    short_pullback = (not in_kumo and cl < kumo_bot and t < k
                      and cl >= t and cl <= (t + (kumo_bot - t) * 0.5)
                      and r <= 60 and h < 0 and a >= 18)
    long_pullback  = (not in_kumo and cl > kumo_top and t > k
                      and cl <= t and cl >= (t - (t - kumo_top) * 0.5)
                      and r >= 40 and h > 0 and a >= 18)

    short_ok = short_primary or short_pullback
    long_ok  = long_primary  or long_pullback

    # Diagnostic : identifier pourquoi le signal est SKIP
    skip_reasons = []
    if in_kumo:
        skip_reasons.append(f"DANS KUMO ({kumo_bot:.0f}–{kumo_top:.0f})")
    elif cl < kumo_bot:
        # Contexte baissier — SHORT potentiel
        if not (t < k):  skip_reasons.append(f"TK haussier (T{t:.0f}>K{k:.0f}) — pas SHORT")
        if not (h < 0):  skip_reasons.append(f"MACD haussier ({h:.1f}) — momentum contre SHORT")
        if a < 18:       skip_reasons.append(f"ADX très faible ({a:.1f}<18) — range")
        elif a < config.ADX_MIN:
            skip_reasons.append(f"ADX limite ({a:.1f}<{config.ADX_MIN}) — tendance faible")
        if r > 65:       skip_reasons.append(f"RSI surachat ({r:.0f}) — pas SHORT")
    elif cl > kumo_top:
        # Contexte haussier — LONG potentiel
        if not (t > k):  skip_reasons.append(f"TK baissier (T{t:.0f}<K{k:.0f}) — pas LONG")
        if not (h > 0):  skip_reasons.append(f"MACD baissier ({h:.1f}) — momentum contre LONG")
        if a < 18:       skip_reasons.append(f"ADX très faible ({a:.1f}<18) — range")
        if r < 35:       skip_reasons.append(f"RSI survente ({r:.0f}) — pas LONG")
    else:
        skip_reasons.append(f"Prix entre kumo_bot {kumo_bot:.0f} et kumo_top {kumo_top:.0f}")

    return {
        "signal":       "SHORT" if short_ok else ("LONG" if long_ok else "SKIP"),
        "skip_reasons": skip_reasons[:3],
        "close":    cl,
        "tenkan":   round(t, 2),
        "kijun":    round(k, 2),
        "kumo_top": round(kumo_top, 2),
        "kumo_bot": round(kumo_bot, 2),
        "rsi":      round(r, 1),
        "macd_h":   round(h, 2),
        "adx":      round(a, 1),
        "atr":      round(atr_v, 1),
        "in_kumo":  in_kumo,
        # Chikou Span
        "chikou_bullish":    chikou_bullish,
        "chikou_bearish":    chikou_bearish,
        "chikou_ref_price":  round(chikou_ref_price, 2),
        # Cloud twist
        "cloud_bullish_twist": cloud_bullish_twist,
        "cloud_bearish_twist": cloud_bearish_twist,
    }


# ── Moteur de scoring — A+ / A / B ───────────────────────────────────────────

def score_setup(
    direction: str,
    d1: dict,
    h1: dict,
    ob_hit: bool,
    fvg_hit: bool,
    key_level: bool,
    kill_zone: str,
    h4_aligned: bool,
    # Nouveaux skills institutionnels
    vwap: dict | None = None,
    bos_choch: dict | None = None,
    sweep: dict | None = None,
    displacement: dict | None = None,
    vol_regime: dict | None = None,
    eq_hl: dict | None = None,
) -> tuple[int, list[str], list[str]]:
    """
    Attribue un score de confluence. Chaque confluence = +1 point.
    Retourne (score, confluences_validées, avertissements).
    """
    confluences = []
    warnings    = []

    # ── Confluences positives ─────────────────────────────────────────────────

    # 1. Biais D1 aligné
    if direction == "SHORT" and d1["bias"] == "BAISSIER":
        confluences.append("D1 Baissier aligne")
    elif direction == "LONG" and d1["bias"] == "HAUSSIER":
        confluences.append("D1 Haussier aligne")
    elif d1["bias"] == "NEUTRE":
        warnings.append("D1 neutre — biais non confirme")

    # 2. H4 structure alignée
    if h4_aligned:
        confluences.append("H4 structure alignee")

    # 3. Ichimoku H1 complet
    if h1["signal"] == direction:
        confluences.append("Ichimoku H1 confirme")

    # 4. RSI en zone optimale
    rsi = h1["rsi"]
    if direction == "SHORT" and 50 <= rsi <= 68:
        confluences.append(f"RSI optimal SHORT ({rsi})")
    elif direction == "LONG" and 32 <= rsi <= 50:
        confluences.append(f"RSI optimal LONG ({rsi})")
    elif direction == "SHORT" and rsi <= 50:
        warnings.append(f"RSI trop bas pour SHORT ({rsi}) — possible survente")
    elif direction == "LONG" and rsi >= 50:
        warnings.append(f"RSI trop haut pour LONG ({rsi}) — possible surachat")

    # 5. MACD confirme
    if direction == "SHORT" and h1["macd_h"] < 0:
        confluences.append("MACD baissier")
    elif direction == "LONG" and h1["macd_h"] > 0:
        confluences.append("MACD haussier")

    # 6. ADX tendance forte
    if h1["adx"] >= 25:
        confluences.append(f"ADX fort ({h1['adx']})")
    elif h1["adx"] >= config.ADX_MIN:
        confluences.append(f"ADX acceptable ({h1['adx']})")

    # 7. Order Block institutionnel
    if ob_hit:
        confluences.append("Prix dans Order Block institutionnel")

    # 8. Fair Value Gap (imbalance)
    if fvg_hit:
        confluences.append("Fair Value Gap present")

    # 9. Niveau clé (PDH/PDL/Weekly)
    if key_level:
        confluences.append("Niveau cle (PDH/PDL/Weekly)")

    # 10. Kill Zone active
    if kill_zone:
        confluences.append(f"Kill Zone active ({kill_zone})")
    else:
        warnings.append("Hors Kill Zone — liquidite reduite")

    # 11. D1 tendance forte
    if d1["trend_strength"] == "FORT":
        confluences.append("Tendance D1 forte")

    # ── Skills institutionnels ────────────────────────────────────────────────

    # 12. Session VWAP — biais intraday institutionnel
    if vwap and vwap.get("vwap"):
        if direction == "LONG" and vwap["bias"] == "LONG":
            confluences.append(f"VWAP haussier (prix={vwap['price']:.0f} > VWAP={vwap['vwap']:.0f})")
        elif direction == "SHORT" and vwap["bias"] == "SHORT":
            confluences.append(f"VWAP baissier (prix={vwap['price']:.0f} < VWAP={vwap['vwap']:.0f})")
        elif vwap.get("overextended"):
            warnings.append(f"Extension VWAP excessive ({vwap['dist_atr']:+.1f}×ATR) — mean-reversion risque")

    # 13. BOS / CHoCH (ICT structure)
    if bos_choch:
        if direction == "LONG" and bos_choch["bos"] == "BULLISH":
            confluences.append(f"BOS Haussier confirmé (swing_high={bos_choch['swing_high']:.0f})")
        elif direction == "LONG" and bos_choch["choch"] == "BULLISH":
            confluences.append(f"CHoCH Haussier — inversion confirmée")
        elif direction == "SHORT" and bos_choch["bos"] == "BEARISH":
            confluences.append(f"BOS Baissier confirmé (swing_low={bos_choch['swing_low']:.0f})")
        elif direction == "SHORT" and bos_choch["choch"] == "BEARISH":
            confluences.append(f"CHoCH Baissier — inversion confirmée")

    # 14. Liquidity Sweep — stop-hunt institutionnel
    if sweep and sweep["confirmation"]:
        if direction == "LONG" and sweep["sweep"] == "BULLISH":
            confluences.append(f"Liquidity Sweep Haussier @ {sweep['swept_level']:.0f} — stop-hunt absorbé")
        elif direction == "SHORT" and sweep["sweep"] == "BEARISH":
            confluences.append(f"Liquidity Sweep Baissier @ {sweep['swept_level']:.0f} — stop-hunt absorbé")

    # 15. Displacement candle — flow institutionnel confirmé
    if displacement and displacement["displacement"] != "NONE":
        if direction == "LONG" and displacement["displacement"] == "BULLISH":
            confluences.append(f"Displacement haussier (force={displacement['strength']:.1f}×ATR)")
        elif direction == "SHORT" and displacement["displacement"] == "BEARISH":
            confluences.append(f"Displacement baissier (force={displacement['strength']:.1f}×ATR)")

    # 16. Equal Highs / Lows — pool de liquidité
    if eq_hl:
        if direction == "LONG" and eq_hl["near_eql"]:
            confluences.append(f"Equal Lows @ support ({eq_hl['eql']}) — liquidité institutionnelle")
        elif direction == "SHORT" and eq_hl["near_eqh"]:
            confluences.append(f"Equal Highs @ résistance ({eq_hl['eqh']}) — liquidité institutionnelle")

    # 18. Chikou Span (confirmation institutionnelle Ichimoku)
    if direction == "LONG" and h1.get("chikou_bullish"):
        confluences.append(f"Chikou Span haussier (> prix H-26)")
    elif direction == "SHORT" and h1.get("chikou_bearish"):
        confluences.append(f"Chikou Span baissier (< prix H-26)")
    else:
        warnings.append("Chikou Span non confirme — signal affaibli")

    # 19. Cloud twist — direction du nuage futur (SA vs SB)
    if direction == "LONG" and h1.get("cloud_bullish_twist"):
        confluences.append("Cloud twist haussier (SA > SB)")
    elif direction == "SHORT" and h1.get("cloud_bearish_twist"):
        confluences.append("Cloud twist baissier (SA < SB)")

    # 20. MACD divergence D1 — pénalité si divergence contre la direction
    d1_divergence = d1.get("macd_divergence", "NONE")
    if direction == "LONG" and d1_divergence == "BEARISH":
        warnings.append("MACD divergence baissiere D1 — conviction -2")
    elif direction == "SHORT" and d1_divergence == "BULLISH":
        warnings.append("MACD divergence haussiere D1 — conviction -2")

    # ── Déductions ────────────────────────────────────────────────────────────
    score = len(confluences)

    # Pénalité si D1 contredit
    if direction == "SHORT" and d1["bias"] == "HAUSSIER":
        score -= 2
        warnings.append("ATTENTION: CONTRE-TENDANCE D1 — risque eleve")
    if direction == "LONG" and d1["bias"] == "BAISSIER":
        score -= 2
        warnings.append("ATTENTION: CONTRE-TENDANCE D1 — risque eleve")

    # Pénalité MACD divergence D1
    d1_divergence = d1.get("macd_divergence", "NONE")
    if direction == "LONG" and d1_divergence == "BEARISH":
        score -= 2
    elif direction == "SHORT" and d1_divergence == "BULLISH":
        score -= 2

    return max(0, score), confluences, warnings


# ── Point d'entrée principal ──────────────────────────────────────────────────

def generate_pro_signal(mtf: dict[str, pd.DataFrame]) -> ProSignal:
    """
    Génère un signal professionnel multi-timeframe avec scoring de confluences.
    Retourne un ProSignal avec grade A+/A/B/SKIP.
    """
    df_d1  = mtf.get("D1",  pd.DataFrame())
    df_h4  = mtf.get("H4",  pd.DataFrame())
    df_h1  = mtf.get("H1",  pd.DataFrame())
    df_m15 = mtf.get("M15", pd.DataFrame())
    df_m5  = mtf.get("M5",  pd.DataFrame())

    sig = ProSignal()

    if df_h1.empty or len(df_h1) < 60:
        sig.direction = "SKIP"
        sig.warnings.append("Donnees H1 insuffisantes")
        return sig

    # ── Analyse par timeframe ─────────────────────────────────────────────────
    d1   = analyze_d1(df_d1)   if not df_d1.empty else {"bias": "NEUTRE", "trend_strength": "FAIBLE"}
    h1   = analyze_h1(df_h1)
    direction = h1["signal"]

    sig.d1_bias      = d1["bias"]
    sig.h1_signal    = direction
    sig.atr          = h1["atr"]
    sig.skip_reasons = h1.get("skip_reasons", [])
    sig.kill_zone    = current_kill_zone()   # toujours set, même sur SKIP

    if direction == "SKIP":
        # Fallback M15 : si H1 est en range (Kumo), utiliser M15 comme signal alternatif
        # REGLE ABSOLUE : le M15 fallback doit etre ALIGNE avec le biais D1 et H4.
        # Entrer contre la tendance dominante est la cause #1 de pertes consecutives.
        if df_m15 is not None and not df_m15.empty:
            m15 = analyze_m15(df_m15)
            if m15["signal"] != "SKIP":
                m15_dir   = m15["signal"]
                d1_bias   = d1.get("bias", "NEUTRE")

                # Verifier l'alignement H4 pour le fallback
                h4_bias = "NEUTRE"
                if not df_h4.empty and len(df_h4) >= 20:
                    h4_cl   = df_h4["Close"]
                    h4_ichi = _ichimoku(df_h4)
                    h4_last = float(h4_cl.iloc[-2])
                    h4_sa   = float(((h4_ichi["tenkan"] + h4_ichi["kijun"]) / 2).iloc[-2])
                    h4_sb   = float(((df_h4["High"].rolling(52).max() + df_h4["Low"].rolling(52).min()) / 2).iloc[-2])
                    h4_top  = max(h4_sa, h4_sb)
                    h4_bot  = min(h4_sa, h4_sb)
                    if h4_last > h4_top:
                        h4_bias = "LONG"
                    elif h4_last < h4_bot:
                        h4_bias = "SHORT"

                # Bloquer si M15 va contre D1 OU contre H4 (tous deux doivent etre alignes ou neutres)
                d1_blocks  = (d1_bias != "NEUTRE" and d1_bias != m15_dir)
                h4_blocks  = (h4_bias != "NEUTRE" and h4_bias != m15_dir)

                if d1_blocks:
                    log.warning(
                        f"  [M15 FALLBACK] BLOQUE — {m15_dir} contre tendance D1 {d1_bias} "
                        f"(ADX={m15['adx']:.0f}) — contre-tendance interdite"
                    )
                    # Ne pas return : laisser le chemin M5 scalp tenter sa chance
                elif h4_blocks:
                    log.warning(
                        f"  [M15 FALLBACK] BLOQUE — {m15_dir} contre structure H4 {h4_bias} "
                        f"(ADX={m15['adx']:.0f}) — alignement requis"
                    )
                    # Ne pas return : laisser le chemin M5 scalp tenter sa chance
                else:
                    # M15 aligne avec D1 et H4 — signal valide
                    direction        = m15_dir
                    sig.direction    = direction
                    sig.h1_signal    = f"M15-{direction}"
                    sig.skip_reasons = []
                    sig.atr          = float(_atr(df_h1).iloc[-1])
                    sig.kill_zone    = current_kill_zone()
                    sig.confluences.append(f"M15 {direction} (ADX={m15['adx']:.0f}, MACD={m15['macd']:.1f})")
                    if d1_bias == direction:
                        sig.confluences.append(f"D1 biais {d1_bias} confirme")
                    if h4_bias == direction:
                        sig.confluences.append(f"H4 structure {h4_bias} alignee")
                    sig.grade = "B"
                    price = m15["close"]
                    atr_h = sig.atr
                    if direction == "LONG":
                        sig.entry = price
                        sig.sl    = round(price - atr_h * 1.0, 2)
                        sig.tp1   = round(price + atr_h * 1.0, 2)
                        sig.tp2   = round(price + atr_h * 2.0, 2)
                        sig.tp3   = round(price + atr_h * 3.0, 2)
                    else:
                        sig.entry = price
                        sig.sl    = round(price + atr_h * 1.0, 2)
                        sig.tp1   = round(price - atr_h * 1.0, 2)
                        sig.tp2   = round(price - atr_h * 2.0, 2)
                        sig.tp3   = round(price - atr_h * 3.0, 2)
                    log.info(
                        f"  [M15 FALLBACK] {direction} valide — D1:{d1_bias} H4:{h4_bias} "
                        f"ADX={m15['adx']:.0f} MACD={m15['macd']:.1f}"
                    )
                    return sig

        # ── Chemin scalp M5 (HFT) ─────────────────────────────────────────────
        # Activé si : SCALP_MODE=True ET M15 fallback a échoué ET M5 disponible
        if config.SCALP_MODE and df_m5 is not None and not df_m5.empty:
            m5 = analyze_m5(df_m5)
            if m5["signal"] != "SKIP":
                m5_dir = m5["signal"]
                d1_bias = d1.get("bias", "NEUTRE")

                # Filtre directionnel minimal : M5 ne doit pas contredire D1 fort
                d1_blocks = (d1_bias != "NEUTRE" and d1_bias != m5_dir)
                if d1_blocks:
                    log.warning(
                        f"  [M5 SCALP] BLOQUE — {m5_dir} contre D1 {d1_bias}"
                    )
                else:
                    # H4 optionnel : si H4 est défini, préférer l'alignement
                    h4_bias = "NEUTRE"
                    if not df_h4.empty and len(df_h4) >= 20:
                        h4_cl  = df_h4["Close"]
                        h4_ichi = _ichimoku(df_h4)
                        h4_last = float(h4_cl.iloc[-2])
                        h4_sa   = float(((h4_ichi["tenkan"] + h4_ichi["kijun"]) / 2).iloc[-2])
                        h4_sb   = float(((df_h4["High"].rolling(52).max() + df_h4["Low"].rolling(52).min()) / 2).iloc[-2])
                        h4_top  = max(h4_sa, h4_sb)
                        h4_bot  = min(h4_sa, h4_sb)
                        if h4_last > h4_top:
                            h4_bias = "LONG"
                        elif h4_last < h4_bot:
                            h4_bias = "SHORT"

                    h4_blocks = (h4_bias != "NEUTRE" and h4_bias != m5_dir)
                    if h4_blocks:
                        log.warning(
                            f"  [M5 SCALP] BLOQUE — {m5_dir} contre H4 {h4_bias}"
                        )
                    else:
                        # Signal M5 scalp validé
                        atr_m5 = m5["atr"]
                        price  = m5["close"]
                        if m5_dir == "LONG":
                            entry = price
                            sl    = round(entry - atr_m5 * config.SCALP_ATR_SL_MULT, 2)
                            tp1   = round(entry + atr_m5 * config.SCALP_ATR_TP1_MULT, 2)
                            tp2   = round(entry + atr_m5 * config.SCALP_ATR_TP2_MULT, 2)
                        else:
                            entry = price
                            sl    = round(entry + atr_m5 * config.SCALP_ATR_SL_MULT, 2)
                            tp1   = round(entry - atr_m5 * config.SCALP_ATR_TP1_MULT, 2)
                            tp2   = round(entry - atr_m5 * config.SCALP_ATR_TP2_MULT, 2)

                        risk   = abs(sl - entry)
                        reward = abs(tp2 - entry)
                        rr_val = reward / max(risk, 0.01)

                        if rr_val >= config.SCALP_MIN_RR:
                            sig.direction   = m5_dir
                            sig.h1_signal   = f"M5-SCALP-{m5_dir}"
                            sig.grade       = "B"
                            sig.entry       = entry
                            sig.sl          = sl
                            sig.tp1         = tp1
                            sig.tp2         = tp2
                            sig.tp3         = round(entry + atr_m5 * config.SCALP_ATR_TP2_MULT * 1.5 * (1 if m5_dir == "LONG" else -1), 2)
                            sig.atr         = atr_m5
                            sig.rr          = f"1:{round(rr_val, 1)}"
                            sig.kill_zone   = current_kill_zone()
                            sig.skip_reasons = []
                            sig.confluences.append(
                                f"M5 SCALP {m5_dir} — EMA5/13 + MACD={m5['macd']:+.3f} "
                                f"ADX={m5['adx']:.0f} RSI={m5['rsi']:.0f} "
                                f"({m5['bull_n'] if m5_dir=='LONG' else m5['bear_n']}/5 bougies)"
                            )
                            if d1_bias == m5_dir:
                                sig.confluences.append(f"D1 biais {d1_bias} confirme")
                            if h4_bias == m5_dir:
                                sig.confluences.append(f"H4 structure {h4_bias} alignee")
                            log.info(
                                f"  [M5 SCALP] {m5_dir} valide — D1:{d1_bias} H4:{h4_bias} "
                                f"ADX={m5['adx']:.0f} MACD={m5['macd']:+.3f} R:R={rr_val:.1f} "
                                f"Entry={entry} SL={sl} TP2={tp2}"
                            )
                            return sig
                        else:
                            log.info(f"  [M5 SCALP] R:R insuffisant ({rr_val:.2f} < {config.SCALP_MIN_RR})")
            else:
                log.info(f"  [M5 SCALP] SKIP — {m5.get('reason', 'pas de signal')}")

        sig.direction = "SKIP"
        return sig

    # ── H4 analyse complète ───────────────────────────────────────────────────
    h4_data    = analyze_h4(df_h4) if not df_h4.empty else {"bias": "NEUTRE", "signal": "SKIP", "aligned": False}
    h4_aligned = (h4_data["signal"] == direction)
    sig.h4_structure = h4_data.get("bias", "NEUTRE")

    # ── Order Blocks ──────────────────────────────────────────────────────────
    ob_h1 = detect_order_blocks(df_h1)
    ob_h4 = detect_order_blocks(df_h4) if not df_h4.empty else []
    price  = h1["close"]
    ob_hit = (price_in_ob(price, ob_h1, direction) is not None or
              price_in_ob(price, ob_h4, direction) is not None)
    sig.order_block = ob_hit

    # ── Fair Value Gaps ────────────────────────────────────────────────────────
    fvg_h1  = detect_fvg(df_h1)
    fvg_hit = price_in_fvg(price, fvg_h1, direction) is not None
    sig.fvg_present = fvg_hit

    # ── Niveaux clés ──────────────────────────────────────────────────────────
    key_levels = detect_key_levels(df_h1, df_d1)
    kl_hit     = near_key_level(price, key_levels, h1["atr"])
    sig.key_level_hit = kl_hit

    # ── Kill Zone ─────────────────────────────────────────────────────────────
    kz = current_kill_zone()
    sig.kill_zone = kz

    # ── Skill 1 : Session VWAP ────────────────────────────────────────────────
    vwap_data = session_vwap(df_m15) if not df_m15.empty else None

    # ── Skill 2 : BOS / CHoCH ─────────────────────────────────────────────────
    bos_data = detect_bos_choch(df_h1)

    # ── Skill 3 : Liquidity Sweep ─────────────────────────────────────────────
    sweep_data = detect_liquidity_sweep(df_h1, h1["atr"])

    # ── Skill 4 : Displacement ────────────────────────────────────────────────
    disp_data = detect_displacement(df_h1, h1["atr"])

    # ── Skill 5 : Volatility Regime ───────────────────────────────────────────
    vol_data = volatility_regime(df_h1)
    sig.warnings.append(f"Volatilité: {vol_data['regime']} ({vol_data['atr_pct']:.0f}e pct)")

    # Bloquer si EXTREME
    if vol_data["regime"] == "EXTREME":
        log.info(f"  [VOL REGIME] Volatilité EXTREME ({vol_data['atr_pct']:.0f}e pct) — pas de trade")
        sig.direction = "SKIP"
        sig.warnings.append("Volatilite EXTREME — trading bloque")
        return sig

    # ── Skill 6 : Equal Highs / Lows ─────────────────────────────────────────
    eq_hl_data = detect_equal_highs_lows(df_h1, h1["atr"])

    # ── Scoring (avec tous les nouveaux skills) ────────────────────────────────
    score, confluences, warnings = score_setup(
        direction, d1, h1, ob_hit, fvg_hit, kl_hit, kz, h4_aligned,
        vwap=vwap_data, bos_choch=bos_data, sweep=sweep_data,
        displacement=disp_data, vol_regime=vol_data, eq_hl=eq_hl_data,
    )
    sig.score       = score
    sig.confluences = confluences
    sig.warnings    = warnings

    # ── Grade ─────────────────────────────────────────────────────────────────
    if score >= MIN_SCORE_A_PLUS:
        sig.grade = "A+"
    elif score >= MIN_SCORE_A:
        sig.grade = "A"
    elif score >= MIN_SCORE_B:
        sig.grade = "B"
    else:
        sig.grade = "SKIP"

    # Skip B-setups par défaut (trop risqué)
    if sig.grade == "B":
        sig.direction = "SKIP"
        return sig

    # ── Filtre : momentum des 3 dernières bougies M15 ─────────────────────────
    # Pour A/A+ : exiger que les 2 des 3 dernières bougies M15 fermées
    # soient dans la direction du signal (évite les entrées contre le momentum immédiat)
    if df_m15 is not None and not df_m15.empty and len(df_m15) >= 5:
        m15_cl     = df_m15["Close"].iloc[-4:-1]   # 3 dernières bougies fermées
        m15_op     = df_m15["Open"].iloc[-4:-1]
        bull_count = int((m15_cl > m15_op).sum())
        bear_count = 3 - bull_count
        if direction == "LONG" and bull_count < 2:
            sig.direction = "SKIP"
            sig.warnings.append(f"Momentum M15 insuffisant ({bull_count}/3 bougies haussières) — LONG bloqué")
            log.info(f"  [FILTRE] LONG bloqué — momentum M15 faible ({bull_count}/3 bougies vertes)")
            return sig
        elif direction == "SHORT" and bear_count < 2:
            sig.direction = "SKIP"
            sig.warnings.append(f"Momentum M15 insuffisant ({bear_count}/3 bougies baissières) — SHORT bloqué")
            log.info(f"  [FILTRE] SHORT bloqué — momentum M15 faible ({bear_count}/3 bougies rouges)")
            return sig

    # ── Niveaux de prix ───────────────────────────────────────────────────────
    atr   = h1["atr"]
    sl_d  = atr * config.ATR_SL_MULT
    tp1_d = atr * config.ATR_TP1_MULT
    tp2_d = atr * config.ATR_TP2_MULT
    tp3_d = atr * config.ATR_TP2_MULT * 1.5   # Extension A+

    if direction == "SHORT":
        sig.entry = round(price, 2)
        sig.sl    = round(price + sl_d,  2)
        sig.tp1   = round(price - tp1_d, 2)
        sig.tp2   = round(price - tp2_d, 2)
        sig.tp3   = round(price - tp3_d, 2)
    else:
        sig.entry = round(price, 2)
        sig.sl    = round(price - sl_d,  2)
        sig.tp1   = round(price + tp1_d, 2)
        sig.tp2   = round(price + tp2_d, 2)
        sig.tp3   = round(price + tp3_d, 2)

    risk   = abs(sig.sl - sig.entry)
    reward = abs(sig.tp2 - sig.entry)
    rr_val = reward / max(risk, 0.01)

    # R:R minimum
    if rr_val < config.MIN_RR:
        sig.direction = "SKIP"
        sig.warnings.append(f"R:R insuffisant ({rr_val:.2f} < {config.MIN_RR})")
        return sig

    # ── Filtre : proximité prix actuel vs entrée calculée ─────────────────────
    # Si le prix M15 actuel est à plus de MAX_ENTRY_SLIPPAGE_ATR × ATR de l'entrée
    # calculée sur H1, le trade est bloqué (évite les entrées avec trop de slippage)
    if df_m15 is not None and not df_m15.empty and len(df_m15) >= 2:
        price_now   = float(df_m15["Close"].iloc[-2])   # dernière bougie M15 fermée
        entry_dist  = abs(price_now - sig.entry)
        max_slip    = atr * MAX_ENTRY_SLIPPAGE_ATR
        if entry_dist > max_slip:
            # Ajuster l'entrée au prix actuel si on peut maintenir le R:R
            if direction == "LONG":
                new_entry = price_now
                new_sl    = round(new_entry - atr * config.ATR_SL_MULT,  2)
                new_tp2   = round(new_entry + atr * config.ATR_TP2_MULT, 2)
            else:
                new_entry = price_now
                new_sl    = round(new_entry + atr * config.ATR_SL_MULT,  2)
                new_tp2   = round(new_entry - atr * config.ATR_TP2_MULT, 2)
            new_risk   = abs(new_sl - new_entry)
            new_reward = abs(new_tp2 - new_entry)
            new_rr     = new_reward / max(new_risk, 0.01)
            if new_rr >= config.MIN_RR:
                log.info(
                    f"  [SLIPPAGE] Entrée ajustée H1:{sig.entry:.0f} → M15:{new_entry:.0f} "
                    f"(dist={entry_dist:.0f}pts > max={max_slip:.0f}pts) | R:R={new_rr:.1f}"
                )
                sig.entry = round(new_entry, 2)
                sig.sl    = new_sl
                sig.tp1   = round(new_entry + atr * config.ATR_TP1_MULT * (1 if direction == "LONG" else -1), 2)
                sig.tp2   = new_tp2
                rr_val    = new_rr
            else:
                sig.direction = "SKIP"
                sig.warnings.append(
                    f"Slippage trop grand ({entry_dist:.0f}pts > {max_slip:.0f}pts) — R:R dégradé ({new_rr:.1f})"
                )
                log.info(
                    f"  [SLIPPAGE] Trade bloqué — écart {entry_dist:.0f}pts trop grand "
                    f"(max={max_slip:.0f}pts), R:R dégradé à {new_rr:.1f}"
                )
                return sig

    sig.direction   = direction
    sig.rr          = f"1:{round(rr_val, 1)}"
    # Facteur de volatilité intégré dans le grade (info pour sizing dynamique)
    if vol_data["vol_factor"] < 1.0:
        sig.warnings.append(f"Volume réduit {vol_data['vol_factor']:.0%} (régime {vol_data['regime']})")
    return sig


# ── Affichage rapport complet ─────────────────────────────────────────────────

def print_pro_signal(sig: ProSignal):
    sep = "─" * 56
    grade_icon = {"A+": "★★★", "A": "★★", "B": "★", "SKIP": "○"}

    log.info(sep)
    log.info(f"  SIGNAL PRO  {grade_icon.get(sig.grade, '')} GRADE {sig.grade}  —  {sig.direction}")
    log.info(sep)

    log.info(f"  D1 Biais      : {sig.d1_bias}")
    log.info(f"  H4 Structure  : {sig.h4_structure or 'N/A'}")
    log.info(f"  H1 Signal     : {sig.h1_signal}")
    if sig.h1_signal == "SKIP" and hasattr(sig, 'skip_reasons') and sig.skip_reasons:
        for r in sig.skip_reasons:
            log.info(f"    >> SKIP car : {r}")
    log.info(f"  Kill Zone     : {sig.kill_zone or 'HORS ZONE'}")
    log.info(f"  ATR           : {sig.atr:.1f} pts")

    log.info(f"  Confluences ({sig.score}):")
    for c in sig.confluences:
        log.info(f"    + {c}")

    if sig.warnings:
        log.info(f"  Avertissements:")
        for w in sig.warnings:
            log.info(f"    ! {w}")

    if sig.direction != "SKIP":
        log.info(f"  Entry : {sig.entry}")
        log.info(f"  SL    : {sig.sl}  (risque {abs(sig.sl - sig.entry):.0f} pts)")
        log.info(f"  TP1   : {sig.tp1}")
        log.info(f"  TP2   : {sig.tp2}  R:R {sig.rr}")
        if sig.grade == "A+":
            log.info(f"  TP3   : {sig.tp3}  (extension A+)")

    log.info(sep)
