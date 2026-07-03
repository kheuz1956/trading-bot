#!/usr/bin/env python3
"""
Pro Trader Routines — niveaux institutionnels et routines quotidiennes.

Concepts :
  VWAP session    → benchmark institutionnel (ancré à London ou NY open)
  PDH / PDL       → Previous Day High/Low — magnets journaliers
  PWH / PWL       → Previous Week High/Low — cadre hebdomadaire
  Opening Range   → range NY Open 13:30-14:00 UTC — breakouts haute proba
  ES/NQ corr      → corrélation S&P / Nasdaq — confirmation institutionnelle
  Daily reset     → remise à zéro du compteur journalier à minuit UTC
  Pre-session log → briefing quotidien 07:00 UTC
"""

import logging
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd

log = logging.getLogger("xtb_pw")


# ══════════════════════════════════════════════════════════════════════════════
# 1. VWAP — Volume Weighted Average Price (ancré session)
# ══════════════════════════════════════════════════════════════════════════════

def calc_session_vwap(df_m5: pd.DataFrame) -> dict:
    """
    VWAP ancré à l'ouverture London (08:00 UTC) ou NY (13:30 UTC).
    - Price > VWAP : biais haussier institutionnel → préférer LONG
    - Price < VWAP : biais baissier institutionnel → préférer SHORT
    Retourne vwap, band_up/dn (±1σ), bias, dist_pts.
    """
    if df_m5 is None or df_m5.empty or len(df_m5) < 5:
        return {"vwap": None, "band_up": None, "band_dn": None, "bias": "NEUTRE", "dist_pts": 0}

    now_utc = datetime.now(timezone.utc)
    today   = now_utc.date()

    # Anchor : NY Open si après 13:30, sinon London Open 08:00
    if now_utc.hour >= 13 and now_utc.minute >= 30:
        anchor = datetime(today.year, today.month, today.day, 13, 30, tzinfo=timezone.utc)
    else:
        anchor = datetime(today.year, today.month, today.day,  8,  0, tzinfo=timezone.utc)

    df_s = df_m5[df_m5.index >= anchor].copy()
    if len(df_s) < 3:
        return {"vwap": None, "band_up": None, "band_dn": None, "bias": "NEUTRE", "dist_pts": 0}

    tp  = (df_s["High"] + df_s["Low"] + df_s["Close"]) / 3
    vol = df_s["Volume"].replace(0, 1)

    cum_tpv = (tp * vol).cumsum()
    cum_vol = vol.cumsum()
    vwap_s  = cum_tpv / cum_vol

    vwap = float(vwap_s.iloc[-1])
    sq_diff = ((tp - vwap_s) ** 2 * vol).cumsum() / cum_vol
    std     = float(np.sqrt(max(float(sq_diff.iloc[-1]), 0)))

    last  = float(df_s["Close"].iloc[-1])
    bias  = "HAUSSIER" if last > vwap else "BAISSIER"

    return {
        "vwap":     round(vwap,        2),
        "band_up":  round(vwap + std,  2),
        "band_dn":  round(vwap - std,  2),
        "bias":     bias,
        "dist_pts": round(last - vwap, 1),
        "last":     round(last,        2),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 2. PDH / PDL — Previous Day High / Low
# ══════════════════════════════════════════════════════════════════════════════

def get_pdh_pdl(df_d1: pd.DataFrame) -> dict:
    """
    Previous Day High/Low depuis les données D1 yfinance.
    Niveaux de référence institutionnels — toujours tracés en premier.
    """
    if df_d1 is None or df_d1.empty or len(df_d1) < 2:
        return {"pdh": None, "pdl": None, "pdo": None, "pdc": None, "pd_range": 0}

    prev = df_d1.iloc[-2]
    return {
        "pdh":      round(float(prev["High"]),              2),
        "pdl":      round(float(prev["Low"]),               2),
        "pdo":      round(float(prev["Open"]),              2),
        "pdc":      round(float(prev["Close"]),             2),
        "pd_range": round(float(prev["High"] - prev["Low"]), 1),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 3. PWH / PWL — Previous Week High / Low
# ══════════════════════════════════════════════════════════════════════════════

def get_pwh_pwl(df_d1: pd.DataFrame) -> dict:
    """
    Previous Week High/Low — cadre hebdomadaire institutionnel.
    Calculé sur les 5 jours ouvrables de la semaine précédente.
    """
    if df_d1 is None or df_d1.empty or len(df_d1) < 7:
        return {"pwh": None, "pwl": None, "pw_range": 0}

    # Normaliser le timezone de l'index
    idx = df_d1.index
    if hasattr(idx, "tz") and idx.tz is None:
        df_d1 = df_d1.copy()
        df_d1.index = df_d1.index.tz_localize("UTC")

    now_utc = datetime.now(timezone.utc)
    days_since_mon = now_utc.weekday()
    this_mon = datetime(now_utc.year, now_utc.month, now_utc.day,
                        tzinfo=timezone.utc) - timedelta(days=days_since_mon)
    prev_mon = this_mon - timedelta(days=7)

    pw = df_d1[(df_d1.index >= prev_mon) & (df_d1.index < this_mon)]
    if pw.empty:
        pw = df_d1.iloc[-7:-2]   # fallback : 5 jours avant avant-hier

    if pw.empty:
        return {"pwh": None, "pwl": None, "pw_range": 0}

    pwh = round(float(pw["High"].max()), 2)
    pwl = round(float(pw["Low"].min()),  2)
    return {"pwh": pwh, "pwl": pwl, "pw_range": round(pwh - pwl, 1)}


# ══════════════════════════════════════════════════════════════════════════════
# 4. OPENING RANGE — NY Open 13:30-14:00 UTC
# ══════════════════════════════════════════════════════════════════════════════

def get_opening_range(df_m5: pd.DataFrame, window_min: int = 30) -> dict:
    """
    Opening Range = high/low des 30 premières minutes de la session NY.
    - Break au-dessus + volume → LONG haute probabilité (add +2 score)
    - Break en-dessous + volume → SHORT haute probabilité (add +2 score)
    """
    empty = {"or_high": None, "or_low": None, "or_range": 0, "or_complete": False, "breakout": "NONE"}
    if df_m5 is None or df_m5.empty:
        return empty

    now_utc = datetime.now(timezone.utc)
    today   = now_utc.date()
    ny_open = datetime(today.year, today.month, today.day, 13, 30, tzinfo=timezone.utc)
    or_end  = ny_open + timedelta(minutes=window_min)

    if now_utc < ny_open:
        return empty

    df_or = df_m5[(df_m5.index >= ny_open) & (df_m5.index < or_end)]
    if df_or.empty:
        return empty

    or_high    = round(float(df_or["High"].max()),       2)
    or_low     = round(float(df_or["Low"].min()),        2)
    or_range   = round(or_high - or_low,                 1)
    or_complete = now_utc >= or_end

    breakout = "NONE"
    if or_complete and or_range > 0:
        df_after = df_m5[df_m5.index >= or_end]
        if not df_after.empty:
            last = float(df_after["Close"].iloc[-1])
            buf  = or_range * 0.05   # 5% du range = confirmation
            if last > or_high + buf:
                breakout = "LONG"
            elif last < or_low - buf:
                breakout = "SHORT"

    return {
        "or_high":     or_high,
        "or_low":      or_low,
        "or_range":    or_range,
        "or_complete": or_complete,
        "breakout":    breakout,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 5. KEY LEVELS SCORER — confluences PDH/PDL/VWAP/OR
# ══════════════════════════════════════════════════════════════════════════════

def score_key_levels(price: float, direction: str, levels: dict, atr: float) -> tuple[int, list[str]]:
    """
    Score les niveaux institutionnels en tant que confluences.
    +1 par niveau favorable, +2 pour Opening Range Breakout.
    Pénalité si prix est ENTRE un niveau clé et sa cible (mur institutionnel).
    """
    score = 0
    confs: list[str] = []
    prox = atr * 0.3   # zone de proximité = 30% ATR

    vwap    = levels.get("vwap")
    pdh     = levels.get("pdh")
    pdl     = levels.get("pdl")
    pwh     = levels.get("pwh")
    pwl     = levels.get("pwl")
    or_high = levels.get("or_high")
    or_low  = levels.get("or_low")
    breakout = levels.get("breakout", "NONE")

    if direction == "SHORT":
        if vwap and price < vwap:
            score += 1
            confs.append(f"Sous VWAP {vwap:.0f} ({abs(price-vwap):.0f}pts) — biais baissier institutionnel")
        if pdh and abs(price - pdh) <= prox:
            score += 1
            confs.append(f"Proche PDH {pdh:.0f} — résistance journalière")
        if pwh and abs(price - pwh) <= prox:
            score += 1
            confs.append(f"Proche PWH {pwh:.0f} — résistance hebdomadaire")
        if breakout == "SHORT" and or_low:
            score += 2
            confs.append(f"Opening Range Breakdown — OR_LOW {or_low:.0f} cassé")
        # Pénalité : SHORT vers VWAP si price >> vwap (le VWAP va agir comme support)
        if vwap and price > vwap + prox:
            score -= 1
            confs.append(f"VWAP {vwap:.0f} potentiel support sous le prix")

    elif direction == "LONG":
        if vwap and price > vwap:
            score += 1
            confs.append(f"Au-dessus VWAP {vwap:.0f} (+{abs(price-vwap):.0f}pts) — biais haussier institutionnel")
        if pdl and abs(price - pdl) <= prox:
            score += 1
            confs.append(f"Proche PDL {pdl:.0f} — support journalier")
        if pwl and abs(price - pwl) <= prox:
            score += 1
            confs.append(f"Proche PWL {pwl:.0f} — support hebdomadaire")
        if breakout == "LONG" and or_high:
            score += 2
            confs.append(f"Opening Range Breakout — OR_HIGH {or_high:.0f} cassé")
        # Pénalité : LONG vers VWAP si price << vwap (résistance imminente)
        if vwap and price < vwap - prox:
            score -= 1
            confs.append(f"VWAP {vwap:.0f} potentielle résistance au-dessus")

    return score, confs


# ══════════════════════════════════════════════════════════════════════════════
# 6. CORRELATION ES / NQ
# ══════════════════════════════════════════════════════════════════════════════

def check_es_nq_correlation(df_m5_nq: pd.DataFrame) -> dict:
    """
    Corrélation des retours 5 min entre ES=F (S&P) et NQ.
    corr > 0.70 → alignement institutionnel → signal confirmé
    corr < 0.50 → divergence → avertissement (signal moins fiable)
    """
    try:
        import yfinance as yf
        es = yf.download("ES=F", period="1d", interval="5m", progress=False, auto_adjust=True)
        if es.empty or len(es) < 20:
            return {"corr": None, "aligned": True, "es_dir": "?", "warning": ""}
        if isinstance(es.columns, pd.MultiIndex):
            es.columns = es.columns.get_level_values(0)

        es_ret = es["Close"].pct_change().dropna().tail(20)
        if df_m5_nq is None or df_m5_nq.empty or len(df_m5_nq) < 20:
            return {"corr": None, "aligned": True, "es_dir": "?", "warning": ""}

        nq_ret = df_m5_nq["Close"].pct_change().dropna().tail(20)
        common = es_ret.index.intersection(nq_ret.index)
        if len(common) < 10:
            return {"corr": None, "aligned": True, "es_dir": "?", "warning": ""}

        corr    = float(es_ret.loc[common].corr(nq_ret.loc[common]))
        aligned = corr > 0.70
        es_dir  = "HAUSSIER" if float(es["Close"].iloc[-1]) > float(es["Close"].iloc[-6]) else "BAISSIER"

        return {
            "corr":    round(corr, 2),
            "aligned": aligned,
            "es_dir":  es_dir,
            "warning": "" if aligned else f"ES/NQ divergence (corr={corr:.2f}) — conviction réduite",
        }
    except Exception:
        return {"corr": None, "aligned": True, "es_dir": "?", "warning": ""}


# ══════════════════════════════════════════════════════════════════════════════
# 7. DAILY STATE RESET — minuit UTC
# ══════════════════════════════════════════════════════════════════════════════

def check_daily_reset(state: dict) -> dict:
    """
    Réinitialise les compteurs journaliers si le jour UTC a changé.
    Préserve session_start_equity pour le drawdown check intraday.
    """
    today     = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    last_date = state.get("trade_date", "")

    if last_date != today:
        old_count = state.get("daily_trade_count", 0)
        state["daily_trade_count"] = 0
        state["trade_date"]        = today
        state["daily_losses"]      = 0
        # Reset equity de référence pour le drawdown quotidien
        equity = state.get("account_equity")
        if equity:
            state["session_start_equity"] = equity
        if old_count > 0 or last_date:
            log.info(
                f"  [DAILY RESET] Nouveau jour {today} — "
                f"compteur réinitialisé (J-1 : {old_count} trades)"
            )

    return state


# ══════════════════════════════════════════════════════════════════════════════
# 8. PRE-SESSION BRIEFING — 07:00 UTC (London Open)
# ══════════════════════════════════════════════════════════════════════════════

_briefing_done_date: str = ""

def log_presession_briefing(mtf: dict, levels: dict) -> None:
    """
    Briefing quotidien affiché une seule fois à London Open (07:00-07:05 UTC).
    Synthèse complète : niveaux clés, biais D1, calendrier économique.
    """
    global _briefing_done_date

    now   = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    # Une seule fois par jour, entre 07:00 et 07:15 UTC
    if _briefing_done_date == today:
        return
    if not (7 <= now.hour < 8 and now.minute < 15):
        return

    _briefing_done_date = today

    log.info("═" * 60)
    log.info(f"  PRE-SESSION BRIEFING — {today}")
    log.info("═" * 60)

    # Niveaux journaliers
    pdh = levels.get("pdh")
    pdl = levels.get("pdl")
    pdr = levels.get("pd_range", 0)
    if pdh and pdl:
        log.info(f"  PDH : {pdh:.2f}  |  PDL : {pdl:.2f}  |  Range J-1 : {pdr:.0f} pts")

    # Niveaux hebdomadaires
    pwh = levels.get("pwh")
    pwl = levels.get("pwl")
    pwr = levels.get("pw_range", 0)
    if pwh and pwl:
        log.info(f"  PWH : {pwh:.2f}  |  PWL : {pwl:.2f}  |  Range S-1 : {pwr:.0f} pts")

    # Biais D1
    try:
        from strategy_pro import analyze_d1
        df_d1 = mtf.get("D1", pd.DataFrame())
        if not df_d1.empty and len(df_d1) > 20:
            d1 = analyze_d1(df_d1)
            log.info(f"  BIAIS D1 : {d1.get('bias', '?')}  |  Force : {d1.get('trend_strength', '?')}")
    except Exception:
        pass

    log.info("  KILL ZONES : London 07h-10h | NY 13h30-16h | NY Aft 16h-20h")
    log.info("  RÈGLE N°1  : Suivre la tendance D1 — ne jamais contredire le biais")
    log.info("  RÈGLE N°2  : Attendre le signal H1 Ichimoku — ne pas anticiper")
    log.info("  RÈGLE N°3  : Stop TOUJOURS placé avant entrée — zéro exception")
    log.info("═" * 60)


# ══════════════════════════════════════════════════════════════════════════════
# 9. ROUTINE COMPLÈTE — appelée à chaque scan depuis signal_runner.py
# ══════════════════════════════════════════════════════════════════════════════

def run_pro_routine(mtf: dict, state: dict) -> dict:
    """
    Point d'entrée unique pour toutes les routines pro.
    Retourne un dict 'pro_ctx' utilisé pour enrichir le signal et les logs.

    Usage dans signal_runner.py :
        pro_ctx = run_pro_routine(mtf, state)
        # puis passer pro_ctx à score_key_levels() depuis strategy_pro.py
    """
    df_d1 = mtf.get("D1", pd.DataFrame())
    df_m5 = mtf.get("M5", pd.DataFrame())

    # 7. Reset journalier (avant tout)
    state = check_daily_reset(state)

    # Niveaux institutionnels
    vwap_data = calc_session_vwap(df_m5)
    pdh_pdl   = get_pdh_pdl(df_d1)
    pwh_pwl   = get_pwh_pwl(df_d1)
    or_data   = get_opening_range(df_m5)

    # Merge en un seul dict
    levels = {**vwap_data, **pdh_pdl, **pwh_pwl, **or_data}

    # 8. Briefing pré-session (London Open 07:00-07:15)
    log_presession_briefing(mtf, levels)

    # 6. Corrélation ES/NQ (cache 5 min pour éviter trop d'appels yfinance)
    cache = getattr(run_pro_routine, "_es_cache", (None, 0))
    import time
    if time.time() - cache[1] > 300:
        es_corr = check_es_nq_correlation(df_m5)
        run_pro_routine._es_cache = (es_corr, time.time())
    else:
        es_corr = cache[0] or {"corr": None, "aligned": True, "es_dir": "?", "warning": ""}

    # Log VWAP et niveaux clés (compact)
    vwap = vwap_data.get("vwap")
    pdh  = pdh_pdl.get("pdh")
    pdl  = pdh_pdl.get("pdl")
    pwh  = pwh_pwl.get("pwh")
    pwl  = pwh_pwl.get("pwl")
    orh  = or_data.get("or_high")
    orl  = or_data.get("or_low")

    vwap_str = f"VWAP={vwap:.0f}({vwap_data.get('bias','?')})" if vwap else "VWAP=N/A"
    pdh_str  = f"PDH={pdh:.0f}/PDL={pdl:.0f}" if pdh else "PDH/PDL=N/A"
    pwh_str  = f"PWH={pwh:.0f}/PWL={pwl:.0f}" if pwh else ""
    or_str   = (f"OR={orh:.0f}-{orl:.0f}({'DONE' if or_data.get('or_complete') else 'LIVE'})"
                if orh else "OR=N/A")
    corr_str = (f"ES/NQ={es_corr['corr']:.2f}" if es_corr.get("corr") else "ES/NQ=N/A")

    log.info(
        f"  [PRO] {vwap_str} | {pdh_str}"
        + (f" | {pwh_str}" if pwh_str else "")
        + f" | {or_str} | {corr_str}"
    )

    if es_corr.get("warning"):
        log.warning(f"  [PRO] {es_corr['warning']}")

    if or_data.get("breakout") != "NONE":
        log.info(f"  [PRO] ★ OPENING RANGE BREAKOUT {or_data['breakout']} — OR {orh:.0f}-{orl:.0f}")

    return {
        "levels":  levels,
        "es_corr": es_corr,
        "state":   state,
    }
