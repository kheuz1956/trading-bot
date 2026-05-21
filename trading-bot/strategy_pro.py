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
MIN_SCORE_A_PLUS = 5   # A+ setup : exécution immédiate
MIN_SCORE_A      = 3   # A setup  : exécution normale
MIN_SCORE_B      = 2   # B setup  : skip (sauf si config.ALLOW_B_SETUP=True)


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

def _download(period: str, interval: str) -> pd.DataFrame:
    raw = yf.download("NQ=F", period=period, interval=interval,
                      progress=False, auto_adjust=True)
    if raw.empty:
        return pd.DataFrame()
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
    return df.dropna()


def load_mtf() -> dict[str, pd.DataFrame]:
    """Charge D1, H4, H1, M15 en parallèle via yfinance."""
    return {
        "D1":  _download("60d", "1d"),
        "H4":  _download("30d", "4h"),
        "H1":  _download("5d",  "1h"),
        "M15": _download("2d",  "15m"),
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
    hi, lo = df["High"], df["Low"]
    t  = (hi.rolling(config.TENKAN_PERIOD).max()    + lo.rolling(config.TENKAN_PERIOD).min())    / 2
    k  = (hi.rolling(config.KIJUN_PERIOD).max()     + lo.rolling(config.KIJUN_PERIOD).min())     / 2
    sa = ((t + k) / 2).shift(config.DISPLACEMENT)
    sb = ((hi.rolling(config.SENKOU_B_PERIOD).max() + lo.rolling(config.SENKOU_B_PERIOD).min()) / 2).shift(config.DISPLACEMENT)
    return pd.DataFrame({"tenkan": t, "kijun": k, "sa": sa, "sb": sb})


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

    return {
        "bias":           "HAUSSIER" if bullish else ("BAISSIER" if bearish else "NEUTRE"),
        "trend_strength": strength,
        "ema20": round(e20, 2),
        "ema50": round(e50, 2),
        "price": round(last, 2),
        "above_ema20": last > e20,
        "hh_hl": hh and hl,
        "lh_ll": lh and ll,
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

    # ── Déductions ────────────────────────────────────────────────────────────
    score = len(confluences)

    # Pénalité si D1 contredit
    if direction == "SHORT" and d1["bias"] == "HAUSSIER":
        score -= 2
        warnings.append("ATTENTION: CONTRE-TENDANCE D1 — risque eleve")
    if direction == "LONG" and d1["bias"] == "BAISSIER":
        score -= 2
        warnings.append("ATTENTION: CONTRE-TENDANCE D1 — risque eleve")

    return max(0, score), confluences, warnings


# ── Point d'entrée principal ──────────────────────────────────────────────────

def generate_pro_signal(mtf: dict[str, pd.DataFrame]) -> ProSignal:
    """
    Génère un signal professionnel multi-timeframe avec scoring de confluences.
    Retourne un ProSignal avec grade A+/A/B/SKIP.
    """
    df_d1 = mtf.get("D1", pd.DataFrame())
    df_h4 = mtf.get("H4", pd.DataFrame())
    df_h1 = mtf.get("H1", pd.DataFrame())
    df_m15 = mtf.get("M15", pd.DataFrame())

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
                    sig.direction = "SKIP"
                    return sig

                if h4_blocks:
                    log.warning(
                        f"  [M15 FALLBACK] BLOQUE — {m15_dir} contre structure H4 {h4_bias} "
                        f"(ADX={m15['adx']:.0f}) — alignement requis"
                    )
                    sig.direction = "SKIP"
                    return sig

                # M15 aligne avec D1 et H4 — signal valide
                direction        = m15_dir
                sig.direction    = direction
                sig.h1_signal    = f"M15-{direction}"
                sig.skip_reasons = []
                sig.atr          = m15["atr"] * 4   # ATR M15 × 4 ≈ ATR H1
                sig.kill_zone    = current_kill_zone()
                # Confluences : M15 + D1 + H4 si alignes
                sig.confluences.append(f"M15 {direction} (ADX={m15['adx']:.0f}, MACD={m15['macd']:.1f})")
                if d1_bias == direction:
                    sig.confluences.append(f"D1 biais {d1_bias} confirme")
                if h4_bias == direction:
                    sig.confluences.append(f"H4 structure {h4_bias} alignee")

                # Grade B (signal fallback) — exige alignement macro fort pour atteindre seuil conviction
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
        sig.direction = "SKIP"
        return sig

    # ── H4 alignement ─────────────────────────────────────────────────────────
    h4_aligned = False
    if not df_h4.empty and len(df_h4) >= 20:
        h4_cl   = df_h4["Close"]
        h4_e20  = float(_ema(h4_cl, 20).iloc[-1])
        h4_last = float(h4_cl.iloc[-1])
        h4_aligned = (direction == "SHORT" and h4_last < h4_e20) or \
                     (direction == "LONG"  and h4_last > h4_e20)
        sig.h4_structure = "BAISSIER" if h4_last < h4_e20 else "HAUSSIER"

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

    # ── Scoring ───────────────────────────────────────────────────────────────
    score, confluences, warnings = score_setup(
        direction, d1, h1, ob_hit, fvg_hit, kl_hit, kz, h4_aligned
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

    sig.direction = direction
    sig.rr        = f"1:{round(rr_val, 1)}"
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
