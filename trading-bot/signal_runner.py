#!/usr/bin/env python3
"""
Signal Runner — Mode autonome (sans browser, sans WebSocket XTB)
Génère des signaux PRO toutes les 5 min et les logue.
Exécution des ordres : manuelle via XStation5 (Claude in Chrome).

Lancer : python signal_runner.py
Log    : signal_runner.log
"""

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import config
from strategy_pro import load_mtf, generate_pro_signal, print_pro_signal
from market_intelligence import MarketIntelligenceEngine
from news_surveillance import NewsSurveillanceEngine
from jesse_adapter import get_market_regime, get_var_estimate, validate_sl_with_monte_carlo, JESSE_MCP_AVAILABLE
from trading_library import full_library_assessment, SteenbargerPerformanceTracker

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("signal_runner.log", encoding="utf-8"),
        logging.FileHandler("xtb_bot_playwright.log", encoding="utf-8"),  # monitor existant
    ],
)
log = logging.getLogger("xtb_pw")

STATE_FILE = Path(__file__).parent / "bot_state.json"


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(d: dict):
    STATE_FILE.write_text(json.dumps(d, indent=2), encoding="utf-8")


def run_scan():
    now = datetime.now(timezone.utc).strftime("%H:%M GMT")
    log.info(f"── SCAN {now} " + "─" * 38)

    state = load_state()
    consec = state.get("consecutive_losses", 0)
    cb_until = state.get("circuit_breaker_until", 0)

    # Circuit breaker
    if time.time() < cb_until:
        rem = int(cb_until - time.time())
        log.info(f"  [CIRCUIT BREAKER] Pause — {rem//60}min {rem%60}s restantes")
        return

    # Position déjà ouverte ?
    if state.get("entry_price"):
        side  = state.get("trade_side", "?")
        entry = state.get("entry_price", 0)
        log.info(f"  Position {side}@{entry:.0f} déjà ouverte — pas de nouveau trade")
        return

    # Surveillance marché
    try:
        import asyncio
        mi = MarketIntelligenceEngine()
        mi_result = asyncio.run(mi.analyze())
        if mi_result and mi_result.risk_score <= -0.3:
            log.info(f"  [SURVEILLANCE] RISK_OFF (score={mi_result.risk_score:.2f}) — prudence")
    except Exception:
        pass

    # Signal MTF
    log.info("  Chargement MTF (yfinance)…")
    try:
        mtf = load_mtf()
        sig = generate_pro_signal(mtf)
        print_pro_signal(sig)
    except Exception as e:
        log.error(f"  Erreur génération signal: {e}")
        return

    if sig.direction == "SKIP":
        return

    # ── Filtre Trading Library (5 livres) ────────────────────────────────────
    try:
        signal_data = {
            "direction": sig.direction,
            "d1_bias": sig.d1_bias if hasattr(sig, 'd1_bias') else "NEUTRE",
            "h1_signal": sig.direction,
            "confluences_count": len(sig.confluences) if hasattr(sig, 'confluences') else 0,
            "rsi": getattr(sig, 'rsi', 50),
            "atr": sig.atr,
            "d1_macd_hist": 0,
        }
        library_result = full_library_assessment(state, signal_data)
        if not library_result["can_trade"]:
            for reason in library_result["reasons"]:
                log.warning(f"  [LIBRARY] {reason}")
            log.info(f"  [LIBRARY] {library_result['quote']}")
            if library_result["steenbarger"]["status"] == "CIRCUIT_BREAKER":
                log.warning("  [LIBRARY] CIRCUIT BREAKER ACTIF — signal ignoré")
                return
    except Exception as e:
        log.debug(f"trading_library filter: {e}")

    # Anti-reentry — actif uniquement après un SL (pas après un TP profitable)
    last_entry  = state.get("last_entry_price")
    last_side   = state.get("last_trade_side")
    last_reason = state.get("last_close_reason", "tp")  # "tp" / "sl" / "manual"
    if last_side == sig.direction and last_entry and last_reason == "sl":
        if sig.direction == "LONG"  and sig.entry > last_entry:
            log.warning(f"  [ANTI-REENTRY] LONG bloqué après SL: {sig.entry:.0f} > {last_entry:.0f}")
            return
        if sig.direction == "SHORT" and sig.entry < last_entry:
            log.warning(f"  [ANTI-REENTRY] SHORT bloqué après SL: {sig.entry:.0f} < {last_entry:.0f}")
            return

    # ── Enrichissement Jesse-MCP ─────────────────────────────────────────────
    if JESSE_MCP_AVAILABLE:
        try:
            regime = get_market_regime("US100", "1h")
            if regime.get("available"):
                log.info(f"  [JESSE] Régime: {regime['regime']} (conf={regime['confidence']:.0%})")

            var = get_var_estimate("US100", config.VOLUME, sig.entry)
            if var.get("available") and var.get("var_usd"):
                log.info(f"  [JESSE] VaR 95%: {var['var_usd']:.2f} USD")

            mc = validate_sl_with_monte_carlo("US100", sig.entry, sig.sl, sig.tp2)
            if mc.get("available") and mc.get("tp_probability") is not None:
                log.info(f"  [JESSE] Monte Carlo TP prob: {mc['tp_probability']:.0%}")
                if mc["tp_probability"] < 0.40:
                    log.warning(f"  [JESSE] ⚠ Probabilité TP faible ({mc['tp_probability']:.0%}) — prudence")
        except Exception as e:
            log.debug(f"jesse-mcp enrichissement: {e}")

    # Alerte trade — exécution manuelle requise
    log.info("=" * 56)
    log.info(f"  *** SIGNAL ACTIONNABLE *** {sig.direction} Grade {sig.grade}")
    log.info(f"  Entry : {sig.entry}  |  SL : {sig.sl}  |  TP : {sig.tp2}")
    log.info(f"  R:R   : {sig.rr}    |  ATR: {sig.atr:.0f} pts")
    log.info(f"  >>> PLACER ORDRE SUR XSTATION5 <<<")
    log.info("=" * 56)


def main():
    log.info("=" * 56)
    log.info("  XTB US100 SIGNAL RUNNER — STRATEGY PRO")
    log.info(f"  Compte : DEMO | {config.SYMBOL}")
    log.info(f"  Scan   : {config.SCAN_INTERVAL_SEC}s | ADX min={config.ADX_MIN}")
    log.info("=" * 56)

    while True:
        t0 = time.monotonic()
        try:
            run_scan()
        except Exception as e:
            log.error(f"Erreur scan: {e}", exc_info=True)

        elapsed = time.monotonic() - t0
        wait    = max(0, config.SCAN_INTERVAL_SEC - elapsed)
        log.info(f"  ⏱  Prochain scan dans {wait:.0f}s\n")
        time.sleep(wait)


if __name__ == "__main__":
    main()
