#!/usr/bin/env python3
"""
Smart Money Monitor — SEC EDGAR Form 4, OpenInsider, Congressional Trades

Surveille les flux institutionnels et insiders sur les composants Nasdaq 100.
Utilisé comme signal de confluence supplémentaire (non-bloquant).

Sources :
  - SEC EDGAR  : RSS atom des Form 4 (dépôts insiders officiels)
  - OpenInsider: screener achats/ventes >500k USD sur 24h
  - Capitol Trades : transactions récentes des élus du Congrès US

Cache : 15 min (données insiders peu fréquentes, évite le rate-limiting).
"""

from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.request import Request, urlopen

log = logging.getLogger("xtb_pw")

# ── Composants Nasdaq 100 à surveiller ────────────────────────────────────────
_NQ100 = frozenset({
    "AAPL", "MSFT", "NVDA", "AMZN", "META",
    "GOOGL", "GOOG", "TSLA", "AVGO", "COST",
    "NFLX", "AMD", "QCOM", "ADBE", "MU",
    "ORCL", "CRM", "AMAT", "LRCX", "KLAC",
    "SNPS", "CDNS", "MRVL", "PANW", "CRWD",
    "ASML", "INTC", "TXN", "ABNB", "PYPL",
})

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

_CACHE_TTL = 900  # 15 min


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class _Flow:
    buys: int = 0
    sells: int = 0
    tickers: list[str] = field(default_factory=list)


@dataclass
class SmartMoneySignal:
    score: float = 0.0           # -1.0 (vente massive) → +1.0 (achat massif)
    edgar_tickers: list[str] = field(default_factory=list)
    insider_buys: int = 0
    insider_sells: int = 0
    congress_buys: int = 0
    congress_sells: int = 0
    notable_tickers: list[str] = field(default_factory=list)
    summary: str = "Aucune donnée disponible"
    ok: bool = False              # True si au moins une source a répondu


# ── Moteur ────────────────────────────────────────────────────────────────────

