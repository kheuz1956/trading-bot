#!/usr/bin/env python3
"""
Signal Runner — Mode autonome (sans browser, sans WebSocket XTB)
Génère des signaux PRO toutes les 5 min et les logue.
Exécution des ordres : manuelle via XStation5 (Claude in Chrome).

Lancer : python signal_runner.py
Log    : signal_runner.log
"""

import asyncio as _asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

try:
    import websockets as _websockets
    _WS_AVAILABLE = True
except ImportError:
    _WS_AVAILABLE = False

# XTB xAPI nécessite une inscription séparée — désactivé jusqu'à activation du compte
_API_ENABLED = False

try:
    import yfinance as yf
    _YF_AVAILABLE = True
except ImportError:
    _YF_AVAILABLE = False

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import config
from strategy_pro import load_mtf, generate_pro_signal, print_pro_signal
from market_intelligence import MarketIntelligenceEngine
from news_surveillance import NewsSurveillanceEngine
from smart_money import SmartMoneyEngine as _SmartMoneyEngine

_smart_money_engine = _SmartMoneyEngine()
from jesse_adapter import get_market_regime, get_var_estimate, validate_sl_with_monte_carlo, JESSE_MCP_AVAILABLE
from trading_library import full_library_assessment, SteenbargerPerformanceTracker
from pro_routines import run_pro_routine, score_key_levels
from institutional_signals import get_institutional_filter, log_institutional_context

# ── Logging ───────────────────────────────────────────────────────────────────
_LOG_DIR = Path(__file__).resolve().parent  # absolute: logs always land beside this file

_handlers = [
    # Rotating: cap each log at 2 MB x 2 backups (~6 MB max) to prevent the
    # unbounded growth that bloated Claude sessions into the 1M-context tier.
    RotatingFileHandler(_LOG_DIR / "signal_runner.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8"),
    RotatingFileHandler(_LOG_DIR / "xtb_bot_playwright.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8"),
]
# stdout handler only when stdout is real (interactive). When launched detached/hidden,
# sys.stdout can be None or a broken handle whose write() blocks and freezes the whole loop.
if sys.stdout is not None and getattr(sys.stdout, "isatty", lambda: False)():
    _handlers.insert(0, logging.StreamHandler(sys.stdout))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=_handlers,
    force=True,  # imported modules (jesse_adapter, ...) configure logging first; force our handlers
)
log = logging.getLogger("xtb_pw")

STATE_FILE         = Path(__file__).parent / "bot_state.json"
TRADES_JOURNAL_FILE = Path(__file__).parent / "trades_history.jsonl"

# Module-level state tracked between scans for transition detection
_prev_entry_price        = None
_prev_consecutive_losses = None
_last_signal_key         = None   # dedup: évite de répéter le même ACTIONNABLE en boucle


# ═══════════════════════════════════════════════════════════════════════════════
# XTB API CLIENT — Auto-exécution WebSocket
# ═══════════════════════════════════════════════════════════════════════════════

