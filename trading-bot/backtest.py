#!/usr/bin/env python3
"""
Backtester — stratégie Ichimoku + RSI + ADX + MACD sur NQ=F H1
Usage : python backtest.py [--optimize]
"""

import sys
import itertools
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Paramètres par défaut (identiques au bot) ─────────────────────────────────
DEFAULTS = dict(
    TENKAN_PERIOD   = 9,
    KIJUN_PERIOD    = 26,
    SENKOU_B_PERIOD = 52,
    DISPLACEMENT    = 26,
    ATR_PERIOD      = 14,
    ATR_SL_MULT     = 1.5,
    ATR_TP2_MULT    = 3.0,
    ADX_PERIOD      = 14,
    ADX_MIN         = 20,
    RSI_PERIOD      = 14,
    RSI_MAX         = 70,
    RSI_MIN         = 30,
    MACD_FAST       = 12,
    MACD_SLOW       = 26,
    MACD_SIGNAL     = 9,
    SESSION_START   = 13 * 60 + 30,   # 13:30 UTC en minutes
    SESSION_END     = 20 * 60,         # 20:00 UTC en minutes
    VOLUME          = 0.10,
    TICK_VALUE      = 1.0,             # USD par point par 0.01 lot (approx US100)
)

# ── Chargement données ─────────────────────────────────────────────────────────

def load_data(period: str = "2y") -> pd.DataFrame:
    print(f"Téléchargement NQ=F H1 ({period})...")
    raw = yf.download("NQ=F", period=period, interval="1h",
                      progress=False, auto_adjust=True)
    if raw.empty:
        raise RuntimeError("Aucune donnée yfinance")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    idx = raw.index.get_level_values(0) if isinstance(raw.index, pd.MultiIndex) else raw.index
    df = pd.DataFrame({
        "Open":   raw["Open"].to_numpy().ravel(),
        "High":   raw["High"].to_numpy().ravel(),
        "Low":    raw["Low"].to_numpy().ravel(),
        "Close":  raw["Close"].to_numpy().ravel(),
        "Volume": raw["Volume"].to_numpy().ravel(),
    }, index=idx)
    df.index = pd.to_datetime(df.index, utc=True)
    print(f"  {len(df)} bougies chargées ({df.index[0].date()} → {df.index[-1].date()})")
    return df

# ── Indicateurs ───────────────────────────────────────────────────────────────

