"""
auto_trade.py — Automation vers $2000
Surveille le log signal_runner, extrait les signaux ACTIONNABLE,
et exécute les ordres via XTB WebSocket API.
"""
import json, re, time, logging, subprocess
from pathlib import Path
from datetime import datetime

LOG = Path(r"C:\Users\CHEIKH MBACKE DIENG\Documents\CLAUDE\CODE\.claude\worktrees\nervous-margulis-1c105b\trading-bot\xtb_bot_playwright.log")
STATE = Path(r"C:\Users\CHEIKH MBACKE DIENG\Documents\CLAUDE\CODE\.claude\worktrees\nervous-margulis-1c105b\trading-bot\bot_state.json")
TARGET_USD = 2000.0
BASELINE_BALANCE = 283101.23  # balance avant session

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger(__name__)

def load_state():
    try:
        return json.loads(STATE.read_text())
    except:
        return {}

def get_session_pnl(balance: float) -> float:
    return balance - BASELINE_BALANCE

def parse_last_signal(log_path: Path) -> dict | None:
    """Lit les dernières lignes du log pour extraire le dernier signal ACTIONNABLE."""
    try:
        lines = log_path.read_text(encoding='utf-8', errors='replace').splitlines()
    except:
        return None

    # Chercher le dernier bloc ACTIONNABLE
    entry = sl = tp = direction = grade = None
    for line in reversed(lines[-100:]):
        if 'SIGNAL ACTIONNABLE' in line and not entry:
            m = re.search(r'(LONG|SHORT)\s+Grade\s+(\w+)', line)
            if m:
                direction = m.group(1)
                grade = m.group(2)
        if 'Entry :' in line and not entry:
            m = re.search(r'Entry\s*:\s*([\d.]+)', line)
            if m: entry = float(m.group(1))
        if 'SL    :' in line and not sl:
            m = re.search(r'SL\s*:\s*([\d.]+)', line)
            if m: sl = float(m.group(1))
        if 'TP    :' in line and not tp:
            m = re.search(r'TP\s*:\s*([\d.]+)', line)
            if m: tp = float(m.group(1))
        if entry and sl and tp and direction:
            break

    if entry and sl and tp and direction:
        return {'direction': direction, 'grade': grade, 'entry': entry, 'sl': sl, 'tp': tp}
    return None

def monitor_and_notify():
    """Boucle principale : surveille le log et notifie dès signal."""
    log.info(f"Démarrage auto_trade — objectif {TARGET_USD} USD")
    last_signal_time = None
    last_line_count = 0

    while True:
        # Vérifier progression vers objectif
        state = load_state()

        # Lire le log
        try:
            lines = LOG.read_text(encoding='utf-8', errors='replace').splitlines()
        except:
            time.sleep(5)
            continue

        # Nouveau contenu ?
        if len(lines) != last_line_count:
            last_line_count = len(lines)
            recent = '\n'.join(lines[-50:])

            # Signal ACTIONNABLE présent ?
            if 'SIGNAL ACTIONNABLE' in recent and '>>> PLACER ORDRE' in recent:
                signal = parse_last_signal(LOG)
                if signal:
                    # Éviter de répéter le même signal
                    sig_key = f"{signal['entry']}-{signal['sl']}-{signal['tp']}"
                    if sig_key != last_signal_time:
                        last_signal_time = sig_key
                        log.info(f"SIGNAL DÉTECTÉ: {signal['direction']} Grade {signal['grade']}")
                        log.info(f"  Entry: {signal['entry']} | SL: {signal['sl']} | TP: {signal['tp']}")
                        # Écrire dans un fichier de trigger pour Claude
                        trigger = {
                            'signal': signal,
                            'timestamp': datetime.utcnow().isoformat(),
                            'action': 'EXECUTE_TRADE'
                        }
                        Path(r"C:\Users\CHEIKH MBACKE DIENG\Documents\CLAUDE\CODE\.claude\worktrees\nervous-margulis-1c105b\trading-bot\trade_trigger.json").write_text(
                            json.dumps(trigger, indent=2)
                        )
                        log.info("  → trade_trigger.json écrit")

        time.sleep(10)

if __name__ == '__main__':
    monitor_and_notify()