class _XTBClient:
    _URL = "wss://xapi.xtb.com:5124"  # DEMO

    def __init__(self):
        self._ws = None

    async def connect(self):
        self._ws = await _websockets.connect(
            self._URL, ping_interval=20, ping_timeout=15, close_timeout=5
        )

    async def disconnect(self):
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def _cmd(self, command: str, arguments: dict = {}) -> dict:
        payload = json.dumps({"command": command, "arguments": arguments})
        await self._ws.send(payload)
        raw  = await _asyncio.wait_for(self._ws.recv(), timeout=15)
        resp = json.loads(raw)
        if not resp.get("status"):
            raise RuntimeError(f"xAPI [{command}]: {resp.get('errorDescr', resp)}")
        return resp

    async def login(self):
        if not config.ACCOUNT_ID or not config.PASSWORD:
            raise ValueError("ACCOUNT_ID/PASSWORD manquants dans .env")
        await self._cmd("login", {
            "userId": config.ACCOUNT_ID, "password": config.PASSWORD,
            "appName": "signal_runner",
        })

    async def get_balance(self) -> float:
        r = await self._cmd("getMarginLevel")
        return float(r.get("returnData", {}).get("equity", 0.0))

    async def get_open_trades(self) -> list:
        r = await self._cmd("getTrades", {"openedOnly": True})
        return r.get("returnData", [])

    async def place_order(self, cmd: int, volume: float, price: float,
                          sl: float, tp: float, comment: str = "bot") -> int:
        r = await self._cmd("tradeTransaction", {"tradeTransInfo": {
            "cmd": cmd, "customComment": comment, "expiration": 0,
            "offset": 0, "order": 0, "price": price,
            "sl": sl, "symbol": config.SYMBOL, "tp": tp,
            "type": 0, "volume": volume,
        }})
        return int(r["returnData"]["order"])

    async def close_partial(self, order_id: int, cmd: int, volume: float, price: float):
        await self._cmd("tradeTransaction", {"tradeTransInfo": {
            "cmd": cmd, "customComment": "bot_tp1", "expiration": 0,
            "offset": 0, "order": order_id, "price": price,
            "sl": 0.0, "symbol": config.SYMBOL, "tp": 0.0,
            "type": 2, "volume": volume,
        }})

    async def modify_sl_tp(self, order_id: int, cmd: int, volume: float,
                           price: float, sl: float, tp: float):
        await self._cmd("tradeTransaction", {"tradeTransInfo": {
            "cmd": cmd, "customComment": "bot_modify", "expiration": 0,
            "offset": 0, "order": order_id, "price": price,
            "sl": sl, "symbol": config.SYMBOL, "tp": tp,
            "type": 3, "volume": volume,
        }})


async def _api_open_trade(sig, volume: float) -> tuple:
    """Ouvre un trade via XTB WebSocket API. Retourne (order_id, equity)."""
    client = _XTBClient()
    try:
        await client.connect()
        await client.login()
        cmd = 0 if sig.direction == "LONG" else 1
        oid = await client.place_order(
            cmd=cmd, volume=volume,
            price=sig.entry, sl=sig.sl, tp=sig.tp2,
            comment=f"bot_pro_{sig.grade}",
        )
        equity = await client.get_balance()
        log.info(f"  [API] ✅ Ordre #{oid} | {sig.direction} {volume}lots @ {sig.entry} | SL={sig.sl} TP={sig.tp2}")
        return oid, equity
    except Exception as e:
        log.error(f"  [API] Échec ouverture: {e}")
        return None, 0.0
    finally:
        await client.disconnect()


