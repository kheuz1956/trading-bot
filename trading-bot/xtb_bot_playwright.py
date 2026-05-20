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
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 on Windows stdout to avoid cp1252 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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
from strategy_pro import load_mtf, generate_pro_signal, print_pro_signal, ProSignal

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
    """NQ=F = NASDAQ 100 E-mini futures, proxy fidèle du US100 XTB."""
    raw = yf.download("NQ=F", period="10d", interval="1h",
                      progress=False, auto_adjust=True)
    if raw.empty:
        raise RuntimeError("yfinance: aucune donnée reçue pour NQ=F")
    # Aplatir le MultiIndex si présent (yfinance >= 0.2.x)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    # Reconstruire un DataFrame propre avec des Series strictement 1D
    idx = raw.index.get_level_values(0) if isinstance(raw.index, pd.MultiIndex) else raw.index
    df = pd.DataFrame({
        "Open":   raw["Open"].to_numpy().ravel(),
        "High":   raw["High"].to_numpy().ravel(),
        "Low":    raw["Low"].to_numpy().ravel(),
        "Close":  raw["Close"].to_numpy().ravel(),
        "Volume": raw["Volume"].to_numpy().ravel(),
    }, index=idx)
    log.info(f"  {len(df)} bougies H1 chargées (NQ=F)")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# BOT PLAYWRIGHT
# ═══════════════════════════════════════════════════════════════════════════════