class SmartMoneyEngine:
    """
    Agrège les flux de transactions insiders et gouvernementaux
    pour les composants Nasdaq 100.
    Cache interne : 15 min pour éviter le rate-limiting.
    """

    def __init__(self):
        self._cache: SmartMoneySignal | None = None
        self._cache_until: float = 0.0

    # ── Utilitaires ───────────────────────────────────────────────────────────

    def _fetch(self, url: str, timeout: int = 12) -> bytes:
        req = Request(url, headers={
            "User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        with urlopen(req, timeout=timeout) as r:
            return r.read()

    def _strip_tags(self, html: str) -> str:
        return re.sub(r"<[^>]+>", " ", html)

    # ── 1. SEC EDGAR Form 4 ───────────────────────────────────────────────────

    def _edgar_form4(self) -> _Flow:
        """
        RSS Atom officiel SEC pour les Form 4 récents.
        Title format: "4 - CompanyName (TICKER) (CIK) filed YYYY-MM-DD"
        """
        flow = _Flow()
        try:
            url = (
                "https://www.sec.gov/cgi-bin/browse-edgar"
                "?action=getcurrent&type=4&dateb=&owner=include"
                "&count=40&search_text=&output=atom"
            )
            raw = self._fetch(url, timeout=15)
            root = ET.fromstring(raw)
            ns = {"a": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("a:entry", ns):
                title = (entry.findtext("a:title", "", ns) or "").upper()
                # Format: "4 - COMPANY NAME (TICKER) (0000123456)"
                m = re.search(r"\(([A-Z]{2,5})\)\s*\(0{0,6}\d+\)", title)
                if m and m.group(1) in _NQ100:
                    ticker = m.group(1)
                    if ticker not in flow.tickers:
                        flow.tickers.append(ticker)
                    # Form 4 sans parsing XML complet : on comptabilise comme signal neutre
                    # Le volume et la direction nécessiteraient de fetcher chaque XML individuel
                    flow.buys += 1
        except Exception as e:
            log.debug(f"[SMART_MONEY] EDGAR: {e}")
        return flow

    # ── 2. OpenInsider ────────────────────────────────────────────────────────

    def _openinsider(self) -> _Flow:
        """
        Screener OpenInsider — transactions insiders >500k USD, dernier jour.
        Colonnes clés : ticker (lien /TICKER), type (P-Purchase / S-Sale / etc.)
        """
        flow = _Flow()
        try:
            url = (
                "https://openinsider.com/screener"
                "?s=&o=&pl=&ph=&ll=&lh=&fd=1&fdr=&td=0&tdr="
                "&fdlyl=&fdlyh=&daysago=&ob=&vl=500&vh="
                "&ocl=&och=&sic1=-1&sicl=100&sich=9999&grp=0"
                "&nfl=&nfh=&nil=&nih=&nol=&noh="
                "&v2l=&v2h=&oc2l=&oc2h=&sortcol=0&cnt=30&page=1"
            )
            html = self._fetch(url, timeout=15).decode("utf-8", errors="replace")

            # Chaque ligne de la table : extraire ticker + type de transaction
            for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL):
                # Ticker : href="/TICKER" suivi du texte du lien
                ticker_m = re.search(r'href="/([A-Z]{2,5})"[^>]*>\1<', row)
                if not ticker_m or ticker_m.group(1) not in _NQ100:
                    continue
                ticker = ticker_m.group(1)

                clean = self._strip_tags(row).upper()
                is_buy  = bool(re.search(r"\bP\s*[-–]\s*PURCHASE\b|\bP\b", clean))
                is_sell = bool(re.search(r"\bS\s*[-–]\s*SALE\b|\bS\b", clean))

                if is_buy and not is_sell:
                    flow.buys += 1
                    if ticker not in flow.tickers:
                        flow.tickers.append(ticker)
                elif is_sell:
                    flow.sells += 1
                    if ticker not in flow.tickers:
                        flow.tickers.append(ticker)

        except Exception as e:
            log.debug(f"[SMART_MONEY] OpenInsider: {e}")
        return flow

    # ── 3. Capitol Trades (Congrès) ───────────────────────────────────────────

    def _congress_trades(self) -> _Flow:
        """
        Capitol Trades — dernières transactions des membres du Congrès US.
        On cherche les tickers NQ100 et la direction (buy/sell).
        """
        flow = _Flow()
        try:
            url = (
                "https://www.capitoltrades.com/trades"
                "?pageSize=30&assetType=stock"
            )
            html = self._fetch(url, timeout=15).decode("utf-8", errors="replace")

            # Découper en blocs par trade (articles ou lignes de table)
            # Capitol Trades a des articles ou des <tr> contenant le ticker et le type
            segments = re.split(r"(?=<(?:tr|article|li)[^>]*>)", html)
            for seg in segments:
                clean = self._strip_tags(seg).upper()
                # Chercher un ticker NQ100 dans le segment
                ticker = None
                for t in _NQ100:
                    if re.search(rf"\b{re.escape(t)}\b", clean):
                        ticker = t
                        break
                if not ticker:
                    continue

                is_buy  = bool(re.search(r"\b(BUY|PURCHASE|BOUGHT)\b", clean))
                is_sell = bool(re.search(r"\b(SELL|SALE|SOLD)\b", clean))

                if is_buy and not is_sell:
                    flow.buys += 1
                    if ticker not in flow.tickers:
                        flow.tickers.append(ticker)
                elif is_sell:
                    flow.sells += 1
                    if ticker not in flow.tickers:
                        flow.tickers.append(ticker)

        except Exception as e:
            log.debug(f"[SMART_MONEY] CapitolTrades: {e}")
        return flow

    # ── Évaluation complète ───────────────────────────────────────────────────

    def assess(self) -> SmartMoneySignal:
        """
        Retourne le signal smart money agrégé (EDGAR + OpenInsider + Congress).
        Résultat mis en cache 15 min.
        """
        now = time.monotonic()
        if self._cache and now < self._cache_until:
            return self._cache

        edgar = self._edgar_form4()
        oi    = self._openinsider()
        cong  = self._congress_trades()

        total_buys  = oi.buys  + cong.buys
        total_sells = oi.sells + cong.sells
        total       = total_buys + total_sells

        score   = round((total_buys - total_sells) / total, 2) if total > 0 else 0.0
        notable = list(dict.fromkeys(edgar.tickers + oi.tickers + cong.tickers))
        ok      = bool(edgar.tickers or total > 0)

        parts: list[str] = []
        if edgar.tickers:
            parts.append(f"EDGAR Form4: {edgar.tickers}")
        if oi.buys or oi.sells:
            parts.append(f"Insiders {oi.buys}B/{oi.sells}S {oi.tickers or []}")
        if cong.buys or cong.sells:
            parts.append(f"Congress {cong.buys}B/{cong.sells}S {cong.tickers or []}")

        sig = SmartMoneySignal(
            score=score,
            edgar_tickers=edgar.tickers,
            insider_buys=oi.buys,
            insider_sells=oi.sells,
            congress_buys=cong.buys,
            congress_sells=cong.sells,
            notable_tickers=notable,
            summary=" | ".join(parts) if parts else "Aucune transaction NQ100 notable",
            ok=ok,
        )

        self._cache = sig
        self._cache_until = now + _CACHE_TTL
        return sig

    def log_signal(self, sig: SmartMoneySignal) -> None:
        """Log formaté du signal smart money dans le logger principal."""
        direction = (
            "BULL" if sig.score >= 0.3 else
            "BEAR" if sig.score <= -0.3 else
            "NEUTRE"
        )
        log.info(
            f"  [SMART_MONEY] score={sig.score:+.2f}({direction}) | "
            f"Insiders {sig.insider_buys}B/{sig.insider_sells}S | "
            f"Congress {sig.congress_buys}B/{sig.congress_sells}S | "
            f"{sig.summary}"
        )
