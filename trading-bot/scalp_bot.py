#!/usr/bin/env python3
"""
scalp_bot.py — Bot de scalping automatisé 40+ trades | Objectif $2000
Stratégie : Scalp M1/M5 avec EMA + RSI + momentum
API : XTB WebSocket xAPI (DEMO)
"""
import asyncio, json, logging, sys, time, math
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import websockets

# ── Config ────────────────────────────────────────────────────────────────────
from dotenv import load_dotenv
import os
load_dotenv()

ACCOUNT_ID  = os.getenv("XTB_ACCOUNT_ID", "19975796")
PASSWORD    = os.getenv("XTB_PASSWORD", "")
WS_URL      = "wss://xapi.xtb.com:5124"
SYMBOL      = "US100"
VOLUME      = 0.05       # 1 USD/pt — risque minimal
TARGET_USD  = 2000.0     # objectif session
SL_MULT     = 1.5        # SL = 1.5 × ATR
TP_MULT     = 2.0        # TP = 2.0 × ATR (R:R 1.33:1)
MIN_TRADES  = 40         # minimum 40 opérations
SCAN_SEC    = 30         # scan toutes les 30 secondes

STATE_FILE  = Path(__file__).parent / "bot_state.json"
LOG_FILE    = Path(__file__).parent / "scalp_bot.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_FILE)),
    ],
)
log = logging.getLogger("scalp")

# ── État session ──────────────────────────────────────────────────────────────
class Session:
    def __init__(self):
        self.pnl = 0.0
        self.trades = 0
        self.wins = 0
        self.losses = 0
        self.open_pos = None  # {'order': int, 'side': str, 'entry': float, 'sl': float, 'tp': float}
        self.start_time = time.time()

    @property
    def duration_min(self): return (time.time() - self.start_time) / 60
    @property
    def win_rate(self): return self.wins / max(self.trades, 1) * 100

    def log_status(self):
        log.info(f"SESSION: {self.trades} trades | P&L: {self.pnl:+.2f} USD | "
                 f"WR: {self.win_rate:.0f}% | {self.duration_min:.0f}min")

# ── Client XTB WebSocket ──────────────────────────────────────────────────────
class XTBClient:
    def __init__(self, url: str):
        self.url = url
        self.ws = None
        self._cmd_id = 1
        self.stream_sid = None

    async def connect(self):
        self.ws = await websockets.connect(self.url, ping_interval=20)
        log.info(f"Connecté à {self.url}")

    async def send(self, cmd: str, args: dict = None) -> dict:
        payload = {"command": cmd}
        if args:
            payload["arguments"] = args
        payload["customTag"] = str(self._cmd_id)
        self._cmd_id += 1
        await self.ws.send(json.dumps(payload))
        resp = json.loads(await self.ws.recv())
        return resp

    async def login(self, account: str, password: str) -> bool:
        r = await self.send("login", {"userId": account, "password": password})
        ok = r.get("status", False)
        if ok:
            self.stream_sid = r.get("streamSessionId", "")
            log.info(f"Login OK — streamSessionId: {self.stream_sid[:8]}...")
        else:
            log.error(f"Login FAILED: {r}")
        return ok

    async def get_symbol(self, symbol: str) -> dict:
        r = await self.send("getSymbol", {"symbol": symbol})
        return r.get("returnData", {})

    async def get_candles(self, symbol: str, period: int, count: int) -> list:
        """period: 1=M1, 5=M5, 15=M15, 60=H1"""
        import time as t
        now = int(t.time() * 1000)
        start = now - count * period * 60000 * 2
        r = await self.send("getChartRangeRequest", {
            "info": {"symbol": symbol, "period": period,
                     "start": start, "end": now, "ticks": count}
        })
        data = r.get("returnData", {})
        return data.get("rateInfos", [])

    async def open_trade(self, symbol: str, side: int, volume: float,
                          price: float, sl: float, tp: float) -> dict:
        """side: 0=BUY, 1=SELL"""
        r = await self.send("tradeTransaction", {
            "tradeTransInfo": {
                "cmd": side,
                "symbol": symbol,
                "volume": volume,
                "price": price,
                "sl": sl,
                "tp": tp,
                "type": 0,  # OPEN
                "comment": f"scalp_{datetime.utcnow().strftime('%H%M%S')}"
            }
        })
        return r

    async def close_trade(self, symbol: str, order: int, side: int,
                           volume: float, price: float) -> dict:
        """close_side = 0 if was SELL (buy to close), 1 if was BUY (sell to close)"""
        close_cmd = 1 if side == 0 else 0  # inverse
        r = await self.send("tradeTransaction", {
            "tradeTransInfo": {
                "cmd": close_cmd,
                "symbol": symbol,
                "order": order,
                "volume": volume,
                "price": price,
                "sl": 0,
                "tp": 0,
                "type": 2,  # CLOSE
                "comment": "scalp_close"
            }
        })
        return r

    async def get_trades(self) -> list:
        r = await self.send("getTrades", {"openedOnly": True})
        return r.get("returnData", [])

    async def get_balance(self) -> float:
        r = await self.send("getMarginLevel", {})
        d = r.get("returnData", {})
        return d.get("balance", 0.0)

