#!/usr/bin/env python3
"""
XTB US100 Trading Bot — Playwright Edition
Data source : yfinance (NQ=F — NASDAQ 100 futures, proxy US100)
Execution   : Playwright → XStation5 browser (Click & Trade)
Lancer      : python xtb_bot_playwright.py
"""

import asyncio
import json
import logging
import msvcrt
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 on Windows stdout to avoid cp1252 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import aiohttp
import numpy as np
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout

import config
from market_intelligence import MarketIntelligenceEngine
from macro_intelligence import MacroIntelligenceEngine
from economic_calendar import EconomicCalendarEngine
from news_surveillance import NewsSurveillanceEngine
from smart_money import SmartMoneyEngine
from strategy_pro import load_mtf, generate_pro_signal, print_pro_signal, ProSignal
from market_regime import classify_regime, regime_summary
from kronos_model import evaluate_kronos, kronos_summary
from session_analytics import (
    load_history, compute_kelly, record_trade, print_analytics_report
)

load_dotenv()

# ═══════════════════════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("xtb_bot_playwright.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("xtb_pw")

# ═══════════════════════════════════════════════════════════════════════════════
# INDICATEURS TECHNIQUES
# ═══════════════════════════════════════════════════════════════════════════════

def calc_ichimoku(df: pd.DataFrame) -> pd.DataFrame:
    hi = df["High"]
    lo = df["Low"]
    t  = (hi.rolling(config.TENKAN_PERIOD).max()    + lo.rolling(config.TENKAN_PERIOD).min())    / 2
    k  = (hi.rolling(config.KIJUN_PERIOD).max()     + lo.rolling(config.KIJUN_PERIOD).min())     / 2
    sa = ((t + k) / 2).shift(config.DISPLACEMENT)
    sb = ((hi.rolling(config.SENKOU_B_PERIOD).max() + lo.rolling(config.SENKOU_B_PERIOD).min()) / 2).shift(config.DISPLACEMENT)
    return pd.DataFrame({"tenkan": t, "kijun": k, "senkou_a": sa, "senkou_b": sb}, index=df.index)


