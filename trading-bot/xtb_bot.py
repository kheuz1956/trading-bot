#!/usr/bin/env python3
"""
XTB US100 Trading Bot
Stratégie : Ichimoku (H1) + Donchian + RSI
API       : xStation5 WebSocket (xAPI)
Lancer    : python xtb_bot.py
"""

import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import websockets

import config
from strategy_pro import load_mtf, generate_pro_signal, print_pro_signal, ProSignal

# ═══════════════════════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("xtb_bot.log"),
    ],
)
log = logging.getLogger("xtb_bot")


# ═══════════════════════════════════════════════════════════════════════════════
# CLIENT API XTB (WebSocket xStation)
# ═══════════════════════════════════════════════════════════════════════════════
class XTBClient:
    _URLS = {
        True:  "wss://xapi.xtb.com:5124",   # demo
        False: "wss://xapi.xtb.com:5112",   # real
    }

    def __init__(self):
        self.url           = self._URLS[config.DEMO]
        self._ws           = None
        self._digits_cache: dict[str, int] = {}

    # ── Connexion / Auth ─────────────────────────────────────────────────────

    async def connect(self) -> None:
        self._ws = await websockets.connect(
            self.url, ping_interval=20, ping_timeout=15, close_timeout=5
        )
        log.info(f"WebSocket connecté → {self.url}")

    async def disconnect(self) -> None:
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def login(self) -> None:
        if not config.ACCOUNT_ID or not config.PASSWORD:
            raise ValueError("ACCOUNT_ID / PASSWORD manquants dans .env")
        await self._cmd("login", {
            "userId":   config.ACCOUNT_ID,
            "password": config.PASSWORD,
            "appName":  "ichimoku_bot",
        })
        log.info("Login XTB OK")

    # ── Commandes bas niveau ─────────────────────────────────────────────────

    async def _cmd(self, command: str, arguments: dict = {}) -> dict:
        payload = json.dumps({"command": command, "arguments": arguments})
        await self._ws.send(payload)
        raw  = await asyncio.wait_for(self._ws.recv(), timeout=15)
        resp = json.loads(raw)
        if not resp.get("status"):
            raise RuntimeError(f"xAPI [{command}] erreur: {resp.get('errorDescr', resp)}")
        return resp

    # ── Données marché ───────────────────────────────────────────────────────

    async def _digits(self, symbol: str) -> int:
        if symbol not in self._digits_cache:
            resp = await self._cmd("getSymbol", {"symbol": symbol})
            self._digits_cache[symbol] = resp["returnData"]["digits"]
        return self._digits_cache[symbol]

    async def get_candles(self, symbol: str, period_min: int, count: int) -> pd.DataFrame:
        digits   = await self._digits(symbol)
        divisor  = 10 ** digits
        start_ms = int((time.time() - count * period_min * 60) * 1000)
        resp     = await self._cmd("getChartLastRequest", {
            "info": {"period": period_min, "start": start_ms, "symbol": symbol}
        })
        rows = []
        for r in resp["returnData"]["rateInfos"]:
            o = r["open"] / divisor
            rows.append({
                "time":  datetime.fromtimestamp(r["time"] / 1000, tz=timezone.utc),
                "open":  o,
                "high":  o + r["high"]  / divisor,
                "low":   o + r["low"]   / divisor,
                "close": o + r["close"] / divisor,
                "vol":   r["vol"],
            })
        df = pd.DataFrame(rows).set_index("time").sort_index()
        log.info(f"  {len(df)} bougies {period_min}min chargées pour {symbol}")
        return df

    # ── Gestion des ordres ───────────────────────────────────────────────────

    async def get_open_trades(self) -> list[dict]:
        resp = await self._cmd("getTrades", {"openedOnly": True})
        return resp.get("returnData", [])

    async def get_balance_usd(self) -> float:
        resp = await self._cmd("getMarginLevel", {})
        return resp.get("returnData", {}).get("equity", 0.0)

    async def place_order(
        self, symbol: str, cmd: int, volume: float,
        price: float, sl: float, tp: float, comment: str = "bot"
    ) -> int:
        resp = await self._cmd("tradeTransaction", {"tradeTransInfo": {
            "cmd": cmd, "customComment": comment, "expiration": 0,
            "offset": 0, "order": 0, "price": price,
            "sl": sl, "symbol": symbol, "tp": tp,
            "type": 0, "volume": volume,
        }})
        oid = resp["returnData"]["order"]
        side = "BUY" if cmd == 0 else "SELL"
        log.info(f"  ✅ Ordre #{oid} | {side} {volume} {symbol} @ {price} | SL={sl} TP={tp}")
        return oid

    async def modify_sl_tp(
        self, order_id: int, symbol: str, cmd: int,
        volume: float, price: float, sl: float, tp: float
    ) -> None:
        await self._cmd("tradeTransaction", {"tradeTransInfo": {
            "cmd": cmd, "customComment": "bot_modify", "expiration": 0,
            "offset": 0, "order": order_id, "price": price,
            "sl": sl, "symbol": symbol, "tp": tp,
            "type": 3, "volume": volume,
        }})
        log.info(f"  ✏️  #{order_id} modifié → SL={sl} TP={tp}")

    async def close_partial(
        self, order_id: int, symbol: str, cmd: int,
        volume: float, price: float
    ) -> None:
        await self._cmd("tradeTransaction", {"tradeTransInfo": {
            "cmd": cmd, "customComment": "bot_partial", "expiration": 0,
            "offset": 0, "order": order_id, "price": price,
            "sl": 0.0, "symbol": symbol, "tp": 0.0,
            "type": 2, "volume": volume,
        }})
        log.info(f"  💰 Fermeture partielle #{order_id}: {volume} lots @ {price}")


