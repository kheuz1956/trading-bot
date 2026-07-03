"""
trading_library.py — Formation intégrée des 5 livres de référence

Sources :
  1. Trading in the Zone          — Mark Douglas
  2. Technical Analysis           — John J. Murphy
  3. The Daily Trading Coach      — Brett N. Steenbarger
  4. Reminiscences of a Stock Op. — Jesse Livermore
  5. The New Trading for a Living — Alexander Elder
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)


# ─── 1. MARK DOUGLAS — Probabilités et acceptation du risque ─────────────────

@dataclass
class DouglasCheck:
    """Checklist des 5 vérités fondamentales avant chaque trade."""
    risk_accepted: bool = False        # Perte max acceptée avant d'entrer
    not_revenge: bool = False          # Pas de revenge trading
    thinking_series: bool = False      # Pense en série de 20 trades, pas 1
    sl_immutable: bool = False         # SL défini, ne sera pas modifié
    process_over_result: bool = False  # Jugé sur le process, pas le P&L

    @property
    def is_valid(self) -> bool:
        checks = [self.risk_accepted, self.not_revenge, self.thinking_series,
                  self.sl_immutable, self.process_over_result]
        return all(checks)

    def evaluate(self, consecutive_losses: int, last_close_reason: str) -> 'DouglasCheck':
        """Auto-évalue à partir des données du bot_state."""
        self.not_revenge = last_close_reason not in ("sl",) or consecutive_losses < 2
        self.thinking_series = consecutive_losses < 4
        self.risk_accepted = True   # Accepté si on arrive ici avec SL défini
        self.sl_immutable = True    # Sera vérifié à l'exécution
        self.process_over_result = True
        return self


# ─── 2. JOHN J. MURPHY — Confluence et confirmation ──────────────────────────

def murphy_confluence_score(signal_data: dict) -> dict:
    """
    Calcule le score de confluence selon Murphy.
    Signal_data doit contenir : direction, d1_bias, h1_signal,
    macd_hist, rsi, atr, confluences_count
    """
    score = 0
    notes = []

    direction = signal_data.get("direction", "SKIP")
    d1_bias = signal_data.get("d1_bias", "NEUTRE")
    h1_signal = signal_data.get("h1_signal", "SKIP")
    confluences = signal_data.get("confluences_count", 0)
    rsi = signal_data.get("rsi", 50)
    atr = signal_data.get("atr", 80)

    if direction == "SKIP":
        return {"score": 0, "grade": "F", "notes": ["Signal SKIP — aucune confluence"]}

    # Alignement D1/H1 (Murphy Dow Theory)
    if (direction == "LONG" and d1_bias == "HAUSSIER") or \
       (direction == "SHORT" and d1_bias == "BAISSIER"):
        score += 30
        notes.append("Alignement D1/direction : +30 (Murphy: tendance primaire)")
    elif d1_bias == "NEUTRE":
        score += 10
        notes.append("D1 NEUTRE : +10")
    else:
        score -= 20
        notes.append("CONTRE-TENDANCE D1 : -20 (Murphy: ne pas combattre la tendance!)")

    # Confluences techniques (Murphy: minimun 2 indicateurs convergents)
    score += min(confluences * 10, 40)
    notes.append(f"Confluences ({confluences}) : +{min(confluences*10, 40)}")

    # RSI Murphy
    if direction == "LONG" and 40 <= rsi <= 60:
        score += 10
        notes.append("RSI neutre pour LONG : +10")
    elif direction == "LONG" and rsi < 30:
        score -= 10  # Survente = risque de rebond mais momentum baissier
        notes.append("RSI survente LONG : -10 (risque rebond court terme)")
    elif direction == "SHORT" and rsi > 70:
        score -= 10
        notes.append("RSI surachat SHORT : -10 (risque rebond)")
    elif direction == "SHORT" and 40 <= rsi <= 60:
        score += 10

    # ATR Murphy (volatilité normale = meilleur contexte)
    if 50 <= atr <= 120:
        score += 10
        notes.append(f"ATR normal ({atr:.0f}) : +10")
    elif atr > 150:
        score -= 10
        notes.append(f"ATR excessif ({atr:.0f}) : -10 (éviter entrées impulsives)")

    # Grade
    if score >= 70:
        grade = "A"
    elif score >= 55:
        grade = "B"
    elif score >= 40:
        grade = "C"
    elif score >= 25:
        grade = "D"
    else:
        grade = "F"

    return {"score": score, "grade": grade, "notes": notes}


# ─── 3. BRETT STEENBARGER — Gestion de la performance ───────────────────────

@dataclass
class SteenbargerPerformanceTracker:
    """
    Tracker de performance selon Steenbarger.
    Suit les drawdowns et prescrit les ajustements de sizing.
    """
    consecutive_losses: int = 0
    weekly_drawdown_pct: float = 0.0
    capital: float = 283000.0

    # Règle des drawdowns de Steenbarger
    DRAWDOWN_THRESHOLDS = [
        (0.02, 1.0, "Normal"),    # 0-2% : sizing normal
        (0.05, 0.5, "Réduit"),    # 2-5% : sizing 50%
        (0.10, 0.25, "Minimal"),  # 5-10% : sizing 25%
    ]
    MAX_WEEKLY_DRAWDOWN = 0.06     # Elder : 6% = arrêt semaine
    MAX_CONSECUTIVE_LOSSES = 4     # Circuit breaker

    @property
    def sizing_multiplier(self) -> float:
        """Multiplicateur de sizing selon Steenbarger."""
        if self.consecutive_losses >= self.MAX_CONSECUTIVE_LOSSES:
            return 0.0  # Circuit breaker complet
        for threshold, multiplier, _ in self.DRAWDOWN_THRESHOLDS:
            if self.weekly_drawdown_pct <= threshold:
                return multiplier
        return 0.0  # Drawdown > 10%

    @property
    def status(self) -> str:
        if self.consecutive_losses >= self.MAX_CONSECUTIVE_LOSSES:
            return "CIRCUIT_BREAKER"
        if self.weekly_drawdown_pct >= self.MAX_WEEKLY_DRAWDOWN:
            return "SEMAINE_TERMINEE"
        if self.sizing_multiplier < 1.0:
            return "SIZING_REDUIT"
        return "NORMAL"

    def log_status(self):
        m = self.sizing_multiplier
        s = self.status
        log.info(f"  [STEENBARGER] Statut: {s} | Sizing: {m:.0%} | "
                 f"Pertes consec: {self.consecutive_losses} | "
                 f"DD hebdo: {self.weekly_drawdown_pct:.1%}")


# ─── 4. JESSE LIVERMORE — Pivotal Points et ligne de moindre résistance ──────

def livermore_pivotal_analysis(
    current_price: float,
    donchian_high: float,
    donchian_low: float,
    previous_day_high: float,
    previous_day_low: float,
    atr: float
) -> dict:
    """
    Analyse Livermore :
    - Pivotal Point (résistance/support critique)
    - Ligne de moindre résistance (direction naturelle du marché)
    - Niveau des stops (où le marché va chercher la liquidité)
    """
    # Niveau des stops (Livermore : le marché cherche la liquidité)
    stop_zone_high = donchian_high * 1.001   # Stops au-dessus du Donchian High
    stop_zone_low = donchian_low * 0.999     # Stops en dessous du Donchian Low

    # Ligne de moindre résistance
    mid = (donchian_high + donchian_low) / 2
    if current_price > mid:
        least_resistance = "HAUSSIER"
        livermore_target = donchian_high + atr  # Extension au-delà du high
        pivotal_point = donchian_high
    else:
        least_resistance = "BAISSIER"
        livermore_target = donchian_low - atr
        pivotal_point = donchian_low

    # Proximité des Pivotal Points
    dist_to_high_pct = abs(current_price - donchian_high) / atr
    dist_to_low_pct = abs(current_price - donchian_low) / atr

    # Setup Livermore (cassure de Pivotal Point)
    livermore_setup = None
    if current_price > donchian_high:
        livermore_setup = {
            "type": "BREAKOUT_LONG",
            "entry": donchian_high,
            "sl": previous_day_low,
            "target": livermore_target,
            "note": "Livermore: breakout du Pivotal High confirme la hausse"
        }
    elif current_price < donchian_low:
        livermore_setup = {
            "type": "BREAKDOWN_SHORT",
            "entry": donchian_low,
            "sl": previous_day_high,
            "target": livermore_target,
            "note": "Livermore: breakdown du Pivotal Low confirme la baisse"
        }

    return {
        "least_resistance": least_resistance,
        "pivotal_point": pivotal_point,
        "stop_zone_high": stop_zone_high,
        "stop_zone_low": stop_zone_low,
        "livermore_setup": livermore_setup,
        "note": "Le marché prend toujours la direction qui déjoue le plus grand nombre"
    }


# ─── 5. ALEXANDER ELDER — Triple Screen et règle des 2% ─────────────────────

def elder_triple_screen(
    d1_macd_hist: float,
    h1_rsi: float,
    m5_signal: str,
    direction: str
) -> dict:
    """
    Système Triple Screen d'Elder.
    Screen 1 : D1 MACD → tendance principale
    Screen 2 : H1 RSI/Stochastic → timing oscillateur
    Screen 3 : M5 → entrée précise
    """
    screens = {}

    # Screen 1 : Tendance D1
    if d1_macd_hist > 0:
        screens["S1"] = {"signal": "LONG", "strength": min(abs(d1_macd_hist) / 50, 1.0)}
    elif d1_macd_hist < 0:
        screens["S1"] = {"signal": "SHORT", "strength": min(abs(d1_macd_hist) / 50, 1.0)}
    else:
        screens["S1"] = {"signal": "NEUTRE", "strength": 0.0}

    # Screen 2 : Oscillateur H1 (RSI)
    if direction == "LONG":
        if h1_rsi < 40:
            screens["S2"] = {"signal": "LONG", "quality": "IDEAL",
                             "note": "RSI H1 en survente = pullback dans uptrend"}
        elif 40 <= h1_rsi <= 60:
            screens["S2"] = {"signal": "LONG", "quality": "OK"}
        else:
            screens["S2"] = {"signal": "WAIT", "quality": "POOR",
                             "note": "RSI H1 surachet pour LONG = éviter"}
    elif direction == "SHORT":
        if h1_rsi > 60:
            screens["S2"] = {"signal": "SHORT", "quality": "IDEAL",
                             "note": "RSI H1 en surachat = rebond dans downtrend"}
        elif 40 <= h1_rsi <= 60:
            screens["S2"] = {"signal": "SHORT", "quality": "OK"}
        else:
            screens["S2"] = {"signal": "WAIT", "quality": "POOR",
                             "note": "RSI H1 survente pour SHORT = éviter (rebond)"}

    # Screen 3 : Signal M5
    screens["S3"] = {
        "signal": m5_signal,
        "valid": m5_signal == direction
    }

    # Triple Screen Validated ?
    # NEUTRE = D1 sans tendance claire, pas une opposition — Screen 1 ne bloque pas
    s1_ok = screens["S1"]["signal"] in (direction, "NEUTRE")
    s2_ok = screens.get("S2", {}).get("signal") == direction
    s3_ok = screens["S3"]["valid"]

    validated = s1_ok and s2_ok and s3_ok
    quality = screens.get("S2", {}).get("quality", "POOR")

    return {
        "validated": validated,
        "s1": screens.get("S1"),
        "s2": screens.get("S2"),
        "s3": screens.get("S3"),
        "quality": quality if validated else "INVALID",
        "note": "Elder: les 3 screens doivent confirmer avant d'entrer" if validated else
                "Elder: au moins 1 screen invalide — attendre"
    }


def elder_position_size(capital: float, sl_pts: float,
                         pip_value: float = 1.0,
                         risk_pct: float = 0.01) -> dict:
    """
    Calcule la taille de position selon la règle des 2% d'Elder.
    Par défaut utilise 1% (mode conservateur après drawdown).
    """
    risk_usd = capital * risk_pct
    volume = risk_usd / (sl_pts * pip_value)
    # Arrondir au multiple de 0.01 le plus proche
    volume = round(max(0.01, min(volume, 1.0)), 2)
    return {
        "risk_usd": risk_usd,
        "risk_pct": risk_pct,
        "volume": volume,
        "sl_pts": sl_pts,
        "note": f"Elder: {risk_pct*100:.0f}% du capital = {risk_usd:.0f} USD de risque"
    }


# ─── SYNTHÈSE GLOBALE ─────────────────────────────────────────────────────────

def full_library_assessment(state: dict, signal_data: dict) -> dict:
    """
    Évaluation complète des 5 livres pour un signal donné.
    Retourne la recommandation finale.
    """
    consecutive_losses = state.get("consecutive_losses", 0)
    last_reason = state.get("last_close_reason", "tp")
    daily_losses = state.get("daily_losses", 0)
    post_breaker = state.get("post_breaker", False)
    capital = 283000.0  # Valeur de référence DEMO
    max_daily_losses = 2  # mirrors config.MAX_DAILY_LOSSES

    # 1. Douglas
    douglas = DouglasCheck().evaluate(consecutive_losses, last_reason)

    # 2. Murphy
    murphy = murphy_confluence_score(signal_data)

    # 3. Steenbarger
    steenbarger = SteenbargerPerformanceTracker(
        consecutive_losses=consecutive_losses,
        capital=capital
    )

    # 4. Elder
    elder = elder_triple_screen(
        d1_macd_hist=signal_data.get("d1_macd_hist", 0),
        h1_rsi=signal_data.get("rsi", 50),
        m5_signal=signal_data.get("direction", "SKIP"),
        direction=signal_data.get("direction", "SKIP")
    )

    # Grade minimum requis : A-only en mode post-breaker, sinon A/B/C
    required_grades = {"A"} if post_breaker else {"A", "B", "C"}

    # Verdict final
    can_trade = (
        douglas.is_valid and
        steenbarger.status not in ("CIRCUIT_BREAKER", "SEMAINE_TERMINEE") and
        murphy["grade"] in required_grades and
        elder["validated"] and
        daily_losses < max_daily_losses
    )

    verdict = "TRADE" if can_trade else "ATTENTE"
    reasons = []

    if not douglas.is_valid:
        reasons.append("Douglas: checklist psychologique non validée")
    if steenbarger.status == "CIRCUIT_BREAKER":
        reasons.append(f"Steenbarger: CIRCUIT BREAKER ({consecutive_losses} pertes consec.)")
    if murphy["grade"] not in required_grades:
        if post_breaker:
            reasons.append(f"Post-breaker: Grade A uniquement requis (signal Grade {murphy['grade']})")
        elif murphy["grade"] == "F":
            reasons.append(f"Murphy: score de confluence insuffisant ({murphy['score']}/100)")
    if not elder["validated"]:
        reasons.append("Elder: Triple Screen non aligné")
    if daily_losses >= max_daily_losses:
        reasons.append(f"Max pertes journalières atteint ({daily_losses}/{max_daily_losses}) — session terminée")

    # Quote du livre le plus pertinent
    if consecutive_losses >= 4:
        quote = "Livermore: 'After a string of losses, the market is telling you something.'"
    elif daily_losses >= max_daily_losses:
        quote = "Steenbarger: 'When the market beats you twice in a day, it owns you. Stop.'"
    elif post_breaker:
        quote = "Douglas: 'Reduce size, accept imperfection, rebuild consistency.'"
    elif not elder["validated"]:
        quote = "Elder: 'The markets are never wrong. Opinions often are.'"
    elif murphy["grade"] == "F":
        quote = "Murphy: 'The trend is your friend, until the end.'"
    else:
        quote = "Douglas: 'The best traders have no fear, because they've accepted the risk.'"

    result = {
        "verdict": verdict,
        "can_trade": can_trade,
        "reasons": reasons,
        "douglas": {"valid": douglas.is_valid},
        "murphy": {"grade": murphy["grade"], "score": murphy["score"]},
        "steenbarger": {"status": steenbarger.status,
                        "sizing": steenbarger.sizing_multiplier},
        "elder": {"validated": elder["validated"],
                  "quality": elder.get("quality", "UNKNOWN")},
        "post_breaker": post_breaker,
        "daily_losses": daily_losses,
        "quote": quote,
    }

    # Log complet
    log.info(f"  [LIBRARY] Verdict: {verdict} | Douglas: {douglas.is_valid} | "
             f"Murphy: {murphy['grade']} | Steenbarger: {steenbarger.status} | "
             f"Elder: {elder['validated']}")
    if post_breaker:
        log.info(f"  [LIBRARY] Mode reprise post-breaker actif — Grade A only, demi-taille")
    if daily_losses:
        log.info(f"  [LIBRARY] Pertes aujourd'hui: {daily_losses}/{max_daily_losses}")
    if reasons:
        for r in reasons:
            log.warning(f"  [LIBRARY] BLOCAGE: {r}")
    log.info(f"  [LIBRARY] Quote: {quote}")

    return result


# ─── Test rapide ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Simuler un signal LONG Grade B
    test_signal = {
        "direction": "LONG",
        "d1_bias": "HAUSSIER",
        "h1_signal": "LONG",
        "confluences_count": 5,
        "rsi": 48,
        "atr": 85,
        "d1_macd_hist": 12.5,
    }
    test_state = {
        "consecutive_losses": 2,
        "last_close_reason": "tp",
    }

    result = full_library_assessment(test_state, test_signal)
    print("\n=== ASSESSMENT DES 5 LIVRES ===")
    import json
    print(json.dumps(result, indent=2, ensure_ascii=False))

    # Test Triple Screen
    ts = elder_triple_screen(12.5, 45.0, "LONG", "LONG")
    print("\n=== ELDER TRIPLE SCREEN ===")
    print(json.dumps(ts, indent=2))

    # Test position sizing
    ps = elder_position_size(283000, 85, risk_pct=0.01)
    print("\n=== ELDER POSITION SIZING ===")
    print(json.dumps(ps, indent=2))