def calc_rsi(close: pd.Series) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(com=config.RSI_PERIOD - 1, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=config.RSI_PERIOD - 1, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def calc_atr(df: pd.DataFrame) -> pd.Series:
    hi, lo, cl = df["High"], df["Low"], df["Close"]
    tr = pd.concat([
        hi - lo,
        (hi - cl.shift(1)).abs(),
        (lo - cl.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=config.ATR_PERIOD, adjust=False).mean()


def calc_adx(df: pd.DataFrame) -> pd.Series:
    hi, lo, cl = df["High"], df["Low"], df["Close"]
    tr = pd.concat([
        hi - lo,
        (hi - cl.shift(1)).abs(),
        (lo - cl.shift(1)).abs(),
    ], axis=1).max(axis=1)
    dm_p = (hi - hi.shift(1)).clip(lower=0)
    dm_m = (lo.shift(1) - lo).clip(lower=0)
    # Garder seulement le DM dominant
    both  = (dm_p > 0) & (dm_m > 0)
    dm_p  = dm_p.where(~both | (dm_p >= dm_m), 0.0)
    dm_m  = dm_m.where(~both | (dm_m >  dm_p), 0.0)
    atr_s = tr.ewm(span=config.ADX_PERIOD, adjust=False).mean()
    di_p  = (dm_p.ewm(span=config.ADX_PERIOD, adjust=False).mean() / atr_s.replace(0, np.nan)) * 100
    di_m  = (dm_m.ewm(span=config.ADX_PERIOD, adjust=False).mean() / atr_s.replace(0, np.nan)) * 100
    dx    = ((di_p - di_m).abs() / (di_p + di_m).replace(0, np.nan)) * 100
    return dx.ewm(span=config.ADX_PERIOD, adjust=False).mean()


def calc_macd(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_f    = close.ewm(span=config.MACD_FAST,   adjust=False).mean()
    ema_s    = close.ewm(span=config.MACD_SLOW,   adjust=False).mean()
    macd     = ema_f - ema_s
    sig      = macd.ewm(span=config.MACD_SIGNAL,  adjust=False).mean()
    hist     = macd - sig
    return macd, sig, hist


def is_trading_session() -> bool:
    """Vrai si on est dans la session NY (13:30–20:00 UTC, lun-ven)."""
    if config.FORCE_SESSION:
        return True
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:  # samedi=5, dimanche=6
        return False
    t = now.hour * 60 + now.minute
    start = config.SESSION_START_H * 60 + config.SESSION_START_M
    end   = config.SESSION_END_H   * 60 + config.SESSION_END_M
    return start <= t <= end


def generate_signal(df: pd.DataFrame) -> tuple[str, dict]:
    ichi = calc_ichimoku(df)
    rsi_ = calc_rsi(df["Close"])
    atr_ = calc_atr(df)
    adx_ = calc_adx(df)
    _, _, macd_hist = calc_macd(df["Close"])

    idx = -2  # dernière bougie fermée

    close    = float(df["Close"].iloc[idx])
    tenkan   = float(ichi["tenkan"].iloc[idx])
    kijun    = float(ichi["kijun"].iloc[idx])
    senkou_a = float(ichi["senkou_a"].iloc[idx])
    senkou_b = float(ichi["senkou_b"].iloc[idx])
    rsi_val  = float(rsi_.iloc[idx])
    atr_val  = float(atr_.iloc[idx])
    adx_val  = float(adx_.iloc[idx])
    hist_val = float(macd_hist.iloc[idx])

    kumo_top = max(senkou_a, senkou_b)
    kumo_bot = min(senkou_a, senkou_b)
    in_kumo  = kumo_bot <= close <= kumo_top

    snap = dict(
        close=close, tenkan=tenkan, kijun=kijun,
        senkou_a=senkou_a, senkou_b=senkou_b,
        kumo_top=kumo_top, kumo_bot=kumo_bot,
        rsi=rsi_val, atr=atr_val, adx=adx_val, macd_hist=hist_val,
        in_kumo=in_kumo,
    )

    # Invalider si dans le kumo ou valeurs NaN
    if in_kumo or any(v != v for v in [tenkan, kijun, senkou_a, senkou_b, atr_val, adx_val]):
        return "SKIP", snap

    # Filtre ADX : ignorer les marchés range
    if adx_val < config.ADX_MIN:
        snap["skip_reason"] = f"ADX {adx_val:.1f} < {config.ADX_MIN} (range)"
        return "SKIP", snap

    short_ok = (
        close < kumo_bot
        and tenkan < kijun          # TK cross baissier
        and close < tenkan          # prix sous Tenkan
        and rsi_val <= config.RSI_MAX
        and hist_val < 0            # MACD histogramme négatif (momentum baissier)
    )
    long_ok = (
        close > kumo_top
        and tenkan > kijun          # TK cross haussier
        and close > tenkan          # prix au-dessus Tenkan
        and rsi_val >= config.RSI_MIN
        and hist_val > 0            # MACD histogramme positif (momentum haussier)
    )

    if short_ok: return "SHORT", snap
    if long_ok:  return "LONG",  snap
    return "SKIP", snap


def calc_levels(signal: str, snap: dict) -> dict:
    """SL/TP basés sur ATR — adaptatifs à la volatilité courante."""
    entry = snap["close"]
    atr   = snap["atr"]
    sl_dist  = round(atr * config.ATR_SL_MULT,  2)
    tp1_dist = round(atr * config.ATR_TP1_MULT, 2)
    tp2_dist = round(atr * config.ATR_TP2_MULT, 2)

    if signal == "SHORT":
        sl  = round(entry + sl_dist,  2)
        tp1 = round(entry - tp1_dist, 2)
        tp2 = round(entry - tp2_dist, 2)
    else:
        sl  = round(entry - sl_dist,  2)
        tp1 = round(entry + tp1_dist, 2)
        tp2 = round(entry + tp2_dist, 2)

    risk   = abs(sl - entry)
    reward = abs(tp2 - entry)
    return dict(
        entry=round(entry, 2), sl=sl, tp1=tp1, tp2=tp2,
        risk=round(risk, 2), rr=f"1:{round(reward / max(risk, 0.01), 1)}",
    )


def get_ohlcv() -> pd.DataFrame:
    """Charge les données H1 US100 via yfinance — NQZ26=F (déc.) puis NQ=F puis ^NDX en fallback."""
    _tickers = ["NQZ26=F", "NQ=F", "^NDX", "QQQ"]
    for _sym in _tickers:
        try:
            raw = yf.download(_sym, period="10d", interval="1h",
                              progress=False, auto_adjust=True)
            if raw.empty:
                continue
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
            # Rejeter si le dernier Close < 10000 (futures expirés ou données corrompues)
            last_close = float(df["Close"].iloc[-1])
            if last_close < 10000:
                log.warning(f"  {_sym}: dernier Close {last_close:.0f} suspect — ticker suivant")
                continue
            log.info(f"  {len(df)} bougies H1 chargées ({_sym})")
            return df
        except Exception as e:
            log.debug(f"  {_sym} échec: {e}")
            continue
    raise RuntimeError("yfinance: aucune donnée valide pour US100 (NQZ26=F / NQ=F / ^NDX / QQQ)")


# ═══════════════════════════════════════════════════════════════════════════════
# BOT PLAYWRIGHT
# ═══════════════════════════════════════════════════════════════════════════════

STATE_FILE = Path(__file__).parent / "bot_state.json"


def _redact_url(url: str) -> str:
    """Masque les identifiants (xslogin/xspass/password) dans une URL avant log."""
    import re as _re
    if not url:
        return url
    return _re.sub(r"(xslogin|xspass|password|login|pass)=[^&\s]*", r"\1=***", url, flags=_re.I)


# ═══════════════════════════════════════════════════════════════════════════════
# SESSION TRACKER — statistiques en temps réel + gate journalier
# ═══════════════════════════════════════════════════════════════════════════════

class SessionTracker:
    """
    Suivi temps réel de la session :
    - P&L cumulé (pts et USD)
    - Win rate + W/L count
    - Drawdown maximum
    - Gate journalier : bloque les nouveaux trades si MAX_DAILY_LOSS_USD dépassé
    """

    def __init__(self):
        self.daily_pnl_pts: float = 0.0
        self.daily_pnl_usd: float = 0.0
        self.peak_pnl_pts:  float = 0.0
        self.max_drawdown:  float = 0.0
        self.trades: list[dict]   = []
        self.session_start        = datetime.now(timezone.utc)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t["pnl_pts"] > 0)

    @property
    def losses(self) -> int:
        return sum(1 for t in self.trades if t["pnl_pts"] <= 0)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return self.wins / len(self.trades) * 100

    def record_trade(self, side: str, entry: float, exit_price: float, volume: float):
        """Enregistre un trade clôturé et met à jour toutes les stats."""
        pnl_pts = (entry - exit_price) if side == "SHORT" else (exit_price - entry)
        # US100 : 1 lot = 1 USD/point → volume_lots × pnl_pts (approximation CFD)
        pnl_usd = pnl_pts * volume
        self.daily_pnl_pts += pnl_pts
        self.daily_pnl_usd += pnl_usd
        # Drawdown tracking
        if self.daily_pnl_pts > self.peak_pnl_pts:
            self.peak_pnl_pts = self.daily_pnl_pts
        drawdown = self.peak_pnl_pts - self.daily_pnl_pts
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown
        self.trades.append({
            "side":    side,
            "entry":   entry,
            "exit":    exit_price,
            "volume":  volume,
            "pnl_pts": round(pnl_pts, 1),
            "pnl_usd": round(pnl_usd, 2),
            "time":    datetime.now(timezone.utc).strftime("%H:%M GMT"),
        })
        log.info(
            f"  [SESSION] Trade #{len(self.trades)} {side} {pnl_pts:+.1f}pts ({pnl_usd:+.2f}$) | "
            f"Journée: {self.daily_pnl_pts:+.1f}pts ({self.daily_pnl_usd:+.2f}$) | "
            f"WR: {self.win_rate:.0f}% ({self.wins}W/{self.losses}L)"
        )

    def is_daily_loss_exceeded(self) -> bool:
        """Vérifie si la limite de perte journalière est atteinte."""
        return self.daily_pnl_usd < -config.MAX_DAILY_LOSS_USD

    def print_stats(self):
        sep = "═" * 56
        log.info(sep)
        log.info(f"  SESSION STATS | {datetime.now(timezone.utc).strftime('%H:%M GMT')}")
        log.info(f"  Trades: {len(self.trades)} | W/L: {self.wins}/{self.losses} | WR: {self.win_rate:.0f}%")
        log.info(f"  P&L: {self.daily_pnl_pts:+.1f} pts ({self.daily_pnl_usd:+.2f} USD)")
        log.info(f"  Drawdown max: {self.max_drawdown:.1f} pts")
        log.info(f"  Limite journaliere: {-config.MAX_DAILY_LOSS_USD:.0f} USD "
                 f"({'ATTEINTE' if self.is_daily_loss_exceeded() else 'OK'})")
        log.info(sep)


class CdpPage:
    """Thin wrapper around Chrome CDP WebSocket — mimics the Playwright Page API subset used by this bot."""

    def __init__(self, tab_info: dict, session: aiohttp.ClientSession):
        self._ws_url  = tab_info["webSocketDebuggerUrl"]
        self._url_val = tab_info["url"]
        self._session = session
        self._ws      = None
        self._msg_id  = 0

    async def connect(self):
        self._ws = await self._session.ws_connect(self._ws_url)

    async def close(self):
        if self._ws and not self._ws.closed:
            await self._ws.close()

    @property
    def url(self) -> str:
        return self._url_val

    async def evaluate(self, expression: str):
        if not self._ws or self._ws.closed:
            raise RuntimeError("CDP WebSocket not connected")
        # Sémantique Playwright : une fonction passée en expression doit être APPELÉE.
        # Runtime.evaluate brut renvoie sinon l'objet fonction sérialisé en {} sans l'exécuter.
        stripped = expression.lstrip()
        if stripped.startswith(("() =>", "()=>", "async () =>", "async ()=>", "function")):
            expression = f"({expression})()"
        self._msg_id += 1
        req_id = self._msg_id
        await self._ws.send_str(json.dumps({
            "id": req_id,
            "method": "Runtime.evaluate",
            "params": {"expression": expression, "awaitPromise": True, "returnByValue": True},
        }))
        while True:
            raw = await asyncio.wait_for(self._ws.receive_str(), timeout=15.0)
            data = json.loads(raw)
            if data.get("id") != req_id:
                continue
            result = data.get("result", {})
            exc = result.get("exceptionDetails")
            if exc:
                raise RuntimeError(f"CDP JS: {exc.get('text','error')}")
            val = result.get("result", {})
            return val.get("value")

    async def ping(self, timeout: float = 5.0) -> bool:
        """CDP Watchdog — retourne True si le WebSocket répond en moins de timeout secondes."""
        if not self._ws or self._ws.closed:
            return False
        try:
            self._msg_id += 1
            req_id = self._msg_id
            await self._ws.send_str(json.dumps({
                "id": req_id, "method": "Runtime.evaluate",
                "params": {"expression": "1", "returnByValue": True},
            }))
            deadline = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < deadline:
                try:
                    raw  = await asyncio.wait_for(self._ws.receive_str(), timeout=timeout)
                    data = json.loads(raw)
                    if data.get("id") == req_id:
                        return True
                except asyncio.TimeoutError:
                    return False
            return False
        except Exception:
            return False

    async def screenshot(self, path: str = None):
        pass  # debug screenshots disabled in CDP mode

    async def reload(self, timeout: int = 15000):
        self._msg_id += 1
        await self._ws.send_str(json.dumps({"id": self._msg_id, "method": "Page.reload", "params": {}}))
        await asyncio.sleep(3)

    async def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 30000):
        """Navigate via CDP Page.navigate command."""
        self._msg_id += 1
        req_id = self._msg_id
        await self._ws.send_str(json.dumps({
            "id": req_id,
            "method": "Page.navigate",
            "params": {"url": url},
        }))
        deadline = __import__("time").monotonic() + 10.0
        while __import__("time").monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(self._ws.receive_str(), timeout=5.0)
                data = json.loads(raw)
                if data.get("id") == req_id:
                    break
            except asyncio.TimeoutError:
                break
        await asyncio.sleep(3.0)
        self._url_val = url

    async def wait_for_url(self, pattern: str, timeout: int = 30000):
        """Poll window.location.href until pattern matches."""
        import time as _time
        deadline = _time.monotonic() + timeout / 1000
        fragment = pattern.replace("**/", "").replace("**", "").replace("*", "")
        while True:
            try:
                current = await self.evaluate("window.location.href")
                if current:
                    self._url_val = current
                    if fragment in current:
                        return
            except Exception:
                pass
            if _time.monotonic() >= deadline:
                raise PWTimeout(f"wait_for_url timeout: {pattern}")
            await asyncio.sleep(0.5)

    def _selector_js(self, selector: str) -> str:
        """Convert Playwright selector to JS expression returning an element."""
        # Handle comma-separated compound selectors — try each part
        parts = [s.strip() for s in selector.split(',')]
        clauses = []
        for part in parts:
            if part.startswith('text='):
                text = part[5:].replace("'", "\\'")
                clauses.append(
                    f"Array.from(document.querySelectorAll('*')).find(e => e.offsetParent !== null && e.innerText && e.innerText.trim() === '{text}')"
                )
            elif ':has-text(' in part:
                m = __import__('re').search(r':has-text\(["\']([^"\']+)["\']\)', part)
                base = __import__('re').sub(r':has-text\([^)]+\)', '', part).strip()
                text = m.group(1).replace("'", "\\'") if m else ''
                q = base or '*'
                clauses.append(
                    f"Array.from(document.querySelectorAll({json.dumps(q)})).find(e => e.offsetParent !== null && e.innerText && e.innerText.includes('{text}'))"
                )
            else:
                clauses.append(f"document.querySelector({json.dumps(part)})")
        return ' || '.join(clauses)

    async def _find_element(self, selector: str, timeout: int = 30000):
        """Poll until element matching selector is found, or raise PWTimeout."""
        import time as _time
        deadline = _time.monotonic() + timeout / 1000
        expr = f"({self._selector_js(selector)}) != null"
        while True:
            found = await self.evaluate(expr)
            if found:
                return
            if _time.monotonic() >= deadline:
                raise PWTimeout(f"Timeout: element not found: {selector}")
            await asyncio.sleep(0.3)

    async def click(self, selector: str, click_count: int = 1, timeout: int = 30000):
        await self._find_element(selector, timeout)
        js = self._selector_js(selector)
        for _ in range(click_count):
            await self.evaluate(f"(function(){{ const el = {js}; if(el) el.click(); return !!el; }})()")

    async def fill(self, selector: str, value: str, timeout: int = 30000):
        await self._find_element(selector, timeout)
        js = self._selector_js(selector)
        escaped = json.dumps(str(value))
        # 1. Focus + native setter + Angular events
        await self.evaluate(f"""(function(){{
            const el = {js};
            if (!el) return false;
            el.focus();
            el.click();
            // Clear existing value
            el.select();
            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
            setter.call(el, {escaped});
            el.dispatchEvent(new Event('input', {{bubbles:true, composed:true}}));
            el.dispatchEvent(new Event('change', {{bubbles:true, composed:true}}));
            el.dispatchEvent(new KeyboardEvent('keyup', {{bubbles:true}}));
            // Angular reactive form update
            try {{
                const ngEl = window.ng && window.ng.getContext && window.ng.getContext(el);
                if (ngEl && ngEl.valueAccessor) ngEl.valueAccessor.onChange({escaped});
            }} catch(e) {{}}
            return true;
        }})()""")
        # 2. Backup: CDP Input.insertText (triggers Zone.js interceptors)
        try:
            # Select all existing text first via JS
            await self.evaluate(f"(function(){{ const el = {js}; if(el) el.select(); }})()")
            # Type character by character via CDP to trigger Angular
            self._msg_id += 1
            await self._ws.send_str(json.dumps({
                "id": self._msg_id,
                "method": "Input.insertText",
                "params": {"text": str(value)},
            }))
            await asyncio.sleep(0.3)
        except Exception:
            pass

    def locator(self, selector: str) -> 'CdpLocator':
        return CdpLocator(self, selector)


class CdpLocator:
    """Minimal Playwright Locator emulation over CdpPage."""

    def __init__(self, page: 'CdpPage', selector: str):
        self._page = page
        self._selector = selector

    @property
    def first(self) -> 'CdpLocator':
        return self

    def or_(self, other: 'CdpLocator') -> 'CdpLocator':
        return CdpLocator(self._page, f"{self._selector}, {other._selector}")

    def filter(self, **kwargs) -> 'CdpLocator':
        return self

    async def click(self, click_count: int = 1, timeout: int = 30000):
        await self._page.click(self._selector, click_count=click_count, timeout=timeout)

    async def fill(self, value: str, timeout: int = 30000):
        await self._page.fill(self._selector, value, timeout=timeout)

    async def press(self, key: str, timeout: int = 30000):
        # Focus the element first, then use CDP Input.dispatchKeyEvent (real hardware-level events)
        # Angular Zone.js intercepts these, unlike DOM-dispatched KeyboardEvents
        js = self._page._selector_js(self._selector)
        await self._page.evaluate(f"(function(){{ const el = {js}; if (el) el.focus(); }})()")
        await asyncio.sleep(0.1)
        key_code = 13 if key == "Enter" else (ord(key[0]) if len(key) == 1 else 0)
        dom_key = "Enter" if key == "Enter" else key
        dom_code = "Enter" if key == "Enter" else f"Key{key[0].upper()}"
        for ev_type in ("keyDown", "keyUp"):
            self._page._msg_id += 1
            await self._page._ws.send_str(json.dumps({
                "id": self._page._msg_id,
                "method": "Input.dispatchKeyEvent",
                "params": {
                    "type": ev_type,
                    "key": dom_key,
                    "code": dom_code,
                    "windowsVirtualKeyCode": key_code,
                    "nativeVirtualKeyCode": key_code,
                    "modifiers": 0,
                },
            }))
            await asyncio.sleep(0.15)

    async def wait_for(self, state: str = None, timeout: int = 30000):
        await self._page._find_element(self._selector, timeout)

    async def inner_text(self) -> str:
        js = self._page._selector_js(self._selector)
        result = await self._page.evaluate(f"(function(){{ const el = {js}; return el ? el.innerText : null; }})()")
        return result or ''


class XStation5Bot:

    LOGIN_URL   = "https://xstation5.xtb.com/?branch=int#/_/login"
    TRADING_URL = "https://xstation5.xtb.com/?branch=int#/_/loggedIn"

    def __init__(self):
        self._pw       = None
        self._browser  = None
        self._page: Page | None = None
        self._tp1_done: bool    = False
        self._entry_price: float | None = None
        self._trade_side: str | None    = None  # "SHORT" | "LONG"
        # Dernier trade clôturé — sert à filtrer les re-entrées défavorables
        self._last_entry_price: float | None = None
        self._last_trade_side: str | None    = None
        self._intel        = MarketIntelligenceEngine()
        self._macro        = MacroIntelligenceEngine()
        self._calendar     = EconomicCalendarEngine()
        self._surveillance = NewsSurveillanceEngine(scan_interval=120)
        self._smart_money  = SmartMoneyEngine()
        self._session      = SessionTracker()
        # Volume courant du trade — calculé dynamiquement selon grade + news
        self._current_volume: float = config.VOLUME
        # Trailing stop — prix du stop après TP1
        self._trail_stop: float | None = None
        # Circuit breaker — protection contre pertes consecutives
        self._consecutive_losses: int      = 0
        self._circuit_breaker_until: float = 0.0   # timestamp unix
        # Cooldown après clôture de position
        self._cooldown_until: float        = 0.0   # timestamp unix
        # SL initial du trade courant (R-multiple journal)
        self._initial_sl: float | None     = None
        # Take profit — TP1 réel + extrême favorable pour le profit-lock ratchet
        self._tp1_price: float | None      = None
        self._tp2_price: float | None      = None
        self._peak_price: float | None     = None
        # Confirmation d'attache SL/TP côté serveur — retry persistant tant que False
        self._sltp_confirmed: bool         = False
        self._sltp_last_retry: float       = 0.0
        # Throttle de la resynchronisation serveur du trail stop (profit-lock)
        self._last_sl_sync: float          = 0.0
        # Timestamp de placement de l'ordre courant (fallback position check)
        self._order_placed_at: float       = 0.0
        # Compteur journalier (persiste entre redémarrages, reset à minuit UTC)
        self._daily_trade_count: int       = 0
        self._trade_date: str              = ""    # YYYY-MM-DD UTC
        self._last_signal_type: str | None = None  # ex: "M15-SHORT"
        self._last_loss_time: float        = 0.0   # timestamp perte (pour expiration dedup)
        # Régime de marché courant
        self._current_regime: str          = "UNKNOWN"
        # Grade et kill zone pour le trade ouvert (pour trade recording)
        self._current_grade:    str        = "B"
        self._current_kill_zone: str       = ""
        # KRONOS — multiplicateur de sizing temporel
        self._kronos_mult: float           = 1.0
        # Fermeture précédente — signalés à signal_runner via bot_state.json
        self._last_close_reason: str | None = None
        self._last_pnl: float               = 0.0
        self._last_close_price: float | None = None
        # Pertes journalières réelles (ne se remet PAS à zéro après un gain, contrairement à consecutive_losses)
        self._daily_losses: int             = 0

    def _save_state(self):
        """Persiste l'état du trade en cours + dernier trade clôturé sur disque."""
        # entry_time en ISO pour compatibilité signal_runner.py (évite reset auto)
        entry_time_iso = None
        if self._order_placed_at:
            from datetime import timezone as _tz
            entry_time_iso = datetime.fromtimestamp(self._order_placed_at, tz=_tz.utc).isoformat()
        STATE_FILE.write_text(json.dumps({
            "entry_price":        self._entry_price,
            "trade_side":         self._trade_side,
            "tp1_done":           self._tp1_done,
            "last_entry_price":   self._last_entry_price,
            "last_trade_side":    self._last_trade_side,
            "consecutive_losses": self._consecutive_losses,
            "trail_stop":         self._trail_stop,
            "current_volume":     self._current_volume,
            "order_placed_at":    self._order_placed_at,
            "entry_time":         entry_time_iso,
            "daily_trade_count":  self._daily_trade_count,
            "trade_date":         self._trade_date,
            "cooldown_until":     self._cooldown_until,
            "daily_losses":       self._daily_losses,
            "sl":                 self._trail_stop,  # SL courant (initial ou trail)
            "initial_sl":         self._initial_sl,
            "tp1_price":          self._tp1_price,
            "tp2_price":          self._tp2_price,
            "peak_price":         self._peak_price,
            "sltp_confirmed":     self._sltp_confirmed,
            "last_close_reason":  self._last_close_reason,
            "last_pnl":           self._last_pnl,
            "last_close_price":   self._last_close_price,
        }), encoding="utf-8")

    def _load_state(self):
        """Restaure l'état depuis le disque (survit aux redémarrages)."""
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text(encoding="utf-8-sig"))  # tolère BOM PowerShell
                self._entry_price         = data.get("entry_price")
                self._trade_side          = data.get("trade_side")
                self._tp1_done            = data.get("tp1_done", False)
                self._last_entry_price    = data.get("last_entry_price")
                self._last_trade_side     = data.get("last_trade_side")
                self._consecutive_losses  = data.get("consecutive_losses", 0)
                self._trail_stop          = data.get("trail_stop") or data.get("sl")
                self._current_volume      = data.get("current_volume", config.VOLUME)
                self._order_placed_at     = data.get("order_placed_at", 0.0)
                self._cooldown_until      = data.get("cooldown_until", 0.0)
                self._initial_sl          = data.get("initial_sl")
                self._tp1_price           = data.get("tp1_price")
                self._tp2_price           = data.get("tp2_price")
                self._peak_price          = data.get("peak_price")
                self._sltp_confirmed      = data.get("sltp_confirmed", False)
                saved_date                = data.get("trade_date", "")
                today_utc                 = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                if saved_date == today_utc:
                    self._daily_trade_count = data.get("daily_trade_count", 0)
                    self._daily_losses      = data.get("daily_losses", 0)
                    self._trade_date        = saved_date
                else:
                    self._daily_trade_count = 0
                    self._daily_losses      = 0
                    self._trade_date        = today_utc
                    log.info(f"Nouveau jour UTC ({today_utc}) — compteur journalier remis à zéro")
                log.info(
                    f"État restauré: {self._trade_side} @ {self._entry_price} "
                    f"(tp1_done={self._tp1_done}, trail_stop={self._trail_stop}, "
                    f"pertes_consec={self._consecutive_losses})"
                )
                if self._last_entry_price:
                    log.info(
                        f"Dernier trade clôturé: {self._last_trade_side} @ {self._last_entry_price}"
                    )
            except Exception as e:
                log.warning(f"Impossible de restaurer l'état: {e}")
        else:
            log.info("Aucun état persisté — démarrage propre")

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self):
        self._pw       = None
        self._browser  = None
        self._cdp_sess = None   # aiohttp ClientSession for CDP

        # 1. CDP WebSocket direct sur Chrome existant (port 9222) — pas Playwright
        try:
            sess = aiohttp.ClientSession()
            async with sess.get("http://localhost:9222/json/list", timeout=aiohttp.ClientTimeout(total=4)) as r:
                tabs = await r.json(content_type=None)
            xtb_tab = next((t for t in tabs if "xstation5" in t.get("url", "") and t.get("type") == "page"), None)
            if xtb_tab:
                cdp_page = CdpPage(xtb_tab, sess)
                await cdp_page.connect()
                self._page     = cdp_page
                self._cdp_sess = sess
                log.info(f"CDP WebSocket connecté — XStation5 loggedIn: {_redact_url(xtb_tab['url'])[:60]}")
                return
            else:
                await sess.close()
                log.warning("CDP: Chrome actif mais aucun onglet XStation5 trouvé")
        except Exception as e:
            log.warning(f"CDP direct non disponible ({e.__class__.__name__}) — Playwright fallback")

        # 2. Fallback Playwright (async_playwright)
        import pathlib
        self._pw = await async_playwright().start()
        profile_dir = pathlib.Path(__file__).parent / ".playwright_profile"
        profile_dir.mkdir(exist_ok=True)
        try:
            ctx = await self._pw.chromium.launch_persistent_context(
                str(profile_dir),
                headless=False,
                viewport={"width": 1400, "height": 900},
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            self._browser = None
            self._page    = ctx.pages[0] if ctx.pages else await ctx.new_page()
            self._ctx     = ctx
            log.info(f"Playwright lancé — profil persistant: {profile_dir}")
        except Exception as e2:
            log.error(f"Playwright launch_persistent_context échoué: {e2}")
            raise

    async def stop(self):
        # Fermer CDP WebSocket
        cdp_page = self._page if isinstance(self._page, CdpPage) else None
        if cdp_page:
            await cdp_page.close()
        if self._cdp_sess:
            await self._cdp_sess.close()
        # Fermer Playwright si utilisé
        ctx = getattr(self, "_ctx", None)
        if ctx:
            await ctx.close()
        elif self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def _reconnect_browser(self) -> bool:
        """Reconnect to Chrome/xStation5 after browser crash or closure."""
        log.warning("Browser déconnecté — tentative de reconnexion automatique...")
        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass
        try:
            if self._cdp_sess and not self._cdp_sess.closed:
                await self._cdp_sess.close()
        except Exception:
            pass
        self._cdp_sess = None

        _chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]

        profile_dir = str(Path(__file__).parent / ".playwright_profile")

        for attempt in range(3):
            # Méthode A : CDP direct (CdpPage) — utilisée quand Playwright n'est pas disponible
            try:
                sess = aiohttp.ClientSession()
                async with sess.get("http://localhost:9222/json/list",
                                    timeout=aiohttp.ClientTimeout(total=4)) as r:
                    tabs = await r.json(content_type=None)
                xstb_tabs = [t for t in tabs if "xstation5" in t.get("url", "") and t.get("type") == "page"]

                # Purge des onglets XStation5 en trop — sans ça, chaque appel de
                # reconnexion (déclenché par le watchdog à chaque tick en échec)
                # empile un nouvel onglet sans jamais fermer les précédents.
                # Vu en prod : 416 puis 43 onglets accumulés, alourdissant Chrome
                # jusqu'à l'instabilité (cercle vicieux crash -> reconnect -> tab).
                if len(xstb_tabs) > 1:
                    for extra in xstb_tabs[1:]:
                        try:
                            await sess.get(f"http://localhost:9222/json/close/{extra['id']}",
                                          timeout=aiohttp.ClientTimeout(total=3))
                        except Exception:
                            pass
                    log.info(f"  {len(xstb_tabs)-1} onglet(s) XStation5 en trop fermé(s)")
                xtb_tab = xstb_tabs[0] if xstb_tabs else None

                if not xtb_tab:
                    # Aucun onglet XStation5 — en créer un
                    async with sess.get(f"http://localhost:9222/json/new?{self.LOGIN_URL}",
                                        timeout=aiohttp.ClientTimeout(total=4)) as r2:
                        xtb_tab = await r2.json(content_type=None)
                    await asyncio.sleep(5)
                cdp_page = CdpPage(xtb_tab, sess)
                await cdp_page.connect()
                self._page     = cdp_page
                self._cdp_sess = sess
                log.info(f"  Reconnecté CDP (tentative {attempt+1}) — {_redact_url(xtb_tab.get('url',''))[:60]}")
                return True
            except Exception as e_cdp:
                try:
                    await sess.close()
                except Exception:
                    pass

            # Méthode B : Playwright connect_over_cdp (si Playwright disponible)
            if self._pw is not None:
                try:
                    self._browser = await self._pw.chromium.connect_over_cdp("http://localhost:9222")
                    contexts = self._browser.contexts
                    pages = contexts[0].pages if contexts else []
                    xtb_page = next((p for p in pages if "xstation5" in p.url), None)
                    if xtb_page:
                        self._page = xtb_page
                        log.info(f"  Reconnecté Playwright (tentative {attempt+1}) — xStation5 trouvé")
                        return True
                    self._page = await (contexts[0].new_page() if contexts else self._browser.new_page())
                    await self._page.goto(self.LOGIN_URL, timeout=30000)
                    await asyncio.sleep(5)
                    log.info(f"  Reconnecté Playwright (tentative {attempt+1}) — navigation xStation5")
                    return True
                except Exception as e_pw:
                    log.warning(f"  CDP indisponible (tentative {attempt+1}/3): {e_pw}")

            if attempt < 2:
                # Ne relancer Chrome que s'il n'écoute vraiment plus sur 9222 —
                # sinon le superviseur externe (supervisor.ps1, qui fait la même
                # vérification indépendamment) et cette boucle finissent par
                # lancer plusieurs Chrome en parallèle sur le même profil.
                _cdp_up = False
                try:
                    async with aiohttp.ClientSession() as _probe:
                        async with _probe.get("http://localhost:9222/json/version",
                                             timeout=aiohttp.ClientTimeout(total=3)) as _r:
                            _cdp_up = _r.status == 200
                except Exception:
                    _cdp_up = False

                if not _cdp_up:
                    for chrome_path in _chrome_paths:
                        if os.path.exists(chrome_path):
                            subprocess.Popen([
                                chrome_path,
                                "--remote-debugging-port=9222",
                                "--no-first-run",
                                "--no-default-browser-check",
                                f"--user-data-dir={profile_dir}",
                            ])
                            log.info(f"  Chrome relancé: {chrome_path}")
                            break
                else:
                    log.info("  CDP déjà actif — pas de relance Chrome, retry connexion")
                await asyncio.sleep(12)

        log.error("Reconnexion impossible après 3 tentatives")
        return False

    # ── Authentification ──────────────────────────────────────────────────────

    async def login(self):
        p = self._page

        # Si déjà sur le dashboard (connexion CDP sur onglet loggedIn), ignorer
        if "loggedIn" in p.url:
            log.info("Déjà sur le dashboard — login ignoré")
            return

        await p.goto(self.LOGIN_URL, wait_until="domcontentloaded")

        # Vérifier si session active après navigation
        try:
            await p.wait_for_url("**/loggedIn**", timeout=5000)
            log.info("Session active — login ignoré")
            return
        except PWTimeout:
            pass

        # Attendre que le formulaire Angular soit rendu (spinner peut durer 30-60s)
        log.info("  Attente du formulaire de login (Angular)…")
        try:
            id_input = p.locator('input').filter(has_not_text="").or_(
                p.locator('input[type="text"], input[type="email"], input[name*="login" i], input[name*="user" i]')
            ).first
            # Attendre soit l'input soit la redirection loggedIn
            await id_input.wait_for(state="visible", timeout=60000)
        except PWTimeout:
            # Dernière chance : peut-être déjà redirigé
            if "loggedIn" in p.url:
                log.info("Session déjà active (détecté tard) — login ignoré")
                return
            await p.screenshot(path="login_timeout.png")
            log.error(f"Formulaire introuvable (URL: {_redact_url(p.url)})")
            raise

        # Sélecteurs spécifiques XStation5 (name="xslogin" / name="xspass")
        id_input_specific = p.locator('input[name="xslogin"]').first
        try:
            await id_input_specific.wait_for(state="visible", timeout=3000)
            await id_input_specific.fill(config.ACCOUNT_ID)
        except Exception:
            await id_input.fill(config.ACCOUNT_ID)

        pass_input = p.locator('input[name="xspass"], input[type="password"]').first
        await pass_input.wait_for(state="visible", timeout=10000)
        await pass_input.fill(config.PASSWORD)
        await asyncio.sleep(0.3)

        # Attendre qu'Angular compile les templates (résolution {{bindings}})
        await asyncio.sleep(3.0)

        # Stratégie 1 : clic bouton submit
        # XStation5 utilise input[type="button"][value="Login"], pas <button>
        submitted = await p.evaluate("""(() => {
            const selectors = [
                'input[type="button"]',
                'input[type="submit"]',
                'button[type="submit"]',
                'button.login-btn',
                'button.btn-primary',
                'form button:not([disabled])',
            ];
            for (const sel of selectors) {
                const btn = document.querySelector(sel);
                if (btn && btn.offsetParent !== null) {
                    btn.click();
                    return (btn.value || btn.innerText || '').trim().slice(0, 30) || 'submit-clicked';
                }
            }
            return null;
        })()""")
        log.info(f"  Bouton login cliqué: '{submitted}'")

        # Stratégie 2 : Enter via CDP Input.dispatchKeyEvent (Zone.js-compatible)
        # Toujours exécuté — belt-and-suspenders avec le clic bouton
        log.info("  Envoi Enter via CDP Input.dispatchKeyEvent sur password...")
        await pass_input.press("Enter")

        # Stratégie 3 : form.submit() JavaScript direct
        await asyncio.sleep(0.5)
        await p.evaluate("""() => {
            const form = document.querySelector('form');
            if (form) {
                try { form.dispatchEvent(new Event('submit', {bubbles:true, cancelable:true})); }
                catch(e) {}
                try { form.submit(); } catch(e) {}
            }
        }""")

        # Attendre le dashboard OU la 2FA (vérification email)
        try:
            await p.wait_for_url("**/loggedIn**", timeout=15000)
            log.info("Login XStation5 OK")
            # Sécurité : XStation5 laisse xslogin/xspass dans la query string.
            # Réécrire l'URL (history.replaceState) pour purger les identifiants.
            try:
                await p.evaluate(
                    "(() => { try { history.replaceState(null,'',"
                    "location.pathname + location.hash); } catch(e){} })()"
                )
            except Exception:
                pass
        except PWTimeout:
            # Détecter la dialog de code de vérification (2FA email)
            twofa_dialog = p.locator('input[placeholder*="code" i], input[placeholder*="vérif" i], .verification-code input, input[type="text"][maxlength]').first
            try:
                await twofa_dialog.wait_for(state="visible", timeout=3000)
                log.warning("  [2FA] Code de vérification requis — vérifier l'email XTB")
                log.warning("  [2FA] Coller le code dans: trading-bot/2fa_code.txt  (puis patienter)")
                import pathlib, time as _time
                code_file = pathlib.Path(__file__).parent / "2fa_code.txt"
                # Attendre que le fichier soit créé (max 5 minutes)
                for _ in range(300):
                    if code_file.exists():
                        code = code_file.read_text().strip()
                        if code:
                            code_file.unlink()
                            await twofa_dialog.fill(code)
                            await twofa_dialog.press("Enter")
                            log.info(f"  [2FA] Code soumis: {code}")
                            await p.wait_for_url("**/loggedIn**", timeout=15000)
                            log.info("Login XStation5 OK (2FA validé)")
                            return
                    _time.sleep(1)
                raise RuntimeError("Timeout 2FA — code non fourni dans 5 minutes")
            except Exception as e2:
                await p.screenshot(path="login_timeout.png")
                log.error(f"Login échoué (URL: {_redact_url(p.url)}) — {e2}")
                raise

    # ── Navigation ────────────────────────────────────────────────────────────

    async def ensure_us100_active(self):
        """S'assure que US100 est visible dans la barre Click & Trade."""
        p = self._page
        try:
            # Essayer de cliquer sur US100 dans le market watch
            await p.click('text=US100', timeout=5000)
            await asyncio.sleep(0.5)
        except PWTimeout:
            log.warning("US100 non trouvé dans market watch — tentative de recherche")
            # Try multiple search input selectors (xStation5 lang may vary)
            for search_sel in [
                'input[placeholder*="Rechercher" i]',
                'input[placeholder*="Search" i]',
                'input[placeholder*="Szukaj" i]',
                'input[type="search"]',
            ]:
                try:
                    await p.fill(search_sel, "US100", timeout=2000)
                    break
                except PWTimeout:
                    continue
            await asyncio.sleep(1.5)
            # Try multiple selectors for US100 in search results
            for click_sel in [
                'text=US100 CFD',
                'text=US100',
                '[data-test*="US100"]',
                '.instrument-name:has-text("US100")',
                'span:has-text("US100 CFD")',
            ]:
                try:
                    await p.click(click_sel, timeout=3000)
                    log.info(f"US100 sélectionné via sélecteur: {click_sel}")
                    return
                except PWTimeout:
                    continue
            raise PWTimeout("US100 non trouvé avec aucun sélecteur après recherche")

    # ── Placement d'ordre (Click & Trade) ────────────────────────────────────

    async def _set_stepper_value(self, stepper_input, value: float):
        """Remplit un stepper Angular (xs-stepper-input) avec la valeur donnée."""
        await stepper_input.click(click_count=3)
        await stepper_input.fill(str(round(value, 2)))
        await stepper_input.press("Tab")
        await asyncio.sleep(0.2)

    async def _configure_sl_tp(self, sl: float, tp: float, entry: float | None = None):
        """Configure SL/TP via le popup XStation5 Click & Trade.

        Les steppers du popup attendent des DISTANCES en points par rapport au prix
        d'entrée, pas des prix absolus. Si entry est fourni, convertir.
        """
        p = self._page
        # Déclencher mouseOver Angular sur la row du bouton SELL visible via JS
        await p.evaluate("""() => {
            const sellBtn = Array.from(document.querySelectorAll('button.xs-btn-sell'))
                .find(b => b.offsetParent !== null) || document.querySelector('button.xs-btn-sell');
            if (!sellBtn) return;
            const row = sellBtn.closest('.xui-click-trade-row, .instrument-row, tr, li')
                || sellBtn.parentElement;
            ['mouseenter', 'mouseover'].forEach(ev =>
                row.dispatchEvent(new MouseEvent(ev, {bubbles: true})));
        }""")
        await asyncio.sleep(0.4)
        # Cliquer SL/TP via JS direct — contourne ng-hide sans attendre visibilité
        clicked = await p.evaluate("""() => {
            const btn = document.querySelector('button.sl-tp-button');
            if (btn) { btn.click(); return true; }
            return false;
        }""")
        if not clicked:
            raise RuntimeError("Bouton sl-tp-button introuvable dans le DOM")
        await asyncio.sleep(0.5)

        # Remplir S/L et T/P via Angular (dispatch events) — distances en points
        if entry is not None:
            sl_val = round(abs(entry - sl), 1)
            tp_val = round(abs(tp - entry), 1)
        else:
            sl_val = round(sl, 2)
            tp_val = round(tp, 2)
        await p.evaluate(f"""() => {{
            const inputs = Array.from(document.querySelectorAll('input[name="stepperInput"]'))
                .filter(i => parseFloat(i.value) === 0 || i.value === '');
            if (inputs.length >= 2) {{
                [inputs[0], inputs[1]].forEach((inp, idx) => {{
                    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value').set;
                    nativeInputValueSetter.call(inp, idx === 0 ? '{sl_val}' : '{tp_val}');
                    inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                    inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                }});
            }}
        }}""")
        await asyncio.sleep(0.3)

        # Activer le toggle si nécessaire
        try:
            toggle = p.locator('.sltp-btn .toggle-slider, .sltp-btn input[type="checkbox"]').first
            await toggle.click(timeout=2000)
        except Exception:
            pass

        log.info(f"  SL/TP configuré: SL={sl_val} TP={tp_val}")

    async def _close_position_in_xtb(self):
        """Ferme la position ouverte dans XStation5 via CDP JavaScript."""
        p = self._page
        try:
            closed = await p.evaluate("""() => {
                // Stratégie 1 : sélecteurs CSS directs XStation5
                const cssSelectors = [
                    'button.close-position',
                    'button[class*="close"][class*="position"]',
                    'button[class*="xs-close"]',
                    '.open-position button.close',
                    'a.close-position',
                    '[data-test="close-position"]',
                    '[class*="position-close"]',
                    '[class*="closePosition"]',
                    'button[class*="close-btn"]',
                    '.positions-table button.close',
                    '.trade-close-btn',
                    'button.btn-close-trade',
                ];
                for (const sel of cssSelectors) {
                    try {
                        const btns = Array.from(document.querySelectorAll(sel))
                            .filter(b => b.offsetParent !== null);
                        if (btns.length) { btns[0].click(); return sel; }
                    } catch(e) {}
                }

                // Stratégie 2 : bouton avec aria-label / title contenant "close" ou "fermer"
                const ariaClose = Array.from(document.querySelectorAll('button, a, span'))
                    .filter(el => el.offsetParent !== null)
                    .find(el => {
                        const label = (el.getAttribute('aria-label') || el.getAttribute('title') || '').toLowerCase();
                        return label.includes('close') || label.includes('fermer') || label.includes('clore');
                    });
                if (ariaClose) { ariaClose.click(); return 'aria-close'; }

                // Stratégie 3 : chercher icône × / X dans les lignes de positions
                const xButtons = Array.from(document.querySelectorAll('button, span[class*="icon"], i[class*="icon"]'))
                    .filter(el => el.offsetParent !== null && (el.innerText === '×' || el.innerText === 'X' || el.innerText === '✕'));
                if (xButtons.length) { xButtons[0].click(); return 'x-icon'; }

                // Stratégie 4 : bouton texte "Fermer" / "Close" / "Clore"
                const textClose = Array.from(document.querySelectorAll('button'))
                    .filter(el => el.offsetParent !== null)
                    .find(el => {
                        const t = el.innerText.trim().toLowerCase();
                        return t === 'fermer' || t === 'close' || t === 'clore' || t === 'close position';
                    });
                if (textClose) { textClose.click(); return 'text-fermer'; }

                // Stratégie 5 : dropdown-toggle (pattern XStation5 réel)
                // Le bouton ⋮ ou "btn-primary dropdown-toggle" ouvre un menu avec "Close"
                const dropdowns = Array.from(document.querySelectorAll(
                    'button[class*="dropdown-toggle"], button.dropdown-toggle, [class*="more-btn"], button[class*="menu-btn"]'
                )).filter(b => b.offsetParent !== null);
                if (dropdowns.length) {
                    dropdowns[dropdowns.length - 1].click();
                    return '__DROPDOWN_CLICKED';
                }

                // Stratégie 6 : dump des boutons visibles pour diagnostic
                const visible = Array.from(document.querySelectorAll('button'))
                    .filter(b => b.offsetParent !== null)
                    .map(b => b.className + '|' + b.innerText.trim().slice(0,20))
                    .slice(0, 10).join(' ; ');
                return '__BUTTONS:' + visible;
            }""")

            if closed == '__DROPDOWN_CLICKED':
                # Attendre que le menu dropdown s'ouvre, puis cliquer Close/Fermer
                await asyncio.sleep(0.6)
                try:
                    dropdown_result = await p.evaluate("""() => {
                        const items = Array.from(document.querySelectorAll(
                            '.dropdown-menu a, .dropdown-menu button, .dropdown-item, [class*="dropdown"] li, [class*="context-menu"] li'
                        )).filter(el => el.offsetParent !== null);
                        const closeItem = items.find(el => {
                            const t = el.innerText.trim().toLowerCase();
                            return t.includes('close') || t.includes('fermer') || t.includes('clore');
                        });
                        if (closeItem) { closeItem.click(); return 'dropdown-close'; }
                        // Fallback : tout élément visible du dropdown
                        const allItems = items.map(el => el.innerText.trim().slice(0,20)).join(' | ');
                        return '__DROPDOWN_ITEMS:' + allItems;
                    }""")
                    if dropdown_result and not str(dropdown_result).startswith('__DROPDOWN_ITEMS:'):
                        log.info(f"  Position fermée via dropdown XStation5 ({dropdown_result})")
                        closed = dropdown_result
                    else:
                        log.warning(f"  Dropdown ouvert mais Close non trouvé. Items: {dropdown_result}")
                        closed = None
                except Exception as e:
                    log.warning(f"  Erreur lecture dropdown: {e}")
                    closed = None

            if closed and not str(closed).startswith('__BUTTONS:') and closed != '__DROPDOWN_CLICKED':
                log.info(f"  Position fermée via XStation5 (selector: {closed})")
                await asyncio.sleep(1.5)
                # Confirmer si popup
                try:
                    await p.evaluate("""() => {
                        const btns = Array.from(document.querySelectorAll('button'))
                            .filter(b => b.offsetParent !== null &&
                                ['OK','Confirmer','Confirm','Oui','Yes'].includes(b.innerText.trim()));
                        if (btns.length) { btns[0].click(); return true; }
                    }""")
                except Exception:
                    pass
            elif not closed or str(closed).startswith('__BUTTONS:'):
                if closed and closed.startswith('__BUTTONS:'):
                    log.warning(f"  Close introuvable. Boutons visibles: {closed[10:]}")
                else:
                    log.warning("  Bouton close position introuvable — vérifier XStation5 manuellement")
                # Fallback : naviguer vers positions et réessayer dans 3s
                try:
                    await p.evaluate("() => { const el = document.querySelector('[href*=\"positions\"], [ng-click*=\"position\"], a[class*=\"position\"]'); if(el) el.click(); }")
                    await asyncio.sleep(2.0)
                    await p.evaluate("""() => {
                        const btns = Array.from(document.querySelectorAll('button'))
                            .filter(b => b.offsetParent !== null);
                        const closeBtn = btns.find(b => b.className.includes('close') || b.innerText.trim().toLowerCase().includes('close'));
                        if (closeBtn) { closeBtn.click(); return true; }
                    }""")
                except Exception:
                    pass
        except Exception as e:
            log.error(f"  Erreur fermeture position: {e}")

    async def place_order(self, signal: str, levels: dict) -> bool:
        # Verrou absolu — 1 seule position à la fois, sans exception
        if self._entry_price is not None:
            log.error(
                f"  *** ORDRE BLOQUÉ *** entry_price déjà set ({self._entry_price}) — "
                f"position {self._trade_side} toujours active. Disciplne: 0 doublon toléré."
            )
            return False

        p = self._page
        try:
            await self.ensure_us100_active()

            # SL/TP Click & Trade AVANT le clic — pré-attache stop et limite côté serveur.
            # Le toggle se désactive à chaque refresh de session : le reconfigurer à chaque ordre.
            sl_tp_attached = False
            for attempt in range(2):
                try:
                    await self._configure_sl_tp(levels["sl"], levels["tp2"], levels.get("entry"))
                    sl_tp_attached = True
                    break
                except Exception as e:
                    if attempt == 0:
                        log.warning(f"  SL/TP pré-trade tentative 1 échouée ({e}) — retry dans 2s")
                        await asyncio.sleep(2)
                    else:
                        log.warning(f"  SL/TP pré-trade non configuré ({e}) — SL software seul")

            # Cliquer SELL ou BUY via les sélecteurs réels XStation5
            if signal == "SHORT":
                clicked = await p.evaluate("""() => {
                    const btns = Array.from(document.querySelectorAll('button.xs-btn-sell'));
                    const btn = btns.find(b => b.offsetParent !== null) || btns[0];
                    if (btn) { const price = btn.innerText.trim(); btn.click(); return price; }
                    return null;
                }""")
                log.info(f"  SELL cliqué @ {clicked}")
            else:
                clicked = await p.evaluate("""() => {
                    const btns = Array.from(document.querySelectorAll('button.xs-btn-buy'));
                    const btn = btns.find(b => b.offsetParent !== null) || btns[0];
                    if (btn) { const price = btn.innerText.trim(); btn.click(); return price; }
                    return null;
                }""")
                log.info(f"  BUY cliqué @ {clicked}")

            if not clicked or not isinstance(clicked, str):
                log.error(f"  Bouton {signal} introuvable ou clic non exécuté (retour: {clicked!r}) — ordre annulé")
                return False

            await asyncio.sleep(1.5)

            # Confirmer si une popup apparaît
            try:
                confirm = p.locator('button:has-text("Confirmer"), button:has-text("Confirm"), button:has-text("OK")').first
                await confirm.wait_for(timeout=3000)
                await confirm.click()
                log.info("  Ordre confirmé")
            except PWTimeout:
                pass  # Click & Trade = exécution immédiate sans confirmation

            # Enregistrer la position AVANT de tenter SL/TP (garantit que l'état persiste)
            self._entry_price       = levels["entry"]
            self._trade_side        = signal
            self._tp1_done          = False
            self._trail_stop        = levels.get("sl")  # SL initial comme trail_stop de départ
            self._initial_sl        = levels.get("sl")  # figé pour le calcul du R-multiple
            self._tp1_price         = levels.get("tp1")
            self._tp2_price         = levels.get("tp2")
            self._peak_price        = levels.get("entry")  # extrême favorable (profit-lock ratchet)
            self._sltp_confirmed    = sl_tp_attached
            self._sltp_last_retry   = time.time()
            self._order_placed_at   = time.time()
            self._trade_date        = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            self._daily_trade_count += 1
            self._save_state()

            # Filet post-ordre : si le pré-attachement a échoué, retenter après l'ordre
            if not sl_tp_attached:
                await asyncio.sleep(1.0)
                try:
                    await self._configure_sl_tp(levels["sl"], levels["tp2"], levels.get("entry"))
                    self._sltp_confirmed = True
                    self._save_state()
                except Exception:
                    log.warning(
                        f"SL/TP non configuré dans XStation5 — SL/TP software actif @ "
                        f"SL={levels['sl']} TP={levels.get('tp1')} — retry persistant à chaque scan"
                    )

            log.info(
                f"  Ordre placé: {signal} @ {levels['entry']} | "
                f"SL={levels['sl']} TP={levels['tp2']} | Volume={self._current_volume} lots"
            )
            return True

        except Exception as e:
            log.error(f"  Erreur placement ordre: {e}")
            _browser_closed = any(k in str(e).lower() for k in (
                "browser has been closed", "target page", "target closed",
                "connection refused", "websocket", "session closed",
            ))
            if _browser_closed:
                log.warning("  Browser fermé détecté — reconnexion puis retry...")
                reconnected = await self._reconnect_browser()
                if reconnected:
                    try:
                        await self.login()
                    except Exception:
                        pass
                    return await self.place_order(signal, levels)
            return False

    # ── Gestion de position ouverte ───────────────────────────────────────────

    async def manage_position(self, current_price: float, atr: float = 0.0):
        """
        Gère la position ouverte :
        - Détecte TP1 → active breakeven + trailing stop
        - Met à jour le trailing stop à chaque tick (après TP1)
        - atr : ATR H1 du scan courant pour calculer la distance du trail
        """
        if not self._entry_price or not self._trade_side:
            return

        pnl_pts = (
            (self._entry_price - current_price) if self._trade_side == "SHORT"
            else (current_price - self._entry_price)
        )

        if not self._tp1_done:
            # Vérifier si TP1 est atteint
            if pnl_pts >= config.BREAKEVEN_TRIGGER_PTS:
                log.info(
                    f"  TP1 atteint ({pnl_pts:+.0f} pts) → breakeven activé + trailing stop"
                )
                self._tp1_done   = True
                self._trail_stop = self._entry_price   # SL = entry (breakeven)
                self._save_state()
                await self._sync_server_sl()
        else:
            # Suivi de l'extrême favorable (profit-lock ratchet)
            if self._peak_price is None:
                self._peak_price = current_price
            elif self._trade_side == "LONG" and current_price > self._peak_price:
                self._peak_price = current_price
            elif self._trade_side == "SHORT" and current_price < self._peak_price:
                self._peak_price = current_price

            # Profit-lock : verrouiller PROFIT_LOCK_RATIO du profit max atteint
            # (remplace le simple breakeven — un trade à +60 ne peut plus finir à 0)
            lock = config.PROFIT_LOCK_RATIO
            if self._trade_side == "LONG":
                lock_level = round(self._entry_price + lock * (self._peak_price - self._entry_price), 2)
            else:
                lock_level = round(self._entry_price - lock * (self._entry_price - self._peak_price), 2)

            candidates = [lock_level]
            if atr > 0:
                trail_dist = atr * config.TRAILING_ATR_MULT
                candidates.append(round(current_price - trail_dist, 2) if self._trade_side == "LONG"
                                  else round(current_price + trail_dist, 2))

            new_trail = max(candidates) if self._trade_side == "LONG" else min(candidates)
            improved = (self._trail_stop is None
                        or (self._trade_side == "LONG" and new_trail > self._trail_stop)
                        or (self._trade_side == "SHORT" and new_trail < self._trail_stop))
            if improved:
                log.info(
                    f"  Trail relevé {self._trade_side}: {self._trail_stop} → {new_trail} "
                    f"(prix={current_price:.2f}, peak={self._peak_price:.2f}, lock={lock_level})"
                )
                self._trail_stop = new_trail
                self._save_state()
                await self._sync_server_sl()

    async def _sync_server_sl(self):
        """Pousse le trail_stop courant vers le SL serveur XTB.

        Sans ça, le SL/TP attaché à l'ouverture reste figé au niveau initial
        pendant toute la vie du trade : le profit-lock ne protège alors QUE
        tant que le bot tourne. Un gel du process pendant que le trail est
        resserré (breakeven, ratchet) expose le trade au SL ORIGINAL, bien
        plus large — c'est très probablement la cause de la perte de -218 pts
        du 20-21/07 (gel de 10h avec un trail resserré jamais remonté au serveur).

        Throttlé à 20s pour éviter de marteler le popup Click & Trade.
        """
        if not self._entry_price or not self._trail_stop or not self._tp2_price:
            return
        if time.time() - getattr(self, "_last_sl_sync", 0) < 20:
            return
        self._last_sl_sync = time.time()
        try:
            await self._configure_sl_tp(self._trail_stop, self._tp2_price, self._entry_price)
            log.info(f"  [SL SYNC] Stop serveur resynchronisé à {self._trail_stop}")
        except Exception as e:
            log.warning(f"  [SL SYNC] Échec resynchronisation serveur ({e}) — "
                       f"protection logicielle seule active pour ce niveau")

    # ── Lire le prix courant depuis la page ───────────────────────────────────

    async def get_current_price(self) -> float | None:
        """Lit le prix SELL courant — DOM XStation5 d'abord, yfinance en fallback."""
        try:
            price = await self._page.evaluate("""() => {
                const btns = Array.from(document.querySelectorAll('button.xs-btn-sell, .sell-price, [class*="sell"][class*="price"], .instrument-price'));
                const btn  = btns.find(b => b.offsetParent !== null) || btns[0];
                if (btn) { const v = parseFloat(btn.innerText.replace(/[^0-9.]/g, '')); if (!isNaN(v) && v > 1000) return v; }
                return null;
            }""")
            if price and float(price) > 1000:
                return float(price)
        except Exception:
            pass
        # Fallback yfinance — essayer NQZ26=F (décembre) puis NQ=F puis ^NDX
        # Validation anti-corruption : rejeter tout prix déviant >15% du dernier prix connu
        _ref = self._entry_price or getattr(self, "_last_known_price", None)
        for _ticker in ("NQZ26=F", "NQ=F", "^NDX", "QQQ"):
            try:
                import yfinance as yf
                df = yf.download(_ticker, period="1d", interval="1m", progress=False, auto_adjust=True)
                if df.empty:
                    continue
                c = df["Close"].squeeze()
                raw_price = float(c.iloc[-2])
                if raw_price < 1000:
                    continue
                # Sanity check : rejeter si déviation > 15% du prix de référence
                if _ref and abs(raw_price - _ref) / _ref > 0.15:
                    log.warning(f"  Prix yfinance {_ticker} suspect: {raw_price:.0f} vs ref {_ref:.0f} "
                                f"({abs(raw_price-_ref)/_ref*100:.0f}% écart) — ignoré")
                    continue
                if _ref:
                    self._last_known_price = raw_price
                return raw_price
            except Exception:
                continue
        return None

    async def _has_open_position(self) -> bool:
        """
        Détection de clôture basée sur le prix vs SL/trail_stop.
        N'utilise plus le DOM (sélecteurs xStation5 non fiables).
        La position est considérée ouverte jusqu'à ce que :
          1. Le prix ait clairement croisé le SL ou trail_stop (stop-out confirmé)
          2. L'ordre soit vieux de plus de 24h (position stale)
        """
        # Garde-temps COURT (20 s) : juste après l'entrée, un prix DOM/yfinance
        # stale peut être du mauvais côté. On saute alors uniquement le TP (éviter
        # une fausse prise de profit), MAIS le SL dur et le profit-lock sont
        # TOUJOURS honorés — bug du 17/07 : une grâce aveugle de 5 min a transformé
        # un +29 verrouillé en -67 en ignorant le stop pendant toute la vie du scalp.
        _fresh = self._order_placed_at and (time.time() - self._order_placed_at < 20)

        current = await self.get_current_price()
        if current is None:
            return True  # Pas de prix → bénéfice du doute

        # Take profit réel — fermer 100% à TP1, le gain est encaissé.
        # Exception régime TRENDING (Livermore) : laisser courir vers TP2 serveur,
        # le profit-lock ratchet sécurise 60% du pic en chemin.
        _riding_trend = getattr(self, "_current_regime", "") == "TRENDING"
        if not _fresh and config.TP1_FULL_CLOSE and self._tp1_price and not _riding_trend:
            tp_hit = (current <= self._tp1_price) if self._trade_side == "SHORT" \
                     else (current >= self._tp1_price)
            if tp_hit:
                log.info(f"  TP1 touché: prix {current:.2f} vs TP1 {self._tp1_price:.2f} "
                         f"— TAKE PROFIT, fermeture XStation5")
                await self._close_position_in_xtb()
                return False

        # En mode trend-riding : TP2 logiciel (backup du TP2 serveur)
        if not _fresh and _riding_trend and self._entry_price:
            _tp2 = getattr(self, "_tp2_price", None)
            if _tp2:
                tp2_hit = (current <= _tp2) if self._trade_side == "SHORT" else (current >= _tp2)
                if tp2_hit:
                    log.info(f"  TP2 touché (trend-riding): prix {current:.2f} vs TP2 {_tp2:.2f} "
                             f"— TAKE PROFIT, fermeture XStation5")
                    await self._close_position_in_xtb()
                    return False

        # Stop-out basé sur SL / trail_stop
        sl = self._trail_stop  # Mis à jour par manage_position après TP1
        if sl is None and self._entry_price:
            # Fallback : SL initial = entry ± 2× ATR estimé (200 pts)
            sl = (self._entry_price + 200) if self._trade_side == "SHORT" else (self._entry_price - 200)

        if sl and self._trade_side == "SHORT" and current >= sl:
            log.warning(f"  SL touché: prix {current:.2f} >= SL {sl:.2f} — fermeture XStation5")
            await self._close_position_in_xtb()
            return False
        if sl and self._trade_side == "LONG" and current <= sl:
            log.warning(f"  SL touché: prix {current:.2f} <= SL {sl:.2f} — fermeture XStation5")
            await self._close_position_in_xtb()
            return False

        # Position stale > 24h
        if self._order_placed_at and time.time() - self._order_placed_at > 86400:
            log.warning("  Position > 24h sans clôture détectée — reset forcé")
            return False

        return True  # Position toujours ouverte

    async def _recover_state(self):
        """Restaure l'état depuis le fichier persistant pour éviter les doublons au redémarrage."""
        self._load_state()
        if self._entry_price:
            current = await self.get_current_price()
            log.warning(
                f"Trade {self._trade_side} @ {self._entry_price} restauré depuis fichier — "
                f"prix actuel: {current} | Aucun nouvel ordre avant fermeture"
            )

    # ── Boucle principale ─────────────────────────────────────────────────────

    async def run(self):
        log.info("=" * 56)
        log.info("  XTB US100 TRADING BOT — PLAYWRIGHT")
        log.info(f"  Compte : {'DÉMO' if config.DEMO else '⚠️  RÉEL'} | {config.SYMBOL}")
        log.info(f"  Volume : {config.VOLUME} lots | Scan : {config.SCAN_INTERVAL_SEC}s")
        log.info("=" * 56)

        await self.start()
        try:
            await self.login()
        except Exception as _le:
            log.warning(f"  Login initial échoué ({_le.__class__.__name__}) — bot continue en mode scan-only")
            log.warning("  ACTION REQUISE : Se connecter manuellement à XStation5 dans Chrome")
        await self._recover_state()

        # Lancer la surveillance 24/7 en tâche de fond (non bloquante)
        asyncio.create_task(self._surveillance.start_background_loop())
        log.info("  Surveillance 24/7 démarrée (background)")

        while True:
            t0 = time.monotonic()
            try:
                await self._tick()
            except Exception as e:
                log.error(f"Erreur tick: {e}", exc_info=True)
                _browser_closed = any(k in str(e).lower() for k in (
                    "browser has been closed", "target page", "target closed",
                    "connection refused", "websocket", "session closed",
                ))
                if _browser_closed:
                    reconnected = await self._reconnect_browser()
                    if reconnected:
                        try:
                            await self.login()
                        except Exception:
                            pass
                else:
                    try:
                        await self._page.reload(timeout=15000)
                        await asyncio.sleep(3)
                    except Exception:
                        await self._reconnect_browser()

            elapsed  = time.monotonic() - t0
            # Tick rapide (5 s) quand une position est ouverte — réactivité SL/TP maximale
            _interval = (getattr(config, "SCAN_INTERVAL_POSITION_SEC", config.SCAN_INTERVAL_SEC)
                         if self._entry_price is not None else config.SCAN_INTERVAL_SEC)
            wait     = max(0, _interval - elapsed)
            now      = datetime.now(timezone.utc).strftime("%H:%M GMT")
            log.info(f"  ⏱  [{now}] Prochain scan dans {wait:.0f}s\n")
            await asyncio.sleep(wait)

    def _conviction_score(self, sig, macro, mi) -> int:
        """
        Score de conviction global 0–10 combinant technique + macro + sentiment.
        Pénalités : contre-tendance macro, MACD divergence D1.
        """
        score = 0
        # Technique (max 5)
        grade_pts = {"A+": 5, "A": 3, "B": 1}.get(sig.grade, 0)
        score += grade_pts
        # Macro (max 3)
        if "CONFIRME" in macro.trade_confirmation:
            score += 2
        if macro.liquidity.regime in ("RISK_ON" if sig.direction == "LONG" else ("RISK_OFF",)):
            score += 1
        # Sentiment (max 2)
        if mi.signal_reinforced:
            score += 2
        elif not mi.signal_contradicted:
            score += 1
        # Pénalités
        # MACD divergence D1 prise en compte via score_setup (déjà deduit du grade)
        # Chikou non confirmé : -1 (signal Ichimoku incomplet)
        if sig.direction == "LONG" and not getattr(sig, "_chikou_ok", True):
            score -= 1
        elif sig.direction == "SHORT" and not getattr(sig, "_chikou_ok", True):
            score -= 1
        return max(0, min(score, 10))

    async def _tick(self):
        now = datetime.now(timezone.utc).strftime("%H:%M GMT")
        log.info(f"── SCAN {now} " + "─" * 38)

        # 0a. Daily reset — compteur journalier remis à zéro au passage de minuit UTC
        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._trade_date and self._trade_date != today_utc:
            log.info(f"  [DAILY RESET] Nouveau jour {today_utc} — trades J-1: {self._daily_trade_count}")
            self._daily_trade_count = 0
            self._trade_date        = today_utc
            self._save_state()

        # 0aa. SKILL 15 — CDP Watchdog : ping 5s au lieu de timeout 180s natif
        if hasattr(self._page, "ping"):
            _cdp_alive = await self._page.ping(timeout=5.0)
            if not _cdp_alive:
                log.warning("  [CDP WATCHDOG] WebSocket mort — reconnexion immédiate (évite attente 180s)")
                reconnected = await self._reconnect_browser()
                if reconnected:
                    try:
                        await self.login()
                    except Exception:
                        pass
                return  # Skip ce tick, reprendre au prochain scan

        # 0ab. INTEL BOARD — synthèse décisionnelle toutes les 10 min (cache SKILL 20).
        # Uniquement à plat : les fetchers sont bloquants (urllib) et ne doivent pas
        # retarder le tick 5 s de gestion de position.
        if self._entry_price is None and time.time() - getattr(self, "_last_intel_board", 0) > 600:
            self._last_intel_board = time.time()
            try:
                from market_intel_extra import (fetch_fear_greed, fetch_cot_nasdaq,
                                                fetch_fedwatch, fetch_te_calendar,
                                                fetch_financialjuice)
                _fg, _cot, _fw = fetch_fear_greed(), fetch_cot_nasdaq(), fetch_fedwatch()
                _te, _fj = fetch_te_calendar(), fetch_financialjuice()
                _next_ev = (f"{_te['upcoming'][0]['event']} dans {_te['upcoming'][0]['in_hours']}h"
                            if _te["upcoming"] else "aucun < 24h")
                log.info(
                    f"  [INTEL BOARD] F&G:{_fg['score'] if _fg['score'] is not None else 'N/A'}({_fg['rating']}) | "
                    f"COT:{_cot['net_pct']:+.1f}% {_cot['bias']} | "
                    f"Fed:{_fw['implied_rate'] if _fw['implied_rate'] is not None else 'N/A'}% {_fw['bias']} | "
                    f"News:{_fj['bull']}B/{_fj['bear']}b | Prochain événement: {_next_ev}"
                )
            except Exception:
                pass

        # 0b. Vérification session XStation5 — relogin automatique si expirée
        try:
            _current_url = await self._page.evaluate("window.location.href")
            if _current_url:
                self._page._url_val = _current_url
            if _current_url and "login" in _current_url and "loggedIn" not in _current_url:
                log.warning("  [SESSION] XStation5 expirée — relogin automatique en cours...")
                try:
                    await self.login()
                    log.info("  [SESSION] Relogin effectué")
                except Exception as _login_err:
                    _notify = os.path.join(os.path.dirname(__file__), "PLEASE_LOGIN.txt")
                    if not os.path.exists(_notify):
                        with open(_notify, "w") as _f:
                            _f.write(
                                "XStation5 session expirée. Le bot ne peut pas trader.\n"
                                "Action requise : Ouvrir Chrome, aller sur xstation5.xtb.com\n"
                                "et se connecter manuellement (une seule fois suffit).\n"
                                "Ce fichier sera supprimé automatiquement au prochain scan.\n"
                            )
                    log.warning(f"  [SESSION] Relogin auto échoué — connexion manuelle requise dans Chrome (PLEASE_LOGIN.txt créé)")
                    return   # skip ce tick, réessayer au prochain scan
            else:
                # Session active — supprimer le fichier d'alerte si présent
                _notify = os.path.join(os.path.dirname(__file__), "PLEASE_LOGIN.txt")
                if os.path.exists(_notify):
                    os.remove(_notify)
                    log.info("  [SESSION] Session restaurée — PLEASE_LOGIN.txt supprimé")
        except Exception as _se:
            log.debug(f"  [SESSION] Vérif URL: {_se}")

        # 0. Force trade override — fichier force_trade.json
        import os, json as _json
        _force_file = os.path.join(os.path.dirname(__file__), "force_trade.json")
        if os.path.exists(_force_file):
            try:
                with open(_force_file) as _f:
                    _ft = _json.load(_f)
                os.remove(_force_file)
                log.info(f"  [FORCE] Ordre forcé détecté: {_ft}")
                await self.place_order(_ft["direction"], _ft)
                return
            except Exception as _e:
                log.warning(f"  [FORCE] Échec lecture force_trade.json: {_e}")

        # 1. Gestion position existante
        if self._entry_price:
            still_open = await self._has_open_position()
            if not still_open:
                current = await self.get_current_price()
                pnl = (self._entry_price - current) if (current and self._trade_side == "SHORT") \
                      else ((current - self._entry_price) if current else 0)
                log.info(f"  Position {self._trade_side} fermee (TP/SL) | P&L estime: {pnl:+.1f} pts — reset")
                # Enregistrer dans le tracker de session
                if current:
                    self._session.record_trade(
                        self._trade_side, self._entry_price, current, self._current_volume
                    )
                    self._session.print_stats()
                    # Session Analytics — enregistrement pour Kelly Criterion
                    try:
                        reason = "TP" if pnl > 0 else "SL"
                        record_trade(
                            direction  = self._trade_side,
                            entry      = self._entry_price,
                            exit_price = current,
                            volume     = self._current_volume,
                            grade      = self._current_grade,
                            kill_zone  = self._current_kill_zone,
                            regime     = self._current_regime,
                            reason     = reason,
                            sl         = self._initial_sl,
                        )
                        from session_analytics import export_zella_journal
                        export_zella_journal(load_history(days=60))
                    except Exception:
                        pass
                _cd = (getattr(config, "COOLDOWN_AFTER_WIN_SEC", config.COOLDOWN_AFTER_TRADE_SEC)
                       if pnl > 0 else
                       getattr(config, "COOLDOWN_AFTER_LOSS_SEC", config.COOLDOWN_AFTER_TRADE_SEC))
                self._cooldown_until = time.time() + _cd
                log.info(f"  Cooldown: {_cd // 60} min avant prochain trade ({'gain' if pnl > 0 else 'perte'})")
                # Mémoriser la clôture pour signal_runner (last_close_reason/pnl/price dans bot_state)
                self._last_close_reason = "TP" if pnl > 0 else "SL"
                self._last_pnl          = round(pnl, 2)
                self._last_close_price  = current
                if pnl < 0:
                    self._last_entry_price = self._entry_price
                    self._last_trade_side  = self._trade_side
                    self._consecutive_losses += 1
                    self._daily_losses       += 1
                    self._last_loss_time = time.time()
                    log.warning(
                        f"  Trade fermé en perte — règle anti-re-entrée activée pour {self._trade_side} "
                        f"| Pertes consécutives: {self._consecutive_losses}"
                    )
                    if self._consecutive_losses >= 2:
                        pause_sec = 1800
                        self._circuit_breaker_until = time.time() + pause_sec
                        log.warning(
                            f"  *** CIRCUIT BREAKER *** {self._consecutive_losses} pertes consécutives — "
                            f"pause {pause_sec//60} min"
                        )
                    # Gate journalier — arrêt si limite USD dépassée
                    if self._session.is_daily_loss_exceeded():
                        log.warning(
                            f"  *** DAILY LOSS GATE *** {self._session.daily_pnl_usd:.2f}$ < "
                            f"-{config.MAX_DAILY_LOSS_USD}$ — trading suspendu pour la journée"
                        )
                else:
                    self._last_entry_price   = None
                    self._last_trade_side    = None
                    self._consecutive_losses = 0
                    self._last_signal_type   = None
                    log.info("  Trade fermé en profit — re-entrée libre autorisée | Reset circuit breaker")
                self._entry_price    = None
                self._trade_side     = None
                self._tp1_done       = False
                self._trail_stop     = None
                self._sltp_confirmed = False
                self._current_volume = config.VOLUME
                self._save_state()
                return  # Attendre le prochain scan après clôture (cooldown actif)
            else:
                # Retry persistant : tant que le SL/TP n'est pas confirmé côté serveur,
                # retenter à chaque scan (throttlé 15s) — garantit un TP sur CHAQUE
                # opération même si l'attache initiale a échoué (DOM lent/indisponible).
                if (not self._sltp_confirmed and time.time() - self._sltp_last_retry > 15
                        and self._initial_sl and self._tp2_price and self._entry_price):
                    self._sltp_last_retry = time.time()
                    try:
                        await self._configure_sl_tp(
                            self._initial_sl, self._tp2_price, self._entry_price)
                        self._sltp_confirmed = True
                        self._save_state()
                        log.info("  [TP RETRY] SL/TP attaché avec succès côté serveur")
                    except Exception as e:
                        log.warning(f"  [TP RETRY] Tentative échouée ({e}) — SL/TP software actif, reprise au prochain scan")

                current = await self.get_current_price()
                if current:
                    pnl = (self._entry_price - current) if self._trade_side == "SHORT" \
                          else (current - self._entry_price)
                    log.info(
                        f"  Position {self._trade_side} @ {self._entry_price} | "
                        f"Prix: {current:.2f} | P&L: {pnl:+.1f} pts"
                        + (f" | Trail: {self._trail_stop}" if self._trail_stop else "")
                        + ("" if self._sltp_confirmed else " | [TP non confirmé serveur]")
                    )
                    # Passer l'ATR H1 courant pour le trailing stop (calculé plus bas si nécessaire)
                    # On utilise sig.atr si disponible — ici on passe 0, recalculé dans manage_position
                    await self.manage_position(current)
                else:
                    log.info(f"  Position {self._trade_side} @ {self._entry_price} — prix indisponible")
                return  # 1 seul trade à la fois

        # 2a. Daily loss gate — bloquer si limite journalière dépassée
        if self._session.is_daily_loss_exceeded():
            log.warning(
                f"  *** DAILY LOSS GATE *** {self._session.daily_pnl_usd:.2f}$ — "
                f"limite {config.MAX_DAILY_LOSS_USD}$ atteinte, trading suspendu"
            )
            return

        # 2a2. Max trades par jour (persistant entre redémarrages)
        if self._daily_trade_count >= config.MAX_TRADES_PER_SESSION:
            log.warning(
                f"  *** MAX TRADES JOUR *** {self._daily_trade_count}/{config.MAX_TRADES_PER_SESSION} — "
                f"limite journalière atteinte, reprise demain"
            )
            return

        # 2a3. Cooldown post-trade
        if self._cooldown_until > time.time():
            remaining = int((self._cooldown_until - time.time()) / 60)
            log.info(f"  Cooldown post-trade — reprise dans {remaining} min")
            return

        # 2b. Circuit breaker — pause forcée après pertes consécutives
        if self._circuit_breaker_until > time.time():
            remaining = int((self._circuit_breaker_until - time.time()) / 60)
            log.warning(f"  *** CIRCUIT BREAKER actif *** — reprise dans {remaining} min")
            return

        # 2c. Calendrier économique — protection avant annonces majeures
        cal = self._calendar.assess()
        self._calendar.print_status(cal)
        if cal.is_blackout:
            log.warning(f"  BLACKOUT CALENDRIER — trade suspendu: {cal.message}")
            return

        # 2d. Smart Money — SEC EDGAR Form 4 + OpenInsider + Congress (non-bloquant)
        try:
            sm = self._smart_money.assess()
            self._smart_money.log_signal(sm)
        except Exception:
            pass

        # 3. Analyse multi-timeframe PRO (D1 + H4 + H1 + OB + FVG + Kill Zone)
        loop = asyncio.get_event_loop()
        mtf  = await loop.run_in_executor(None, load_mtf)

        # 3a. Market Regime Classification (Choppiness Index + ADX + ATR)
        try:
            regime = classify_regime(mtf.get("H1"))
            self._current_regime = regime.name
            log.info(f"  [REGIME] {regime_summary(regime)}")
            if not regime.trade_ok:
                log.warning(
                    f"  SKIP REGIME {regime.name} (CI={regime.choppiness}) — "
                    f"stratégie tendance inefficace en marché {'range' if regime.name == 'RANGING' else 'volatile'}"
                )
                return
        except Exception as _re:
            log.debug(f"  Regime detection error: {_re}")

        # 3b. KRONOS — Time-Cycle Intelligence (Hurst + calendrier + saisonnalité)
        try:
            _kronos = evaluate_kronos(mtf.get("H1"), mtf.get("D1"))
            log.info(f"  [KRONOS] {kronos_summary(_kronos)}")
            if _kronos.veto:
                log.warning(f"  SKIP KRONOS: {_kronos.reason}")
                return
            self._kronos_mult = _kronos.multiplier
        except Exception as _ke:
            log.debug(f"  KRONOS error: {_ke}")
            self._kronos_mult = 1.0

        sig  = generate_pro_signal(mtf)
        print_pro_signal(sig)

        if sig.direction == "SKIP" or sig.grade == "SKIP":
            return

        # 4. Macro Intelligence (banques centrales + corrélations + liquidité)
        macro = await self._macro.full_analysis(technical_signal=sig.direction)
        self._macro.print_dashboard(macro)

        if "CONTRE" in macro.trade_confirmation:
            log.warning(f"  SKIP: {macro.trade_confirmation}")
            return

        # 5. Sentiment news + VIX rapide
        mi = await self._intel.analyze(technical_signal=sig.direction)
        self._intel.print_report(mi, sig.direction, sig.to_levels())

        if not mi.trade_allowed:
            log.info("  SKIP: VIX extrême + sentiment très négatif")
            return

        # 5b. Surveillance news 24/7 — breaking news / événements CB / géopolitique
        news_safe, news_reason, size_factor = await self._surveillance.quick_check(sig.direction)
        log.info(f"  [SURVEILLANCE] {news_reason} | factor={size_factor:.1f}")
        if not news_safe:
            log.warning(f"  SKIP: Surveillance news — {news_reason}")
            return

        # 6. Score de conviction final
        conviction = self._conviction_score(sig, macro, mi)
        # Seuil adaptatif : Grade B (M15 fallback aligne D1+H4) accepte 3/10
        # Grade A/A+ exigent 4/10 — signal H1 direct avec confluences multiples
        min_conviction = 2 if sig.grade == "B" else 3
        log.info(
            f"  [CONVICTION] Score final: {conviction}/10 — Grade: {sig.grade} "
            f"| seuil: {min_conviction} | size_factor={size_factor:.1f}"
        )

        if conviction < min_conviction:
            log.info(f"  SKIP: conviction insuffisante (< {min_conviction}/10)")
            return

        # 7a. Filtre signal type répété — bloquer le même fallback M15 après une perte
        #     Expiration automatique après 4h (une session) pour éviter le blocage multi-jours
        _DEDUP_EXPIRY = 4 * 3600
        current_signal_type = sig.h1_signal  # ex: "M15-SHORT", "M15-LONG", ou signal H1
        if (self._last_signal_type and
                self._last_signal_type == current_signal_type and
                self._consecutive_losses > 0 and
                time.time() - self._last_loss_time < _DEDUP_EXPIRY):
            log.warning(
                f"  SKIP signal répété après perte: {current_signal_type} déjà tenté et perdu — "
                f"attendre un nouveau setup différent"
            )
            return

        # 7b. Filtre re-entrée — DÉSACTIVÉ (continuation de tendance autorisée)

        # 8. Sizing dynamique — grade × news factor × Kelly × volume de base
        grade_factor = {"A+": config.VOLUME_A_PLUS, "A": config.VOLUME_A, "B": config.VOLUME_B}.get(sig.grade, 0.5)

        # Kelly Criterion (demi-Kelly cappé entre 10%-30%)
        kelly_factor = 1.0
        history = []
        try:
            history = load_history(days=60)
            kelly_data = compute_kelly(history)
            kelly_factor = kelly_data["kelly"]  # 1.0 si données insuffisantes
            if kelly_data.get("win_rate") is not None:
                log.info(
                    f"  [KELLY] {kelly_data['note']} | "
                    f"WR={kelly_data['win_rate']:.0%} PF={kelly_data.get('profit_factor','N/A')}"
                )
        except Exception:
            kelly_factor = 1.0

        # Facteur kill zone — pénalise les zones prouvées perdantes sur l'historique réel
        # (ex: LONDON_OPEN/NY_OPEN codées "haute liquidité" mais négatives en pratique)
        kz_factor = 1.0
        try:
            from session_analytics import compute_kill_zone_factor
            kz_factor, kz_note = compute_kill_zone_factor(sig.kill_zone or "HORS_ZONE", history)
            if kz_factor < 1.0:
                log.info(f"  [KILL ZONE] {kz_note}")
        except Exception:
            kz_factor = 1.0

        kronos_mult = self._kronos_mult
        combined_factor = round(grade_factor * size_factor * kelly_factor * kz_factor * kronos_mult, 2)
        self._current_volume = round(config.VOLUME * combined_factor, 3)
        self._current_volume = max(config.MIN_VOLUME, min(config.MAX_VOLUME, self._current_volume))
        log.info(
            f"  [SIZING] Grade={sig.grade} ({grade_factor:.2f}x) × News({size_factor:.2f}x) "
            f"× Kelly({kelly_factor:.2f}x) × KZ({kz_factor:.2f}x) × Kronos({kronos_mult:.2f}x) "
            f"= {combined_factor:.2f}x → volume={self._current_volume} lots"
        )

        # Mémoriser grade + kill zone pour le trade recording
        self._current_grade     = sig.grade
        self._current_kill_zone = sig.kill_zone or ""

        # Mémoriser le type de signal avant exécution
        self._last_signal_type = sig.h1_signal
        levels = sig.to_levels()
        await self.place_order(sig.direction, levels)