async def _api_manage_position(state: dict):
    """Gère une position ouverte: détection fermeture, TP1 partiel, breakeven, trailing."""
    client = _XTBClient()
    try:
        await client.connect()
        await client.login()
        trades = await client.get_open_trades()
        order_id = state.get("order_id")
        bot_trades = [t for t in trades
                      if (order_id and str(t.get("order")) == str(order_id))
                      or t.get("customComment", "").startswith("bot_pro")]

        # Position fermée côté serveur (SL ou TP touché)
        if not bot_trades:
            equity = await client.get_balance()
            entry  = float(state.get("entry_price") or 0)
            side   = state.get("trade_side", "LONG")
            sl_val = float(state.get("sl") or 0)
            tp_val = float(state.get("tp") or 0)
            vol    = float(state.get("current_volume") or config.VOLUME)

            # Estimer PnL depuis les niveaux SL/TP (prix de fermeture inconnu)
            # On devine la raison par proximité entry vs sl/tp
            consec = state.get("consecutive_losses", 0)
            # Raison inconnue → on met "server" et on laisse le journal le noter
            pnl_usd = 0.0  # sera mis à jour via account_equity delta
            new_equity = equity
            prev_equity = state.get("account_equity", equity)
            pnl_usd = round(new_equity - prev_equity, 2)
            reason = "tp" if pnl_usd >= 0 else "sl"

            if pnl_usd < 0:
                consec += 1
                log.warning(f"  [API] Position fermée — SL touché | P&L: {pnl_usd:+.2f} USD | pertes consec: {consec}")
            else:
                consec = 0
                log.info(f"  [API] Position fermée — TP touché | P&L: {pnl_usd:+.2f} USD")

            state.update({
                "entry_price": None, "trade_side": None,
                "sl": None, "tp": None, "tp1_done": False, "order_id": None,
                "consecutive_losses": consec,
                "last_pnl": pnl_usd,
                "last_close_reason": reason,
                "account_equity": new_equity,
                "session_pnl": round(state.get("session_pnl", 0) + pnl_usd, 2),
            })
            save_state(state)
            append_trade_journal({
                "ts": datetime.now(timezone.utc).isoformat(),
                "event": "close", "side": side, "entry": entry,
                "pnl": pnl_usd, "reason": reason,
                "consecutive_losses": consec,
            })
            return

        # Position ouverte — gestion TP1 / breakeven / trailing
        trade   = bot_trades[0]
        cmd     = trade.get("cmd", 0)
        oid     = trade.get("order")
        vol     = float(trade.get("volume", state.get("current_volume", config.VOLUME)))
        open_px = float(trade.get("open_price", state.get("entry_price", 0)))
        current = float(trade.get("close_price", open_px))
        profit  = float(trade.get("profit", 0.0))
        pnl_pts = (current - open_px) if cmd == 0 else (open_px - current)

        equity = await client.get_balance()
        state["account_equity"] = equity
        log.info(f"  [API] Position #{oid} | {pnl_pts:+.1f} pts | P&L: {profit:+.2f} USD")

        # TP1 + Breakeven (une seule fois)
        if not state.get("tp1_done") and pnl_pts >= config.BREAKEVEN_TRIGGER_PTS:
            close_vol = round(vol * config.TP1_CLOSE_RATIO, 2)
            if close_vol >= 0.01:
                log.info(f"  [API] TP1 — fermeture {close_vol} lots @ {current:.0f}")
                await client.close_partial(oid, cmd, close_vol, current)
                margin = 5 if cmd == 0 else -5
                new_sl = round(open_px + margin, 2)
                remain = round(vol - close_vol, 2)
                tp_val = float(state.get("tp") or trade.get("tp", 0))
                await client.modify_sl_tp(oid, cmd, remain, current, new_sl, tp_val)
                state.update({"tp1_done": True, "sl": new_sl, "current_volume": remain})
                log.info(f"  [API] Breakeven → SL={new_sl}")

        # Trailing stop après TP1
        elif state.get("tp1_done"):
            atr_val    = float(state.get("atr") or 150)
            trail_dist = round(atr_val * config.TRAILING_ATR_MULT, 0)
            new_sl     = round((current - trail_dist) if cmd == 0 else (current + trail_dist), 0)
            cur_sl     = float(state.get("sl") or 0)
            if (cmd == 0 and new_sl > cur_sl) or (cmd == 1 and 0 < new_sl < cur_sl):
                tp_val = float(state.get("tp") or trade.get("tp", 0))
                remain = float(state.get("current_volume") or round(vol * 0.5, 2))
                await client.modify_sl_tp(oid, cmd, remain, current, new_sl, tp_val)
                state["sl"] = new_sl
                log.info(f"  [API] Trailing → SL={new_sl} (+{pnl_pts:.0f} pts)")

        save_state(state)

    except Exception as e:
        log.error(f"  [API] manage_position: {e}")
    finally:
        await client.disconnect()


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(d: dict):
    STATE_FILE.write_text(json.dumps(d, indent=2), encoding="utf-8")


def compute_dynamic_volume(equity: float, atr: float, sl_mult: float, vol_factor: float = 1.0) -> float:
    """
    Van Tharp position sizing: RISK_PCT_PER_TRADE% de l'equity par trade.
    volume = (equity × risk_pct × vol_factor) / (atr × sl_mult × pip_value_per_lot)
    """
    if not config.USE_DYNAMIC_SIZING or equity <= 0 or atr <= 0:
        return config.VOLUME
    risk_usd = equity * config.RISK_PCT_PER_TRADE * vol_factor
    sl_pts   = atr * sl_mult
    raw_vol  = risk_usd / (sl_pts * config.US100_PIP_VALUE_PER_LOT)
    return round(max(config.MIN_VOLUME, min(config.MAX_VOLUME, raw_vol)), 2)