STATE_FILE = Path(__file__).parent / "bot_state.json"


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
        self.daily_loss = 0.0
        self._intel       = MarketIntelligenceEngine()
        self._macro       = MacroIntelligenceEngine()
        self._calendar    = EconomicCalendarEngine()
        self._surveillance = NewsSurveillanceEngine(scan_interval=120)

    def _save_state(self):
        """Persiste l'état du trade en cours + dernier trade clôturé sur disque."""
        STATE_FILE.write_text(json.dumps({
            "entry_price":       self._entry_price,
            "trade_side":        self._trade_side,
            "tp1_done":          self._tp1_done,
            "last_entry_price":  self._last_entry_price,
            "last_trade_side":   self._last_trade_side,
        }), encoding="utf-8")

    def _load_state(self):
        """Restaure l'état depuis le disque (survit aux redémarrages)."""
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                self._entry_price      = data.get("entry_price")
                self._trade_side       = data.get("trade_side")
                self._tp1_done         = data.get("tp1_done", False)
                self._last_entry_price = data.get("last_entry_price")
                self._last_trade_side  = data.get("last_trade_side")
                log.info(
                    f"État restauré: {self._trade_side} @ {self._entry_price} "
                    f"(tp1_done={self._tp1_done})"
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
        self._pw = await async_playwright().start()

        # Essayer de se connecter au Chrome existant (lancé avec --remote-debugging-port=9222)
        try:
            self._browser = await self._pw.chromium.connect_over_cdp("http://localhost:9222")
            # Récupérer la page XStation5 si déjà ouverte, sinon en créer une
            contexts = self._browser.contexts
            pages    = contexts[0].pages if contexts else []
            xtb_page = next((p for p in pages if "xstation5" in p.url), None)
            if xtb_page:
                self._page = xtb_page
                log.info(f"Connecté au Chrome existant — onglet XStation5 trouvé: {self._page.url}")
            else:
                self._page = await contexts[0].new_page() if contexts else await self._browser.new_page()
                log.info("Connecté au Chrome existant — nouvel onglet créé")
        except Exception as e:
            log.warning(f"CDP non disponible ({e}) — lancement d'un nouveau Chrome")
            self._browser = await self._pw.chromium.launch(
                headless=False,
                channel="chrome",
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            )
            ctx        = await self._browser.new_context(viewport={"width": 1400, "height": 900})
            self._page = await ctx.new_page()
            log.info("Playwright lancé (Chrome nouveau)")

    async def stop(self):
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

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
            log.error(f"Formulaire introuvable (URL: {p.url})")
            raise

        await id_input.fill(config.ACCOUNT_ID)

        pass_input = p.locator('input[type="password"]').first
        await pass_input.wait_for(state="visible", timeout=10000)
        await pass_input.fill(config.PASSWORD)
        await asyncio.sleep(0.3)

        # Cliquer le bouton login (premier bouton visible et non-désactivé)
        submitted = await p.evaluate("""() => {
            const btn = Array.from(document.querySelectorAll('button'))
                .find(b => b.offsetParent !== null && !b.disabled);
            if (btn) { btn.click(); return btn.innerText.trim().slice(0, 30); }
            return false;
        }""")
        log.info(f"  Bouton cliqué: '{submitted}'")

        # Fallback : Enter
        if not submitted:
            await pass_input.press("Enter")

        try:
            await p.wait_for_url("**/loggedIn**", timeout=30000)
            log.info("Login XStation5 OK")
        except PWTimeout:
            await p.screenshot(path="login_timeout.png")
            log.error(f"Login échoué (URL: {p.url}) — vérifier identifiants dans .env")
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
            await p.fill('input[placeholder*="Rechercher" i]', "US100")
            await asyncio.sleep(1)
            await p.click('text=US100 CFD', timeout=5000)

    # ── Placement d'ordre (Click & Trade) ────────────────────────────────────

    async def _set_stepper_value(self, stepper_input, value: float):
        """Remplit un stepper Angular (xs-stepper-input) avec la valeur donnée."""
        await stepper_input.click(click_count=3)
        await stepper_input.fill(str(round(value, 2)))
        await stepper_input.press("Tab")
        await asyncio.sleep(0.2)

    async def _configure_sl_tp(self, sl: float, tp: float):
        """Configure SL/TP via le popup XStation5 Click & Trade."""
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

        # Remplir S/L et T/P via Angular (dispatch events)
        sl_val  = round(sl, 2)
        tp_val  = round(tp, 2)
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

    async def place_order(self, signal: str, levels: dict) -> bool:
        p = self._page
        try:
            await self.ensure_us100_active()

            # Configurer SL/TP avant l'ordre
            try:
                await self._configure_sl_tp(levels["sl"], levels["tp2"])
            except Exception as e:
                log.warning(f"SL/TP config partielle: {e}")

            # Cliquer SELL ou BUY via les sélecteurs réels XStation5
            if signal == "SHORT":
                # xs-btn-sell = bouton rouge VENDRE dans le market watch
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

            await asyncio.sleep(1)

            # Confirmer si une popup apparaît
            try:
                confirm = p.locator('button:has-text("Confirmer"), button:has-text("Confirm"), button:has-text("OK")').first
                await confirm.wait_for(timeout=3000)
                await confirm.click()
                log.info("  Ordre confirmé")
            except PWTimeout:
                pass  # Click & Trade = exécution immédiate sans confirmation

            self._entry_price = levels["entry"]
            self._trade_side  = signal
            self._tp1_done    = False
            self._save_state()
            return True

        except Exception as e:
            log.error(f"  Erreur placement ordre: {e}")
            return False

    # ── Gestion de position ouverte ───────────────────────────────────────────

    async def manage_position(self, current_price: float):
        if not self._entry_price or not self._trade_side:
            return
        if self._tp1_done:
            return

        pnl_pts = (
            (self._entry_price - current_price) if self._trade_side == "SHORT"
            else (current_price - self._entry_price)
        )
        log.info(f"  Position {self._trade_side} | P&L: {pnl_pts:+.1f} pts")

        if pnl_pts >= config.BREAKEVEN_TRIGGER_PTS:
            log.info("  TP1 atteint → breakeven activé (SL ramené au point d'entrée)")
            self._tp1_done = True
            self._save_state()

    # ── Lire le prix courant depuis la page ───────────────────────────────────

    async def get_current_price(self) -> float | None:
        """Lit le prix SELL courant de US100 depuis le bouton xs-btn-sell."""
        try:
            price = await self._page.evaluate("""() => {
                const btns = Array.from(document.querySelectorAll('button.xs-btn-sell'));
                const btn  = btns.find(b => b.offsetParent !== null) || btns[0];
                return btn ? parseFloat(btn.innerText.replace(',', '.')) : null;
            }""")
            return float(price) if price else None
        except Exception:
            return None

    async def _has_open_position(self) -> bool:
        """Vérifie si une position US100 est encore ouverte dans le panel XStation5."""
        try:
            count = await self._page.evaluate("""() => {
                // Lignes de positions ouvertes dans le tableau du bas
                const rows = document.querySelectorAll(
                    '.positions-table tbody tr, [ng-repeat*="position"], .open-positions tr[class*="row"]'
                );
                return rows.length;
            }""")
            return int(count) > 0
        except Exception:
            return True  # Incertain → supposer ouverte pour éviter doublon

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
        await self.login()
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
                # Si la page semble déconnectée, recharger
                try:
                    await self._page.reload(timeout=15000)
                    await asyncio.sleep(3)
                except Exception:
                    pass

            elapsed = time.monotonic() - t0
            wait    = max(0, config.SCAN_INTERVAL_SEC - elapsed)
            now     = datetime.now(timezone.utc).strftime("%H:%M GMT")
            log.info(f"  ⏱  [{now}] Prochain scan dans {wait:.0f}s\n")
            await asyncio.sleep(wait)

    def _conviction_score(self, sig, macro, mi) -> int:
        """Score de conviction global 0–10 combinant technique + macro + sentiment."""
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
        return min(score, 10)

    async def _tick(self):
        now = datetime.now(timezone.utc).strftime("%H:%M GMT")
        log.info(f"── SCAN {now} " + "─" * 38)

        # 1. Gestion position existante
        if self._entry_price:
            still_open = await self._has_open_position()
            if not still_open:
                current = await self.get_current_price()
                pnl = (self._entry_price - current) if (current and self._trade_side == "SHORT") \
                      else ((current - self._entry_price) if current else 0)
                log.info(f"  Position {self._trade_side} fermee (TP/SL) | P&L estime: {pnl:+.1f} pts — reset")
                # Mémoriser uniquement si fermé en PERTE (SL touché)
                # Si en profit (TP), la re-entrée dans la tendance est autorisée librement
                if pnl < 0:
                    self._last_entry_price = self._entry_price
                    self._last_trade_side  = self._trade_side
                    log.warning(f"  Trade fermé en perte — règle anti-re-entrée activée pour {self._trade_side}")
                else:
                    # TP atteint : reset du filtre, nouvelle entrée libre dans la tendance
                    self._last_entry_price = None
                    self._last_trade_side  = None
                    log.info(f"  Trade fermé en profit — re-entrée libre autorisée")
                self._entry_price = None
                self._trade_side  = None
                self._tp1_done    = False
                self._save_state()
            else:
                current = await self.get_current_price()
                if current:
                    pnl = (self._entry_price - current) if self._trade_side == "SHORT" \
                          else (current - self._entry_price)
                    log.info(
                        f"  Position {self._trade_side} @ {self._entry_price} | "
                        f"Prix: {current:.2f} | P&L: {pnl:+.1f} pts"
                    )
                    await self.manage_position(current)
                else:
                    log.info(f"  Position {self._trade_side} @ {self._entry_price} — prix indisponible")
                return  # 1 seul trade à la fois

        # 2. Calendrier économique — protection avant annonces majeures
        cal = self._calendar.assess()
        self._calendar.print_status(cal)
        if cal.is_blackout:
            log.warning(f"  BLACKOUT CALENDRIER — trade suspendu: {cal.message}")
            return

        # 3. Analyse multi-timeframe PRO (D1 + H4 + H1 + OB + FVG + Kill Zone)
        loop = asyncio.get_event_loop()
        mtf  = await loop.run_in_executor(None, load_mtf)
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
        log.info(f"  [CONVICTION] Score final: {conviction}/10 — Grade: {sig.grade} | size_factor={size_factor:.1f}")

        if conviction < 4:
            log.info("  SKIP: conviction insuffisante (< 4/10)")
            return

        # 7. Filtre re-entrée défavorable
        # LONG  : n'ouvre pas si nouvel entry > dernier entry LONG  (on n'achète pas plus cher)
        # SHORT : n'ouvre pas si nouvel entry < dernier entry SHORT (on ne vend pas moins cher)
        new_entry = sig.to_levels()["entry"]
        if self._last_entry_price and self._last_trade_side == sig.direction:
            if sig.direction == "LONG" and new_entry > self._last_entry_price:
                log.warning(
                    f"  SKIP re-entrée LONG : {new_entry:.2f} > dernier entry {self._last_entry_price:.2f} "
                    f"— prix défavorable, attendre repli"
                )
                return
            if sig.direction == "SHORT" and new_entry < self._last_entry_price:
                log.warning(
                    f"  SKIP re-entrée SHORT: {new_entry:.2f} < dernier entry {self._last_entry_price:.2f} "
                    f"— prix défavorable, attendre rebond"
                )
                return

        # 8. Exécution (volume adapté si size_factor < 1.0)
        levels = sig.to_levels()
        if size_factor < 1.0:
            log.info(f"  Volume réduit à {size_factor*100:.0f}% — news tension ({news_reason})")
        await self.place_order(sig.direction, levels)


# ═══════════════════════════════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    bot = XStation5Bot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        log.info("Bot arrêté (Ctrl+C).")
        asyncio.run(bot.stop())