# ═══════════════════════════════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ═══════════════════════════════════════════════════════════════════════════════
_LOCK_FILE = Path(__file__).parent / "bot.lock"
_lock_fh = None  # gardé en vie tout le process — le verrou OS se libère seul au crash/exit


def _acquire_single_instance_lock() -> bool:
    """Empêche deux instances du bot de tourner en même temps.

    Découvert le 06/08 : une fenêtre de redémarrage (superviseur tue l'ancien
    process puis relance avant qu'il soit vraiment mort) a fait tourner deux
    process en parallèle quelques secondes — chacun a détecté indépendamment
    la même clôture de position et écrit sa propre entrée dans
    trade_history.jsonl avec un prix légèrement différent, polluant le Kelly
    Criterion et les stats kill zone. Le verrou OS (msvcrt.locking) se libère
    automatiquement à la mort du process, même en cas de crash — pas besoin
    de cleanup explicite.
    """
    global _lock_fh
    try:
        _lock_fh = open(_LOCK_FILE, "w")
        msvcrt.locking(_lock_fh.fileno(), msvcrt.LK_NBLCK, 1)
        return True
    except OSError:
        return False


if __name__ == "__main__":
    if not _acquire_single_instance_lock():
        log.error(
            "Une autre instance du bot tourne déjà (bot.lock verrouillé) — "
            "arrêt immédiat pour éviter les doublons de trade."
        )
        sys.exit(1)

    bot = XStation5Bot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        log.info("Bot arrêté (Ctrl+C).")
        asyncio.run(bot.stop())
