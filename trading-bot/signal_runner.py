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
        mi = MarketIntelligenceEngine()
        mi_result = mi.analyze()
        if mi_result.risk_score <= -0.3:
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

    # Anti-reentry
    last_entry = state.get("last_entry_price")
    last_side  = state.get("last_trade_side")
    if last_side == sig.direction and last_entry:
        if sig.direction == "LONG"  and sig.entry > last_entry:
            log.warning(f"  [ANTI-REENTRY] LONG bloqué: {sig.entry:.0f} > {last_entry:.0f}")
            return
        if sig.direction == "SHORT" and sig.entry < last_entry:
            log.warning(f"  [ANTI-REENTRY] SHORT bloqué: {sig.entry:.0f} < {last_entry:.0f}")
            return

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