# ═══════════════════════════════════════════════════════════════════════════════
# INDICATEURS TECHNIQUES
# ═══════════════════════════════════════════════════════════════════════════════

def calc_ichimoku(df: pd.DataFrame) -> pd.DataFrame:
    hi, lo = df["high"], df["low"]
    t  = (hi.rolling(config.TENKAN_PERIOD).max()   + lo.rolling(config.TENKAN_PERIOD).min())   / 2
    k  = (hi.rolling(config.KIJUN_PERIOD).max()    + lo.rolling(config.KIJUN_PERIOD).min())    / 2
    sa = ((t + k) / 2).shift(config.DISPLACEMENT)
    sb = ((hi.rolling(config.SENKOU_B_PERIOD).max() + lo.rolling(config.SENKOU_B_PERIOD).min()) / 2).shift(config.DISPLACEMENT)
    return pd.DataFrame({"tenkan": t, "kijun": k, "senkou_a": sa, "senkou_b": sb}, index=df.index)


def calc_donchian(df: pd.DataFrame) -> pd.DataFrame:
    upper  = df["high"].rolling(config.DONCHIAN_PERIOD).max()
    lower  = df["low"].rolling(config.DONCHIAN_PERIOD).min()
    middle = (upper + lower) / 2
    return pd.DataFrame({"upper": upper, "middle": middle, "lower": lower}, index=df.index)


