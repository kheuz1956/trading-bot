"""
KRONOS — Time-Cycle Intelligence Model
Analyse temporelle multi-dimensionnelle : cycles journaliers, hebdomadaires,
mensuels, calendrier économique et exposant de Hurst.

Références académiques :
  - Stock Trader's Almanac (Hirsch) — saisonnalité NASDAQ
  - Peters "Fractal Market Hypothesis" — exposant de Hurst (1994)
  - French (1980) "Day-of-week effects" — biais jour de la semaine
  - Opex / FOMC / NFP — effets calendrier bien documentés
"""

from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd

log = logging.getLogger("xtb_pw")

# ─── Données calendrier 2026 ──────────────────────────────────────────────────
# FOMC 2026 (dates annonce ~14h ET = 19h UTC)
_FOMC_DATES_2026 = {
    (1, 29), (3, 19), (5, 7), (6, 18),
    (7, 30), (9, 17), (11, 5), (12, 10),
}

# NFP = premier vendredi du mois  → calculé dynamiquement
# Opex = 3ème vendredi du mois    → calculé dynamiquement
# CPI : approximation (2ème ou 3ème mercredi — vérifier DXY/surveillance)

# ─── Saisonnalité mensuelle NASDAQ (biais directionnel historique) ────────────
# Source : Hirsch Stock Trader's Almanac, données NASDAQ 1971-2025
_MONTH_BIAS = {
    1:  +0.20,   # Janvier effect
    2:  -0.05,
    3:  -0.05,   # fin de trimestre → range
    4:  +0.15,   # Tax refund rally
    5:  -0.15,   # "Sell in May"
    6:  -0.05,
    7:  +0.10,   # Summer rally
    8:  -0.05,   # Thin markets
    9:  -0.25,   # Pire mois historique NASDAQ
    10: +0.05,   # Volatile mais recovery
    11: +0.20,   # Santa rally commence
    12: +0.15,   # Window dressing + Santa
}

# ─── Biais jour de la semaine ─────────────────────────────────────────────────
# Source : French (1980), études empiriques NASDAQ
_DOW_MULTIPLIER = {
    0: 0.85,   # Lundi — risque gap, repositionnement institutionnel
    1: 1.00,   # Mardi — neutre
    2: 1.10,   # Mercredi — meilleur jour trend (mid-week momentum)
    3: 1.00,   # Jeudi — neutre
    4: 0.90,   # Vendredi — profit-taking, réduction avant weekend
}


@dataclass
class KronosState:
    score: float              # -1.0 à +1.0 : biais directionnel temporel
    multiplier: float         # 0.5 – 1.3 : facteur sizing
    veto: bool                # True = aucun trade autorisé
    active_cycles: list[str]  # cycles détectés ce tick
    reason: str               # description principale
    hurst: float              # exposant de Hurst (0.2-0.9)
    hurst_regime: str         # TRENDING / RANDOM / MEAN_REVERTING


# ─── Exposant de Hurst (R/S Analysis, Peters 1994) ───────────────────────────

