"""
Market Regime Classifier — Choppiness Index + ADX + ATR Percentile
Classifie le marché en : TRENDING | RANGING | VOLATILE | TRANSITIONING

Référence: Elder "Trading for a Living" + Kaufman "Trading Systems and Methods"
Choppiness Index (Dreiss, 1993):
  CI = 100 × log10(Σ ATR(1,14) / (max(High,14) - min(Low,14))) / log10(14)
  CI < 38.2 → tendance forte (acheter breakouts)
  CI > 61.8 → marché choppy/range (éviter les suiveurs de tendance)
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass


@dataclass
class MarketRegime:
    name: str           # TRENDING | RANGING | VOLATILE | TRANSITIONING
    confidence: float   # 0.0 – 1.0
    choppiness: float   # Choppiness Index (38.2 = trend, 61.8 = range)
    adx: float
    atr_pct: float      # ATR courant / ATR_20_avg
    # Paramètres adaptatifs recommandés pour ce régime
    adx_min: int
    sl_mult: float
    tp_mult: float
    trade_ok: bool      # False si RANGING pur ou VOLATILE extrême


def _true_range(df: pd.DataFrame) -> pd.Series:
    return pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift(1)).abs(),
        (df["Low"]  - df["Close"].shift(1)).abs(),
    ], axis=1).max(axis=1)


def _adx_simple(df: pd.DataFrame, period: int = 14) -> float:
    high, low = df["High"], df["Low"]
    tr = _true_range(df)
    up   = high.diff()
    down = -low.diff()
    plus_dm  = up.where((up > down)   & (up > 0),   0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    atr14    = tr.rolling(period).mean().clip(lower=1e-6)
    plus_di  = 100 * plus_dm.rolling(period).mean()  / atr14
    minus_di = 100 * minus_dm.rolling(period).mean() / atr14
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-6)
    adx_series = dx.rolling(period).mean()
    return float(adx_series.iloc[-2]) if len(adx_series) > period + 2 else 0.0


def _choppiness_index(df: pd.DataFrame, period: int = 14) -> float:
    tr    = _true_range(df)
    atr_sum  = tr.rolling(period).sum()
    high_max = df["High"].rolling(period).max()
    low_min  = df["Low"].rolling(period).min()
    hl_range = (high_max - low_min).clip(lower=1e-6)
    ci_series = 100 * np.log10(atr_sum / hl_range) / np.log10(period)
    return float(ci_series.iloc[-2]) if len(ci_series) > period + 2 else 50.0


def classify_regime(df_h1: pd.DataFrame) -> MarketRegime:
    """
    Classifie le régime de marché depuis les données H1.

    Grille de décision:
      CI < 38.2 + ADX > 25           → TRENDING  (trend-following optimal)
      CI > 61.8 + ATR_pct < 1.8      → RANGING   (éviter entrées tendance)
      ATR_pct > 2.0 + ADX < 20       → VOLATILE  (stop trading)
      sinon                           → TRANSITIONING
    """
    if df_h1 is None or len(df_h1) < 30:
        return MarketRegime("UNKNOWN", 0.0, 50.0, 0.0, 1.0, 22, 1.0, 2.0, True)

    tr      = _true_range(df_h1)
    ci      = _choppiness_index(df_h1, 14)
    adx     = _adx_simple(df_h1, 14)

    atr_cur = float(tr.rolling(14).mean().iloc[-2])
    atr_avg = float(tr.rolling(14).mean().rolling(20).mean().iloc[-2])
    atr_pct = atr_cur / max(atr_avg, 1e-6)

    # ── Classification ────────────────────────────────────────────────────────
    if atr_pct > 2.2 and adx < 25:
        name     = "VOLATILE"
        trade_ok = False
    elif ci > 61.8:
        name     = "RANGING"
        trade_ok = False
    elif ci < 38.2 and adx > 20:
        name     = "TRENDING"
        trade_ok = True
    else:
        name     = "TRANSITIONING"
        trade_ok = True

    # ── Confiance ─────────────────────────────────────────────────────────────
    if name == "TRENDING":
        confidence = min(1.0, (50 - ci) / 12)
    elif name == "RANGING":
        confidence = min(1.0, (ci - 50) / 12)
    elif name == "VOLATILE":
        confidence = min(1.0, (atr_pct - 1.5) / 0.8)
    else:
        confidence = 0.5

    # ── Paramètres adaptatifs ─────────────────────────────────────────────────
    if name == "TRENDING":
        adx_min, sl_mult, tp_mult = 18, 0.9, 2.5   # SL serré, TP large
    elif name == "RANGING":
        adx_min, sl_mult, tp_mult = 30, 0.7, 1.0   # Très sélectif
    elif name == "VOLATILE":
        adx_min, sl_mult, tp_mult = 35, 1.8, 1.8   # SL large obligatoire
    else:
        adx_min, sl_mult, tp_mult = 22, 1.0, 2.0   # Paramètres neutres

    return MarketRegime(
        name       = name,
        confidence = round(max(0.0, confidence), 2),
        choppiness = round(ci, 1),
        adx        = round(adx, 1),
        atr_pct    = round(atr_pct, 2),
        adx_min    = adx_min,
        sl_mult    = sl_mult,
        tp_mult    = tp_mult,
        trade_ok   = trade_ok,
    )


def regime_summary(r: MarketRegime) -> str:
    icons = {"TRENDING": "↗", "RANGING": "↔", "VOLATILE": "⚡", "TRANSITIONING": "~", "UNKNOWN": "?"}
    return (
        f"{icons.get(r.name,'?')} {r.name} "
        f"(CI={r.choppiness}, ADX={r.adx}, ATR×{r.atr_pct}) "
        f"conf={r.confidence:.0%} | trade_ok={r.trade_ok}"
    )