# ── Indicateurs ───────────────────────────────────────────────────────────────
def candles_to_arrays(candles: list) -> tuple:
    """Retourne (opens, highs, lows, closes)"""
    if not candles:
        return [], [], [], []
    opens  = [c['open'] / 100 for c in candles]
    closes = [c['open'] / 100 + c['close'] / 100 for c in candles]
    highs  = [c['open'] / 100 + c['high'] / 100 for c in candles]
    lows   = [c['open'] / 100 + c['low'] / 100 for c in candles]
    return opens, highs, lows, closes

def ema(data: list, period: int) -> list:
    if len(data) < period:
        return [data[-1]] * len(data)
    result, k = [], 2 / (period + 1)
    result.append(sum(data[:period]) / period)
    for d in data[period:]:
        result.append(d * k + result[-1] * (1 - k))
    return [result[0]] * (period - 1) + result

def rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i+1] - closes[i] for i in range(len(closes)-1)]
    gains = [max(d, 0) for d in deltas[-period:]]
    losses = [max(-d, 0) for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)

def atr(highs: list, lows: list, closes: list, period: int = 14) -> float:
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i-1]),
                 abs(lows[i] - closes[i-1]))
        trs.append(tr)
    if not trs:
        return 20.0
    return sum(trs[-period:]) / min(len(trs), period)

# ── Stratégie scalp ───────────────────────────────────────────────────────────
def generate_scalp_signal(candles_m5: list, candles_m1: list) -> dict:
    """
    Signal scalp basé sur :
    - EMA8 vs EMA21 (M5) → direction
    - RSI M1 : 30-70 filtre
    - Momentum : 3 dernières bougies M1 alignées
    Retourne {'action': 'LONG'/'SHORT'/'SKIP', 'atr': float}
    """
    if len(candles_m5) < 30 or len(candles_m1) < 20:
        return {'action': 'SKIP', 'atr': 20.0}

    _, hm5, lm5, cm5 = candles_to_arrays(candles_m5)
    _, hm1, lm1, cm1 = candles_to_arrays(candles_m1)

    if not cm5 or not cm1:
        return {'action': 'SKIP', 'atr': 20.0}

    ema8  = ema(cm5, 8)[-1]
    ema21 = ema(cm5, 21)[-1]
    rsi_m1 = rsi(cm1, 14)
    atr_val = atr(hm5, lm5, cm5, 14)

    # Biais directionnel
    bull = ema8 > ema21
    bear = ema8 < ema21

    # Momentum M1 : 3 dernières bougies
    last3 = cm1[-3:]
    mom_bull = last3[-1] > last3[0]  # montée globale
    mom_bear = last3[-1] < last3[0]  # descente globale

    action = 'SKIP'
    if bull and mom_bull and 30 < rsi_m1 < 65:
        action = 'LONG'
    elif bear and mom_bear and 35 < rsi_m1 < 70:
        action = 'SHORT'

    return {'action': action, 'atr': atr_val, 'rsi': rsi_m1,
            'ema8': ema8, 'ema21': ema21, 'price': cm5[-1]}