def compute_indicators(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    hi, lo, cl = df["High"], df["Low"], df["Close"]

    # Ichimoku
    t  = (hi.rolling(p["TENKAN_PERIOD"]).max()    + lo.rolling(p["TENKAN_PERIOD"]).min())    / 2
    k  = (hi.rolling(p["KIJUN_PERIOD"]).max()     + lo.rolling(p["KIJUN_PERIOD"]).min())     / 2
    sa = ((t + k) / 2).shift(p["DISPLACEMENT"])
    sb = ((hi.rolling(p["SENKOU_B_PERIOD"]).max()  + lo.rolling(p["SENKOU_B_PERIOD"]).min()) / 2).shift(p["DISPLACEMENT"])
    kumo_top = pd.concat([sa, sb], axis=1).max(axis=1)
    kumo_bot = pd.concat([sa, sb], axis=1).min(axis=1)

    # ATR
    tr = pd.concat([hi - lo, (hi - cl.shift()).abs(), (lo - cl.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(span=p["ATR_PERIOD"], adjust=False).mean()

    # ADX
    dm_p = (hi - hi.shift()).clip(lower=0)
    dm_m = (lo.shift() - lo).clip(lower=0)
    both = (dm_p > 0) & (dm_m > 0)
    dm_p = dm_p.where(~both | (dm_p >= dm_m), 0.0)
    dm_m = dm_m.where(~both | (dm_m >  dm_p), 0.0)
    atr_s = tr.ewm(span=p["ADX_PERIOD"], adjust=False).mean()
    di_p  = (dm_p.ewm(span=p["ADX_PERIOD"], adjust=False).mean() / atr_s.replace(0, np.nan)) * 100
    di_m  = (dm_m.ewm(span=p["ADX_PERIOD"], adjust=False).mean() / atr_s.replace(0, np.nan)) * 100
    dx    = ((di_p - di_m).abs() / (di_p + di_m).replace(0, np.nan)) * 100
    adx   = dx.ewm(span=p["ADX_PERIOD"], adjust=False).mean()

    # RSI
    delta = cl.diff()
    gain  = delta.clip(lower=0).ewm(com=p["RSI_PERIOD"] - 1, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=p["RSI_PERIOD"] - 1, adjust=False).mean()
    rsi   = 100 - 100 / (1 + gain / loss.replace(0, np.nan))

    # MACD histogramme
    ema_f = cl.ewm(span=p["MACD_FAST"],   adjust=False).mean()
    ema_s = cl.ewm(span=p["MACD_SLOW"],   adjust=False).mean()
    macd  = ema_f - ema_s
    sig   = macd.ewm(span=p["MACD_SIGNAL"], adjust=False).mean()
    hist  = macd - sig

    out = df.copy()
    out["tenkan"]   = t
    out["kijun"]    = k
    out["kumo_top"] = kumo_top
    out["kumo_bot"] = kumo_bot
    out["atr"]      = atr
    out["adx"]      = adx
    out["rsi"]      = rsi
    out["macd_hist"]= hist
    return out

# ── Génération des signaux ─────────────────────────────────────────────────────

def generate_signals(df: pd.DataFrame, p: dict) -> pd.Series:
    c = df["Close"]
    t = df["tenkan"]; k = df["kijun"]
    kt = df["kumo_top"]; kb = df["kumo_bot"]
    atr = df["atr"]; adx = df["adx"]
    rsi = df["rsi"]; hist = df["macd_hist"]

    in_session = (
        (df.index.weekday < 5) &
        (df.index.hour * 60 + df.index.minute >= p["SESSION_START"]) &
        (df.index.hour * 60 + df.index.minute <= p["SESSION_END"])
    )
    in_kumo   = (c >= kb) & (c <= kt)
    trending  = adx >= p["ADX_MIN"]
    valid     = ~in_kumo & trending & in_session

    short = valid & (c < kb) & (t < k) & (c < t) & (rsi <= p["RSI_MAX"]) & (hist < 0)
    long  = valid & (c > kt) & (t > k) & (c > t) & (rsi >= p["RSI_MIN"]) & (hist > 0)

    sig = pd.Series("SKIP", index=df.index)
    sig[short] = "SHORT"
    sig[long]  = "LONG"
    return sig

# ── Simulation trade par trade ─────────────────────────────────────────────────

@dataclass
class Trade:
    entry_time:  datetime
    exit_time:   datetime | None = None
    side:        str = ""
    entry:       float = 0.0
    sl:          float = 0.0
    tp1:         float = 0.0
    tp2:         float = 0.0
    exit_price:  float = 0.0
    result:      str = ""   # "TP2" | "TP1" | "SL" | "OPEN"
    pnl_pts:     float = 0.0

def simulate(df: pd.DataFrame, p: dict) -> list[Trade]:
    ind  = compute_indicators(df, p)
    sigs = generate_signals(ind, p)

    trades: list[Trade] = []
    open_trade: Trade | None = None

    for i in range(1, len(ind)):
        row  = ind.iloc[i]
        prev = ind.iloc[i - 1]
        sig  = sigs.iloc[i - 1]   # signal de la bougie fermée
        ts   = ind.index[i]

        # Gestion position ouverte
        if open_trade:
            hi_i = row["High"]
            lo_i = row["Low"]

            if open_trade.side == "SHORT":
                if lo_i <= open_trade.tp2:
                    open_trade.exit_price = open_trade.tp2
                    open_trade.result     = "TP2"
                    open_trade.pnl_pts    = open_trade.entry - open_trade.tp2
                elif lo_i <= open_trade.tp1:
                    open_trade.exit_price = open_trade.tp1
                    open_trade.result     = "TP1"
                    open_trade.pnl_pts    = open_trade.entry - open_trade.tp1
                elif hi_i >= open_trade.sl:
                    open_trade.exit_price = open_trade.sl
                    open_trade.result     = "SL"
                    open_trade.pnl_pts    = open_trade.entry - open_trade.sl
            else:  # LONG
                if hi_i >= open_trade.tp2:
                    open_trade.exit_price = open_trade.tp2
                    open_trade.result     = "TP2"
                    open_trade.pnl_pts    = open_trade.tp2 - open_trade.entry
                elif hi_i >= open_trade.tp1:
                    open_trade.exit_price = open_trade.tp1
                    open_trade.result     = "TP1"
                    open_trade.pnl_pts    = open_trade.tp1 - open_trade.entry
                elif lo_i <= open_trade.sl:
                    open_trade.exit_price = open_trade.sl
                    open_trade.result     = "SL"
                    open_trade.pnl_pts    = open_trade.sl - open_trade.entry

            if open_trade.result:
                open_trade.exit_time = ts
                trades.append(open_trade)
                open_trade = None

        # Nouveau trade si pas de position
        if not open_trade and sig in ("SHORT", "LONG"):
            atr   = float(prev["atr"])
            entry = float(row["Open"])   # entrée à l'Open de la bougie suivante
            sl_d  = atr * p["ATR_SL_MULT"]
            tp2_d = atr * p["ATR_TP2_MULT"]
            tp1_d = atr * p["ATR_SL_MULT"]   # TP1 = même distance que SL (R:R 1:1)

            if sig == "SHORT":
                sl  = entry + sl_d
                tp1 = entry - tp1_d
                tp2 = entry - tp2_d
            else:
                sl  = entry - sl_d
                tp1 = entry + tp1_d
                tp2 = entry + tp2_d

            open_trade = Trade(
                entry_time=ts, side=sig,
                entry=entry, sl=sl, tp1=tp1, tp2=tp2,
            )

    # Position encore ouverte en fin de backtest
    if open_trade:
        open_trade.result     = "OPEN"
        open_trade.exit_price = float(df["Close"].iloc[-1])
        open_trade.pnl_pts    = (
            open_trade.entry - open_trade.exit_price if open_trade.side == "SHORT"
            else open_trade.exit_price - open_trade.entry
        )
        open_trade.exit_time = df.index[-1]
        trades.append(open_trade)

    return trades

# ── Métriques ─────────────────────────────────────────────────────────────────

def metrics(trades: list[Trade], p: dict) -> dict:
    if not trades:
        return {}

    closed  = [t for t in trades if t.result != "OPEN"]
    winners = [t for t in closed  if t.pnl_pts > 0]
    losers  = [t for t in closed  if t.pnl_pts <= 0]

    total_pts  = sum(t.pnl_pts for t in closed)
    gross_win  = sum(t.pnl_pts for t in winners) or 0
    gross_loss = abs(sum(t.pnl_pts for t in losers)) or 1

    # Courbe d'équité en points cumulés
    pnl_series = pd.Series([t.pnl_pts for t in closed])
    equity     = pnl_series.cumsum()
    drawdown   = equity - equity.cummax()
    max_dd     = float(drawdown.min())

    # Sharpe simplifié (sans annualisation)
    sharpe = (pnl_series.mean() / pnl_series.std()) if pnl_series.std() > 0 else 0

    # Séquences de pertes consécutives
    consecutive_losses = 0
    max_consec_losses  = 0
    for t in closed:
        if t.pnl_pts <= 0:
            consecutive_losses += 1
            max_consec_losses = max(max_consec_losses, consecutive_losses)
        else:
            consecutive_losses = 0

    return dict(
        n_trades     = len(closed),
        n_winners    = len(winners),
        n_losers     = len(losers),
        win_rate     = len(winners) / max(len(closed), 1) * 100,
        total_pts    = round(total_pts, 1),
        avg_win_pts  = round(gross_win  / max(len(winners), 1), 1),
        avg_loss_pts = round(gross_loss / max(len(losers),  1), 1),
        profit_factor= round(gross_win / gross_loss, 2),
        max_dd_pts   = round(max_dd, 1),
        sharpe       = round(sharpe, 3),
        max_consec_losses = max_consec_losses,
        tp2_rate     = sum(1 for t in closed if t.result == "TP2") / max(len(closed), 1) * 100,
        sl_rate      = sum(1 for t in closed if t.result == "SL")  / max(len(closed), 1) * 100,
    )

# ── Affichage ─────────────────────────────────────────────────────────────────

def print_metrics(m: dict, label: str = ""):
    if not m:
        print("  Aucun trade généré.")
        return
    tag = f"[{label}] " if label else ""
    print(f"""
{tag}═══════════════════════════════════════
  Trades      : {m['n_trades']}  (W:{m['n_winners']} L:{m['n_losers']})
  Win rate    : {m['win_rate']:.1f}%
  TP2 rate    : {m['tp2_rate']:.1f}%   SL rate: {m['sl_rate']:.1f}%
  Total pts   : {m['total_pts']:+.1f}
  Avg win     : +{m['avg_win_pts']:.1f} pts
  Avg loss    : -{m['avg_loss_pts']:.1f} pts
  Profit Factor: {m['profit_factor']:.2f}
  Max Drawdown: {m['max_dd_pts']:.1f} pts
  Sharpe      : {m['sharpe']:.3f}
  Max pertes consécutives: {m['max_consec_losses']}
═══════════════════════════════════════""")

# ── Optimisation par grid search ──────────────────────────────────────────────

def optimize(df: pd.DataFrame):
    grid = dict(
        ATR_SL_MULT  = [1.0, 1.5, 2.0],
        ATR_TP2_MULT = [2.0, 3.0, 4.0],
        ADX_MIN      = [15, 20, 25],
    )
    keys   = list(grid.keys())
    combos = list(itertools.product(*grid.values()))
    print(f"\nOptimisation — {len(combos)} combinaisons...")

    results = []
    for combo in combos:
        p = {**DEFAULTS, **dict(zip(keys, combo))}
        try:
            trades = simulate(df, p)
            m      = metrics(trades, p)
            if not m or m["n_trades"] < 10:
                continue
            results.append((m["profit_factor"], m["win_rate"], m["total_pts"], combo, m))
        except Exception:
            continue

    if not results:
        print("Aucun résultat valide.")
        return

    results.sort(reverse=True)
    print(f"\nTop 5 combinaisons (trié par Profit Factor):")
    for rank, (pf, wr, pts, combo, m) in enumerate(results[:5], 1):
        params = dict(zip(keys, combo))
        print(f"\n#{rank}  PF={pf:.2f}  WR={wr:.1f}%  Pts={pts:+.1f}  "
              f"SL×{params['ATR_SL_MULT']} TP×{params['ATR_TP2_MULT']} ADX≥{params['ADX_MIN']}")
        print_metrics(m)

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    optimize_mode = "--optimize" in sys.argv

    df = load_data("2y")

    print("\n── Backtest stratégie actuelle ──────────────────────────")
    trades = simulate(df, DEFAULTS)
    m      = metrics(trades, DEFAULTS)
    print_metrics(m, "Stratégie actuelle")

    # Détail par année
    for year in sorted({t.entry_time.year for t in trades if t.result != "OPEN"}):
        year_trades = [t for t in trades if t.entry_time.year == year and t.result != "OPEN"]
        m_yr = metrics(year_trades, DEFAULTS)
        print_metrics(m_yr, str(year))

    # Détail SHORT vs LONG
    for side in ("SHORT", "LONG"):
        side_trades = [t for t in trades if t.side == side and t.result != "OPEN"]
        m_s = metrics(side_trades, DEFAULTS)
        print_metrics(m_s, side)

    if optimize_mode:
        optimize(df)
    else:
        print("\n  (Ajoutez --optimize pour lancer le grid search des paramètres)")