def get_vix_level() -> float:
    """Fetch current VIX level (Soros VIX gate). Returns 20.0 on failure."""
    if not _YF_AVAILABLE:
        return 20.0
    try:
        vix = yf.download("^VIX", period="1d", interval="1h",
                          progress=False, auto_adjust=True)
        if not vix.empty:
            if isinstance(vix.columns, __import__("pandas").MultiIndex):
                vix.columns = vix.columns.get_level_values(0)
            return float(vix["Close"].iloc[-1])
    except Exception:
        pass
    return 20.0


def check_daily_drawdown_pct(state: dict) -> bool:
    """True si drawdown intraday >= DAILY_DRAWDOWN_MAX_PCT (Raschke 2% rule)."""
    equity       = state.get("account_equity", 0.0)
    start_equity = state.get("session_start_equity", 0.0)
    if equity <= 0 or start_equity <= 0:
        return False
    return (start_equity - equity) / start_equity >= config.DAILY_DRAWDOWN_MAX_PCT


def append_trade_journal(event: dict):
    """Append one trade event line to trades_history.jsonl."""
    with TRADES_JOURNAL_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def count_daily_losses() -> int:
    """Count negative-PnL close events from today (UTC) in the journal."""
    if not TRADES_JOURNAL_FILE.exists():
        return 0
    today = datetime.now(timezone.utc).date().isoformat()
    count = 0
    try:
        with TRADES_JOURNAL_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    ev = json.loads(line)
                    if ev.get("event") == "close" and ev.get("ts", "").startswith(today):
                        if ev.get("pnl", 0) < 0:
                            count += 1
                except Exception:
                    pass
    except Exception:
        pass
    return count