# ── Boucle principale ─────────────────────────────────────────────────────────
async def main():
    session = Session()
    client = XTBClient(WS_URL)

    log.info("=" * 60)
    log.info(f"  SCALP BOT — Objectif {TARGET_USD} USD | Min {MIN_TRADES} trades")
    log.info(f"  Volume: {VOLUME} lots | SL: {SL_MULT}×ATR | TP: {TP_MULT}×ATR")
    log.info("=" * 60)

    await client.connect()
    if not await client.login(ACCOUNT_ID, PASSWORD):
        log.error("Login impossible — arrêt")
        return

    sym_info = await client.get_symbol(SYMBOL)
    spread = sym_info.get("spreadRaw", 1.5)
    log.info(f"Spread actuel: {spread:.2f} pts")

    balance_start = await client.get_balance()
    log.info(f"Balance départ: {balance_start:.2f} USD")

    consecutive_skip = 0

    while True:
        try:
            # Vérifier objectif
            balance = await client.get_balance()
            session.pnl = balance - balance_start
            session.log_status()

            if session.pnl >= TARGET_USD and session.trades >= MIN_TRADES:
                log.info(f"OBJECTIF ATTEINT ! P&L={session.pnl:.2f} USD après {session.trades} trades")
                break

            # Vérifier positions ouvertes
            open_trades = await client.get_trades()
            if open_trades:
                pos = open_trades[0]
                profit = pos.get('profit', 0)
                log.info(f"  Position ouverte: profit={profit:.2f} USD")
                # Fermeture automatique si gain ≥ TP (géré par SL/TP serveur)
                await asyncio.sleep(SCAN_SEC)
                continue

            # Plus de position ouverte = trade clôturé → compter
            if session.open_pos:
                log.info(f"  Trade #{session.trades} clôturé")
                session.open_pos = None

            # Générer signal
            candles_m5 = await client.get_candles(SYMBOL, 5, 50)
            candles_m1 = await client.get_candles(SYMBOL, 1, 30)
            sig = generate_scalp_signal(candles_m5, candles_m1)

            log.info(f"Signal: {sig['action']} | RSI={sig.get('rsi', 0):.1f} | ATR={sig['atr']:.1f}")

            if sig['action'] == 'SKIP':
                consecutive_skip += 1
                if consecutive_skip >= 3:
                    log.info("  3 SKIPs consécutifs — pause 60s")
                    await asyncio.sleep(60)
                    consecutive_skip = 0
                else:
                    await asyncio.sleep(SCAN_SEC)
                continue

            consecutive_skip = 0
            price = sig['price']
            atr_val = max(sig['atr'], 10.0)  # minimum 10 pts
            sl_dist = round(atr_val * SL_MULT, 2)
            tp_dist = round(atr_val * TP_MULT, 2)

            if sig['action'] == 'LONG':
                sl = round(price - sl_dist, 2)
                tp = round(price + tp_dist, 2)
                side = 0
            else:  # SHORT
                sl = round(price + sl_dist, 2)
                tp = round(price - tp_dist, 2)
                side = 1

            log.info(f"  TRADE {sig['action']}: Entry={price:.2f} SL={sl:.2f} TP={tp:.2f}")
            r = await client.open_trade(SYMBOL, side, VOLUME, price, sl, tp)

            if r.get("status"):
                order = r.get("returnData", {}).get("order", 0)
                session.trades += 1
                session.open_pos = {'order': order, 'side': side, 'entry': price, 'sl': sl, 'tp': tp}
                log.info(f"  ✅ Ordre #{order} ouvert | Trade {session.trades}/{MIN_TRADES}")
            else:
                log.warning(f"  ❌ Ordre rejeté: {r}")

            await asyncio.sleep(SCAN_SEC)

        except websockets.ConnectionClosed:
            log.warning("WebSocket fermé — reconnexion...")
            await client.connect()
            await client.login(ACCOUNT_ID, PASSWORD)
        except Exception as e:
            log.error(f"Erreur: {e}", exc_info=True)
            await asyncio.sleep(10)

    balance_end = await client.get_balance()
    log.info(f"\n{'='*60}")
    log.info(f"  SESSION TERMINÉE")
    log.info(f"  Trades: {session.trades} | Wins: {session.wins} | WR: {session.win_rate:.0f}%")
    log.info(f"  P&L: {session.pnl:+.2f} USD")
    log.info(f"  Balance finale: {balance_end:.2f} USD")
    log.info(f"{'='*60}")

if __name__ == "__main__":
    asyncio.run(main())