def calc_rsi(close: pd.Series) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(com=config.RSI_PERIOD - 1, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=config.RSI_PERIOD - 1, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


# ═══════════════════════════════════════════════════════════════════════════════
# STRATÉGIE — SIGNAL + NIVEAUX
# ═══════════════════════════════════════════════════════════════════════════════

def generate_signal(df: pd.DataFrame) -> tuple[str, dict]:
    """
    Retourne (signal, snapshot)
    signal : 'LONG' | 'SHORT' | 'SKIP'

    Règles :
    SHORT → prix sous Kumo + TK baissier + prix < Tenkan + RSI < RSI_MAX
    LONG  → prix sur Kumo  + TK haussier + prix > Tenkan + RSI > RSI_MIN
    Dans Kumo → SKIP systématique
    """
    ichi = calc_ichimoku(df)
    rsi_ = calc_rsi(df["close"])

    # On utilise l'avant-dernière bougie (dernière fermée ; [-1] est en cours)
    idx = -2
    close    = df["close"].iloc[idx]
    tenkan   = ichi["tenkan"].iloc[idx]
    kijun    = ichi["kijun"].iloc[idx]
    senkou_a = ichi["senkou_a"].iloc[idx]
    senkou_b = ichi["senkou_b"].iloc[idx]
    rsi_val  = rsi_.iloc[idx]

    kumo_top = max(senkou_a, senkou_b)
    kumo_bot = min(senkou_a, senkou_b)
    in_kumo  = kumo_bot <= close <= kumo_top

    snap = {
        "close": close, "tenkan": tenkan, "kijun": kijun,
        "senkou_a": senkou_a, "senkou_b": senkou_b,
        "kumo_top": kumo_top, "kumo_bot": kumo_bot,
        "rsi": rsi_val, "in_kumo": in_kumo,
    }

    if in_kumo or any(v != v for v in [tenkan, kijun, senkou_a, senkou_b]):  # NaN guard
        return "SKIP", snap

    short_ok = (
        close    <  kumo_bot   # sous le nuage
        and tenkan  <  kijun      # TK cross baissier
        and close   <  tenkan     # prix sous Tenkan
        and rsi_val <= config.RSI_MAX
    )
    long_ok = (
        close    >  kumo_top   # au-dessus du nuage
        and tenkan  >  kijun      # TK cross haussier
        and close   >  tenkan     # prix au-dessus Tenkan
        and rsi_val >= config.RSI_MIN
    )

    if short_ok:
        return "SHORT", snap
    if long_ok:
        return "LONG", snap
    return "SKIP", snap


def calc_levels(signal: str, snap: dict) -> dict:
    """Entry, SL, TP1, TP2 avec R:R calculé."""
    close = snap["close"]
    buf   = config.SL_BUFFER_PTS

    if signal == "SHORT":
        entry = close
        sl    = round(snap["kumo_bot"] + buf, 2)   # stop au-dessus du bas du Kumo
        risk  = sl - entry
        tp1   = round(entry - risk,       2)        # R:R 1:1
        tp2   = round(entry - risk * 2.0, 2)        # R:R 1:2
    else:  # LONG
        entry = close
        sl    = round(snap["kumo_top"] - buf, 2)
        risk  = entry - sl
        tp1   = round(entry + risk,       2)
        tp2   = round(entry + risk * 2.0, 2)

    rr = round(abs(tp2 - entry) / max(risk, 0.01), 1)
    return {"entry": round(entry, 2), "sl": sl, "tp1": tp1, "tp2": tp2,
            "risk": round(risk, 2), "rr": f"1:{rr}"}


# ═══════════════════════════════════════════════════════════════════════════════
# BOT PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

STATE_FILE = Path(__file__).parent / "bot_state.json"


class TradingBot:
    def __init__(self):
        self.client        = XTBClient()
        self.daily_pnl     = 0.0
        self.equity_open   = None
        self._tp1_done: set[int] = set()
        # État persistant
        self._consecutive_losses: int   = 0
        self._circuit_breaker_until: float = 0.0
        self._last_entry_price: float | None = None
        self._last_trade_side: str | None    = None
        self._load_state()

    def _load_state(self):
        if STATE_FILE.exists():
            try:
                d = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                self._consecutive_losses = d.get("consecutive_losses", 0)
                self._last_entry_price   = d.get("last_entry_price")
                self._last_trade_side    = d.get("last_trade_side")
                log.info(f"État restauré: pertes_consec={self._consecutive_losses} "
                         f"last={self._last_trade_side}@{self._last_entry_price}")
            except Exception as e:
                log.warning(f"Lecture état échouée: {e}")

    def _save_state(self, extra: dict | None = None):
        d = {
            "consecutive_losses": self._consecutive_losses,
            "last_entry_price":   self._last_entry_price,
            "last_trade_side":    self._last_trade_side,
            **(extra or {}),
        }
        STATE_FILE.write_text(json.dumps(d, indent=2), encoding="utf-8")

    def _volume_for_grade(self, grade: str) -> float:
        """Volume dynamique selon le grade du signal."""
        factor = {"A+": config.VOLUME_A_PLUS, "A": config.VOLUME_A, "B": config.VOLUME_B}.get(grade, 1.0)
        return round(config.VOLUME * factor, 2)

    # ── Boucle principale ────────────────────────────────────────────────────

    async def run(self) -> None:
        log.info("=" * 56)
        log.info("  XTB US100 TRADING BOT — DÉMARRAGE")
        log.info(f"  Compte : {'DÉMO' if config.DEMO else '⚠️  RÉEL'} | {config.SYMBOL}")
        log.info(f"  Volume : {config.VOLUME} lots | Scan : {config.SCAN_INTERVAL_SEC}s")
        log.info(f"  Max perte/jour : {config.MAX_DAILY_LOSS_USD} USD")
        log.info("=" * 56)

        while True:
            try:
                await self.client.connect()
                await self.client.login()
                await self._main_loop()
            except (websockets.ConnectionClosed, ConnectionError, OSError) as e:
                log.warning(f"Connexion perdue: {e} — reconnexion dans 30s")
            except Exception as e:
                log.error(f"Erreur inattendue: {e}", exc_info=True)
            finally:
                await self.client.disconnect()
            await asyncio.sleep(30)

    async def _main_loop(self) -> None:
        # Init équité de référence
        self.equity_open = await self.client.get_balance_usd()
        log.info(f"Équité de départ: {self.equity_open:.2f} USD")

        while True:
            t0 = time.monotonic()
            await self._tick()
            elapsed = time.monotonic() - t0
            wait    = max(0, config.SCAN_INTERVAL_SEC - elapsed)
            log.info(f"  ⏱  Prochain scan dans {wait:.0f}s\n")
            await asyncio.sleep(wait)

    # ── Tick (analyse + action) ──────────────────────────────────────────────

    async def _tick(self) -> None:
        now = datetime.now(timezone.utc).strftime("%H:%M GMT")
        log.info(f"── SCAN {now} " + "─" * 40)

        # 1. Circuit breaker
        if time.time() < self._circuit_breaker_until:
            rem = int(self._circuit_breaker_until - time.time())
            log.info(f"  [CIRCUIT BREAKER] Pause active — {rem//60}min {rem%60}s restantes")
            return

        # 2. Vérification perte journalière
        equity = await self.client.get_balance_usd()
        self.daily_pnl = equity - (self.equity_open or equity)
        if self.daily_pnl <= -abs(config.MAX_DAILY_LOSS_USD):
            log.warning(f"  [DAILY GATE] perte jour = {self.daily_pnl:.2f}$ ≥ limite {config.MAX_DAILY_LOSS_USD}$ — stop")
            await asyncio.sleep(3600)
            return

        # 3. Positions ouvertes du bot
        all_trades = await self.client.get_open_trades()
        bot_trades = [
            t for t in all_trades
            if t.get("customComment", "").startswith("bot")
            and t.get("symbol") == config.SYMBOL
        ]

        # 4. Gérer position existante (breakeven / TP partiel / suivi)
        if bot_trades:
            await self._manage_position(bot_trades[0])
            return

        # Détecter fermeture de position (perte/gain) depuis le dernier tick
        # Si on avait un state "entry_price" mais plus de trade ouvert → clôturé
        state = {}
        if STATE_FILE.exists():
            try: state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            except Exception: pass
        if state.get("entry_price") and not bot_trades:
            # Position vient d'être fermée (SL/TP côté serveur)
            df_m15_live = await self.client.get_candles(config.SYMBOL, 5, 3)
            current = float(df_m15_live["close"].iloc[-1])
            side  = state.get("trade_side", "LONG")
            entry = float(state.get("entry_price", current))
            pnl   = (current - entry) if side == "LONG" else (entry - current)
            log.info(f"  Position {side}@{entry:.0f} fermée — P&L estimé: {pnl:+.0f} pts")
            if pnl < 0:
                self._consecutive_losses += 1
                self._last_entry_price   = entry
                self._last_trade_side    = side
                log.warning(f"  Perte #{self._consecutive_losses} consecutive(s)")
                if self._consecutive_losses >= 2:
                    self._circuit_breaker_until = time.time() + 1800
                    log.warning(f"  *** CIRCUIT BREAKER 30min ***")
            else:
                self._consecutive_losses = 0
            self._save_state({"entry_price": None, "trade_side": None, "tp1_done": False})
            return

        # 5. Générer signal PRO (strategy_pro + yfinance)
        log.info("  Chargement données MTF (yfinance)…")
        mtf = load_mtf()
        sig = generate_pro_signal(mtf)
        print_pro_signal(sig)

        if sig.direction == "SKIP":
            return

        # 6. Filtre anti-re-entrée (même direction après perte)
        if (self._last_trade_side == sig.direction
                and self._last_entry_price is not None
                and sig.direction == "LONG"
                and sig.entry > self._last_entry_price):
            log.warning(
                f"  [ANTI-REENTRY] LONG bloqué: entry {sig.entry:.0f} > "
                f"dernier SL {self._last_entry_price:.0f}"
            )
            return
        if (self._last_trade_side == sig.direction
                and self._last_entry_price is not None
                and sig.direction == "SHORT"
                and sig.entry < self._last_entry_price):
            log.warning(
                f"  [ANTI-REENTRY] SHORT bloqué: entry {sig.entry:.0f} < "
                f"dernier SL {self._last_entry_price:.0f}"
            )
            return

        # 7. Ouvrir le trade via API XTB
        volume = self._volume_for_grade(sig.grade)
        cmd    = 0 if sig.direction == "LONG" else 1
        log.info(
            f"  >> TRADE {sig.direction} | Grade {sig.grade} | Vol {volume}lots "
            f"| Entry={sig.entry} SL={sig.sl} TP={sig.tp2} | {sig.rr}"
        )
        order_id = await self.client.place_order(
            symbol  = config.SYMBOL,
            cmd     = cmd,
            volume  = volume,
            price   = sig.entry,
            sl      = sig.sl,
            tp      = sig.tp2,
            comment = f"bot_pro_{sig.grade}",
        )
        # Persister l'état du trade
        self._save_state({
            "entry_price": sig.entry,
            "trade_side":  sig.direction,
            "tp1_done":    False,
            "order_id":    order_id,
        })

    # ── Gestion de position ouverte ──────────────────────────────────────────

    async def _manage_position(self, trade: dict) -> None:
        order_id   = trade["order"]
        cmd        = trade["cmd"]          # 0=BUY 1=SELL
        open_price = trade["open_price"]
        sl         = trade["sl"]
        tp         = trade["tp"]
        volume     = trade["volume"]
        profit     = trade.get("profit", 0.0)

        # Prix actuel approximé depuis le profit et le volume
        # (plus simple : on relit les données)
        df = await self.client.get_candles(config.SYMBOL, 5, 5)
        current = df["close"].iloc[-1]

        pnl_pts = (current - open_price) if cmd == 0 else (open_price - current)
        log.info(f"  Position #{order_id} | {pnl_pts:+.1f} pts | P&L: {profit:+.2f} USD")

        # TP1 + Breakeven (une seule fois)
        if order_id not in self._tp1_done and pnl_pts >= config.BREAKEVEN_TRIGGER_PTS:
            close_vol = round(volume * config.TP1_CLOSE_RATIO, 2)
            log.info(f"  TP1 atteint (+{pnl_pts:.0f} pts) → fermeture {close_vol} lots")
            await self.client.close_partial(order_id, config.SYMBOL, cmd, close_vol, current)

            # Breakeven: SL déplacé au prix d'ouverture + petite marge favorable
            margin = 5 if cmd == 0 else -5
            new_sl = round(open_price + margin, 2)
            remain = round(volume - close_vol, 2)
            await self.client.modify_sl_tp(order_id, config.SYMBOL, cmd, remain, current, new_sl, tp)
            self._tp1_done.add(order_id)
            log.info(f"  Breakeven activé → SL={new_sl}")

    # ── Log ──────────────────────────────────────────────────────────────────

    def _log_signal(self, signal: str, snap: dict) -> None:
        icon = {"LONG": "🟢", "SHORT": "🔴", "SKIP": "⚪"}[signal]
        log.info(
            f"  {icon} {signal:5s} | Prix={snap['close']:.2f} | "
            f"Tenkan={snap['tenkan']:.2f} | Kijun={snap['kijun']:.2f} | "
            f"Kumo={snap['kumo_bot']:.2f}–{snap['kumo_top']:.2f} | "
            f"RSI={snap['rsi']:.1f} | InKumo={snap['in_kumo']}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    bot = TradingBot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        log.info("Bot arrêté (Ctrl+C).")