def _hurst_rs(prices: np.ndarray) -> float:
    """
    Calcule l'exposant de Hurst via l'analyse R/S.
    H > 0.6 → persistance / tendance forte
    H ≈ 0.5 → marche aléatoire
    H < 0.4 → anti-persistance / mean-reversion
    """
    if len(prices) < 20:
        return 0.5

    lags, rs_vals = [], []
    for lag in range(4, min(len(prices) // 3, 80), 4):
        n = (len(prices) // lag) * lag
        sub = prices[:n].reshape(-1, lag)
        rs_sub = []
        for s in sub:
            mean = s.mean()
            dev = np.cumsum(s - mean)
            r = dev.max() - dev.min()
            sd = s.std(ddof=1)
            if sd > 0:
                rs_sub.append(r / sd)
        if rs_sub:
            lags.append(lag)
            rs_vals.append(np.mean(rs_sub))

    if len(lags) < 5:
        return 0.5

    h, _ = np.polyfit(np.log(lags), np.log(rs_vals), 1)
    return float(np.clip(h, 0.2, 0.9))


# ─── Détection calendrier ─────────────────────────────────────────────────────

def _is_us_market_holiday(d: date) -> bool:
    """Jours fériés NYSE à date fixe (Jan 1, Jun 19, Jul 4, Dec 25) avec règle d'observation."""
    y = d.year
    observed = []
    for month, day in [(1, 1), (6, 19), (7, 4), (12, 25)]:
        base = date(y, month, day)
        if base.weekday() == 5:      # samedi → vendredi
            base -= timedelta(days=1)
        elif base.weekday() == 6:    # dimanche → lundi
            base += timedelta(days=1)
        observed.append(base)
    return d in observed


def _is_nfp_day(dt: datetime) -> bool:
    """Premier vendredi du mois (NFP) — décalé au jeudi si ce vendredi est férié NYSE."""
    if dt.day > 7:
        return False
    d = dt.date()
    if dt.weekday() == 4:   # Vendredi
        return not _is_us_market_holiday(d)
    if dt.weekday() == 3:   # Jeudi : NFP si le lendemain (vendredi ≤ 7) est férié
        next_day = d + timedelta(days=1)
        return next_day.day <= 7 and _is_us_market_holiday(next_day)
    return False


def _is_opex_friday(dt: datetime) -> bool:
    """3ème vendredi du mois = options expiration."""
    return dt.weekday() == 4 and 15 <= dt.day <= 21


def _is_fomc_day(dt: datetime) -> bool:
    return (dt.month, dt.day) in _FOMC_DATES_2026


def _is_quarter_end_week(dt: datetime) -> bool:
    """5 derniers jours calendaires du mois de fin de trimestre."""
    if dt.month not in (3, 6, 9, 12):
        return False
    last_day = calendar.monthrange(dt.year, dt.month)[1]
    return dt.day >= last_day - 4


def _is_last_trading_day_of_month(dt: datetime) -> bool:
    """Dernier jour du mois (window dressing final)."""
    last_day = calendar.monthrange(dt.year, dt.month)[1]
    return dt.day == last_day


def _is_cpi_week(dt: datetime) -> bool:
    """CPI publié ~2ème mercredi du mois — semaine de la publication."""
    return dt.weekday() == 2 and 8 <= dt.day <= 15


# ─── Fonction principale ──────────────────────────────────────────────────────

def evaluate_kronos(
    df_h1: Optional[pd.DataFrame],
    df_d1: Optional[pd.DataFrame],
    direction: str = "UNKNOWN",
    now: Optional[datetime] = None,
) -> KronosState:
    """
    Évalue les cycles temporels et retourne un KronosState.

    Parameters
    ----------
    df_h1       : OHLCV H1 (pour Hurst + contexte technique)
    df_d1       : OHLCV D1 (pour Hurst long-terme)
    direction   : signal actuel (LONG / SHORT / UNKNOWN)
    now         : datetime UTC (default = maintenant)
    """
    if now is None:
        now = datetime.now(timezone.utc)

    active_cycles: list[str] = []
    score = 0.0
    mult  = 1.0
    veto  = False
    veto_reason = ""

    # ── 1. Exposant de Hurst ──────────────────────────────────────────────────
    hurst = 0.5
    hurst_regime = "RANDOM"
    try:
        source = df_h1 if df_h1 is not None and len(df_h1) >= 50 else df_d1
        if source is not None and len(source) >= 20:
            prices = source["Close"].values.astype(float)
            hurst = _hurst_rs(prices)
            if hurst > 0.60:
                hurst_regime = "TRENDING"
                mult *= 1.12
                active_cycles.append(f"Hurst={hurst:.2f}→TREND")
                score += 0.10
            elif hurst < 0.42:
                hurst_regime = "MEAN_REVERTING"
                mult *= 0.75
                active_cycles.append(f"Hurst={hurst:.2f}→MR")
                score -= 0.10
            else:
                hurst_regime = "RANDOM"
    except Exception:
        pass

    # ── 2. Calendrier économique ──────────────────────────────────────────────
    if _is_nfp_day(now):
        veto = True
        veto_reason = "NFP Day — risque extrême, aucun trade"
        active_cycles.append("NFP_DAY")

    elif _is_fomc_day(now):
        # Veto avant l'annonce (14h ET = 19h UTC), demi-taille après
        if now.hour < 19:
            veto = True
            veto_reason = "FOMC annonce à 19h UTC — attente obligatoire"
            active_cycles.append("FOMC_PRE")
        else:
            mult *= 0.70
            active_cycles.append("FOMC_POST")
            score -= 0.05  # incertitude résiduelle

    elif _is_last_trading_day_of_month(now):
        veto = True
        veto_reason = "Dernier jour du mois — window dressing → chaos de clôture"
        active_cycles.append("MONTH_END")

    else:
        if _is_opex_friday(now):
            mult *= 0.80
            active_cycles.append("OPEX_FRIDAY")
            score -= 0.05

        if _is_quarter_end_week(now):
            mult *= 0.85
            active_cycles.append("QUARTER_END_WEEK")
            score -= 0.08

        if _is_cpi_week(now):
            mult *= 0.85
            active_cycles.append("CPI_WEEK")

    # ── 3. Biais jour de la semaine ───────────────────────────────────────────
    if not veto:
        dow = now.weekday()
        dow_mult = _DOW_MULTIPLIER.get(dow, 1.0)
        mult *= dow_mult
        dow_names = {0: "Lundi", 1: "Mardi", 2: "Mercredi", 3: "Jeudi", 4: "Vendredi"}
        active_cycles.append(f"{dow_names[dow]}({dow_mult:.2f}x)")
        if dow == 2:
            score += 0.10   # Mercredi = meilleur jour tendance
        elif dow == 0:
            score -= 0.08   # Lundi = gap risk

        # Vendredi après 14h UTC : demi-taille (liquidité qui baisse)
        if dow == 4 and now.hour >= 14:
            mult *= 0.85
            active_cycles.append("Vendredi_PM")

    # ── 4. Saisonnalité mensuelle ─────────────────────────────────────────────
    if not veto:
        month_bias = _MONTH_BIAS.get(now.month, 0.0)
        score += month_bias

        # Aligner biais mensuel avec la direction du signal
        if direction == "LONG" and month_bias > 0:
            mult *= 1.0 + month_bias * 0.5   # LONG en mois haussier → boost
        elif direction == "SHORT" and month_bias < 0:
            mult *= 1.0 + abs(month_bias) * 0.5  # SHORT en mois baissier → boost
        elif direction == "LONG" and month_bias < -0.15:
            mult *= 0.80   # LONG en Septembre ou mois très baissier → réduction forte
        elif direction == "SHORT" and month_bias > 0.15:
            mult *= 0.85   # SHORT en mois très haussier → réduction

        month_names = {
            1:"Jan", 2:"Fév", 3:"Mar", 4:"Avr", 5:"Mai", 6:"Jun",
            7:"Jul", 8:"Aoû", 9:"Sep", 10:"Oct", 11:"Nov", 12:"Déc"
        }
        active_cycles.append(f"{month_names[now.month]}(bias{month_bias:+.2f})")

    # ── 5. Semaine du mois ────────────────────────────────────────────────────
    if not veto:
        week_of_month = (now.day - 1) // 7 + 1  # 1-4
        if week_of_month == 1:
            mult *= 1.05
            active_cycles.append("Sem1(début_mois)")
        elif week_of_month == 4:
            mult *= 0.90
            active_cycles.append("Sem4(fin_mois)")

    # ── 6. Normalisation finale ───────────────────────────────────────────────
    mult  = round(max(0.40, min(1.30, mult)), 3)
    score = round(max(-1.0, min(1.0, score)), 3)

    if veto:
        mult = 0.0

    reason = veto_reason if veto else (
        f"{'Tailwind' if score >= 0.10 else 'Headwind' if score <= -0.10 else 'Neutre'} "
        f"| score={score:+.2f} | cycles={len(active_cycles)}"
    )

    return KronosState(
        score=score,
        multiplier=mult,
        veto=veto,
        active_cycles=active_cycles,
        reason=reason,
        hurst=round(hurst, 3),
        hurst_regime=hurst_regime,
    )


def kronos_summary(k: KronosState) -> str:
    icons = {"TRENDING": "^TREND", "MEAN_REVERTING": "~MR", "RANDOM": "~RW"}
    icon = "VETO" if k.veto else icons.get(k.hurst_regime, "~")
    return (
        f"{icon} score={k.score:+.2f} | mult={k.multiplier:.2f}x "
        f"| Hurst={k.hurst:.2f}({k.hurst_regime}) "
        f"| [{', '.join(k.active_cycles)}]"
    )