def run_scan():
    global _prev_entry_price, _prev_consecutive_losses, _last_signal_key

    now = datetime.now(timezone.utc).strftime("%H:%M GMT")
    log.info(f"── SCAN {now} " + "─" * 38)

    state = load_state()
    consec = state.get("consecutive_losses", 0)
    cb_until = state.get("circuit_breaker_until", 0)

    # ── Transition detection ─────────────────────────────────────────────────
    current_entry = state.get("entry_price")

    # Trade close detected (entry_price went non-null → null between two scans)
    if _prev_entry_price is not None and current_entry is None:
        pnl    = state.get("last_pnl", 0)
        reason = state.get("last_close_reason", "unknown")
        append_trade_journal({
            "ts":                 datetime.now(timezone.utc).isoformat(),
            "event":              "close",
            "side":               state.get("last_trade_side"),
            "entry":              state.get("last_entry_price"),
            "exit":               state.get("last_close_price"),
            "pnl":                pnl,
            "reason":             reason,
            "volume":             state.get("current_volume", config.VOLUME),
            "consecutive_losses": consec,
        })
        log.info(f"  [JOURNAL] Close enregistré — raison={reason} PnL={pnl:+.2f} USD")

        # Post-breaker wins tracking
        if state.get("post_breaker"):
            if reason == "tp" and pnl >= 0:
                wins = state.get("post_breaker_wins", 0) + 1
                if wins >= config.POST_BREAKER_WINS_REQUIRED:
                    state["post_breaker"]      = False
                    state["post_breaker_wins"] = 0
                    log.info(f"  [RECOVERY] {config.POST_BREAKER_WINS_REQUIRED} gains consécutifs "
                             f"— mode reprise terminé, taille normale restaurée")
                else:
                    state["post_breaker_wins"] = wins
                    log.info(f"  [RECOVERY] Gain {wins}/{config.POST_BREAKER_WINS_REQUIRED} "
                             f"— mode reprise encore actif")
                save_state(state)
            elif pnl < 0:
                state["post_breaker_wins"] = 0
                save_state(state)

    # Circuit-breaker lifted: consecutive_losses reset from ≥4 to <4 → activate post_breaker
    CB_THRESHOLD = 4  # mirrors SteenbargerPerformanceTracker.MAX_CONSECUTIVE_LOSSES
    if (_prev_consecutive_losses is not None
            and _prev_consecutive_losses >= CB_THRESHOLD
            and consec < CB_THRESHOLD
            and not state.get("post_breaker")):
        state["post_breaker"]      = True
        state["post_breaker_wins"] = 0
        save_state(state)
        log.info("  [RECOVERY] Circuit breaker levé → mode reprise activé "
                 "(Grade A uniquement + demi-taille jusqu'à 2 gains consécutifs)")

    _prev_entry_price        = current_entry
    _prev_consecutive_losses = consec

    # Daily losses (feeds trading_library guard-rail)
    state["daily_losses"] = count_daily_losses()

    # Circuit breaker
    if time.time() < cb_until:
        rem = int(cb_until - time.time())
        log.info(f"  [CIRCUIT BREAKER] Pause — {rem//60}min {rem%60}s restantes")
        return

    # Daily drawdown % (Raschke — stop si equity -2% intraday)
    if check_daily_drawdown_pct(state):
        equity  = state.get("account_equity", 0)
        start_e = state.get("session_start_equity", 0)
        dd_pct  = (start_e - equity) / start_e * 100 if start_e > 0 else 0
        log.warning(f"  [DRAWDOWN] Limite journalière atteinte ({dd_pct:.1f}% > {config.DAILY_DRAWDOWN_MAX_PCT*100:.0f}%) — trading suspendu")
        return

    # VIX gate (Soros — réduire/bloquer sur panique marché)
    _vix_cache = getattr(run_scan, "_vix_cache", (0.0, 0))
    if time.time() - _vix_cache[1] > 300:  # refresh toutes les 5 min
        _vix = get_vix_level()
        run_scan._vix_cache = (_vix, time.time())
    else:
        _vix = _vix_cache[0]
    if _vix > 0:
        if _vix >= config.VIX_EXTREME_THRESHOLD:
            log.warning(f"  [VIX GATE] VIX={_vix:.1f} >= {config.VIX_EXTREME_THRESHOLD} — trading bloqué (panique marché)")
            return
        elif _vix >= config.VIX_HIGH_THRESHOLD:
            log.info(f"  [VIX GATE] VIX={_vix:.1f} >= {config.VIX_HIGH_THRESHOLD} — volume réduit 50%")

    # Position déjà ouverte ?
    if state.get("entry_price"):
        side  = state.get("trade_side", "?")
        entry = state.get("entry_price", 0)
        if not (_WS_AVAILABLE and _API_ENABLED):
            # Sans API on ne peut pas vérifier si la position est encore ouverte.
            # Si entry_time > 12h, on considère qu'elle a été fermée manuellement.
            entry_time_str = state.get("entry_time")
            if entry_time_str:
                try:
                    entry_dt = datetime.fromisoformat(entry_time_str.replace("Z", "+00:00"))
                    age_h = (datetime.now(timezone.utc) - entry_dt).total_seconds() / 3600
                    if age_h > 12:
                        log.warning(
                            f"  [STATE] Position {side}@{entry:.0f} > 12h sans API "
                            f"({age_h:.0f}h) — entry_price réinitialisé. "
                            f"Fermer manuellement si encore ouverte."
                        )
                        state.update({"entry_price": None, "trade_side": None,
                                      "sl": None, "tp": None, "entry_time": None})
                        save_state(state)
                        # continue scan ci-dessous
                    else:
                        log.info(f"  Position {side}@{entry:.0f} ouverte — gestion manuelle (API désactivée)")
                        return
                except Exception:
                    log.info(f"  Position {side}@{entry:.0f} déjà ouverte — gestion automatique")
                    return
            else:
                log.warning(f"  [STATE] entry_price sans entry_time — reset auto (API désactivée)")
                state.update({"entry_price": None, "trade_side": None})
                save_state(state)
        else:
            log.info(f"  Position {side}@{entry:.0f} déjà ouverte — gestion automatique")
            try:
                _asyncio.run(_api_manage_position(state))
            except Exception as e:
                log.debug(f"  [API] manage_position: {e}")
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

    # Smart Money — SEC EDGAR Form 4 + OpenInsider + Congress (non-bloquant)
    try:
        sm = _smart_money_engine.assess()
        _smart_money_engine.log_signal(sm)
    except Exception:
        pass

    # Institutional Signals — VIX / Yield Curve / DXY / COT / Put-Call / Breadth
    # Évaluation effectuée AVANT la génération du signal pour court-circuiter tôt
    _inst_ctx = None
    try:
        _inst_ctx = get_institutional_filter(direction="LONG")  # neutre à ce stade
        log_institutional_context(_inst_ctx)
        if not _inst_ctx.can_trade:
            log.warning(f"  [INST] Scan ignoré — {_inst_ctx.block_reason}")
            return
    except Exception as e:
        log.debug(f"institutional_signals error: {e}")

    # Signal MTF
    log.info("  Chargement MTF (yfinance)…")
    try:
        mtf = load_mtf()
        sig = generate_pro_signal(mtf)
        print_pro_signal(sig)
    except Exception as e:
        log.error(f"  Erreur génération signal: {e}")
        return

    # ── Routines Pro Trader — VWAP, PDH/PDL, PWH/PWL, Opening Range, ES/NQ ─────
    pro_ctx = {}
    try:
        pro_ctx = run_pro_routine(mtf, state)
        state   = pro_ctx.get("state", state)
        # Enrichir le signal avec les niveaux institutionnels
        if sig.direction != "SKIP" and sig.entry > 0:
            lv_score, lv_confs = score_key_levels(
                sig.entry, sig.direction, pro_ctx.get("levels", {}), sig.atr
            )
            if lv_score > 0:
                sig.confluences.extend(lv_confs)
                sig.score = getattr(sig, "score", 0) + lv_score
                log.info(f"  [PRO] +{lv_score} confluence(s) institutionnelle(s) ajoutée(s)")
            elif lv_score < 0:
                log.warning(f"  [PRO] {abs(lv_score)} pénalité niveau institutionnel")
                for c in lv_confs:
                    log.warning(f"    ⚠ {c}")
    except Exception as e:
        log.debug(f"pro_routine: {e}")

    if sig.direction == "SKIP":
        return

    # ── Filtre Institutionnel avec la vraie direction du signal ───────────────
    try:
        if _inst_ctx is None:
            _inst_ctx = get_institutional_filter(direction=sig.direction)
        else:
            # Ré-évaluer avec la vraie direction si différente de LONG (neutre initial)
            if sig.direction == "SHORT":
                _inst_ctx = get_institutional_filter(direction="SHORT")
        log_institutional_context(_inst_ctx)
        if not _inst_ctx.can_trade:
            log.warning(f"  [INST] Trade bloqué par filtre institutionnel: {_inst_ctx.block_reason}")
            return
        # Intégrer le score institutionnel dans le score du signal
        if hasattr(sig, "score"):
            inst_bonus = round(_inst_ctx.composite_score * 2, 1)  # échelle ±2
            sig.score = sig.score + inst_bonus
            log.info(f"  [INST] Score composite {_inst_ctx.composite_score:+.2f} → bonus signal {inst_bonus:+.1f}")
    except Exception as e:
        log.debug(f"inst_filter direction: {e}")

    # ── Filtre Trading Library (5 livres) ────────────────────────────────────
    try:
        signal_data = {
            "direction": sig.direction,
            "d1_bias": sig.d1_bias if hasattr(sig, 'd1_bias') else "NEUTRE",
            "h1_signal": sig.direction,
            "confluences_count": len(sig.confluences) if hasattr(sig, 'confluences') else 0,
            "rsi": getattr(sig, 'rsi', 50),
            "atr": sig.atr,
            "d1_macd_hist": (1.0 if getattr(sig, 'd1_bias', 'NEUTRE') == "LONG"
                             else -1.0 if getattr(sig, 'd1_bias', 'NEUTRE') == "SHORT"
                             else 0.0),
        }
        library_result = full_library_assessment(state, signal_data)
        if not library_result["can_trade"]:
            for reason in library_result["reasons"]:
                log.warning(f"  [LIBRARY] BLOCAGE: {reason}")
            log.info(f"  [LIBRARY] {library_result['quote']}")
            log.warning("  [LIBRARY] Signal ignoré (can_trade=False)")
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

    # ── Déduplication (évite de répéter le même signal chaque scan) ─────────
    sig_key = f"{sig.direction}_{sig.entry}_{sig.grade}"
    if sig_key == _last_signal_key:
        log.info(f"  Signal identique au précédent ({sig_key}) — skip (dédup)")
        return

    # ── Volume & log signal ──────────────────────────────────────────────────
    post_breaker = state.get("post_breaker", False)
    if post_breaker and sig.grade not in ("A", "A+"):
        log.info(f"  [POST-BREAKER] Grade {sig.grade} bloqué — Grade A/A+ requis")
        return
    _last_signal_key = sig_key  # marquer après tous les checks, avant exécution
    vol_factor   = 1.0
    if post_breaker:
        vol_factor *= config.POST_BREAKER_VOLUME_MULT
    if _vix >= config.VIX_HIGH_THRESHOLD:
        vol_factor *= 0.5
    equity = state.get("account_equity", 0.0)
    if config.USE_DYNAMIC_SIZING and equity > 0:
        recommended_volume = compute_dynamic_volume(equity, sig.atr, config.ATR_SL_MULT, vol_factor)
    else:
        recommended_volume = round(config.VOLUME * vol_factor, 2)
    log.info("=" * 56)
    log.info(f"  *** SIGNAL ACTIONNABLE *** {sig.direction} Grade {sig.grade}")
    log.info(f"  Entry : {sig.entry}  |  SL : {sig.sl}  |  TP : {sig.tp2}")
    log.info(f"  R:R   : {sig.rr}    |  ATR: {sig.atr:.0f} pts")
    log.info(f"  Volume: {recommended_volume:.2f} lots"
             + ("  [MODE REPRISE — demi-taille]" if post_breaker else ""))

    # ── Auto-exécution via XTB WebSocket API ────────────────────────────────
    if _WS_AVAILABLE and _API_ENABLED:
        order_id, new_equity = _asyncio.run(_api_open_trade(sig, recommended_volume))
        if order_id:
            state.update({
                "entry_price":    sig.entry,
                "trade_side":     sig.direction,
                "sl":             sig.sl,
                "tp":             sig.tp2,
                "tp1_done":       False,
                "order_id":       order_id,
                "current_volume": recommended_volume,
                "atr":            round(sig.atr, 1),
                "grade":          sig.grade,
            })
            if new_equity > 0:
                state["account_equity"] = new_equity
            save_state(state)
            log.info(f"  [API] Ordre #{order_id} exécuté — bot_state.json mis à jour")
        else:
            log.error("  [API] Ordre NON placé — vérifier connexion XTB")
    else:
        log.info("  >>> API xAPI non activée — PLACER ORDRE SUR XSTATION5 <<<")
    log.info("=" * 56)

    # Journal open event
    append_trade_journal({
        "ts":     datetime.now(timezone.utc).isoformat(),
        "event":  "open",
        "side":   sig.direction,
        "entry":  sig.entry,
        "sl":     sig.sl,
        "tp1":    getattr(sig, "tp1", None),
        "tp2":    sig.tp2,
        "rr":     sig.rr,
        "grade":  sig.grade,
        "volume": recommended_volume,
        "atr":    round(sig.atr, 1),
    })

    # When API is disabled the operator places the order manually; persist entry_price
    # so the next scan does not see entry_price=None and emit another duplicate open event.
    if not (_WS_AVAILABLE and _API_ENABLED) and not state.get("entry_price"):
        state.update({
            "entry_price":    sig.entry,
            "trade_side":     sig.direction,
            "sl":             sig.sl,
            "current_volume": recommended_volume,
            "entry_time":     datetime.now(timezone.utc).isoformat(),
        })
        save_state(state)


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
