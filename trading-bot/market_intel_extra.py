"""
Market Intelligence Extra — sources additionnelles pour le scoring NQ.

Sources : Trading Economics, FinancialJuice, CME FedWatch (via ZQ=F),
COT CFTC, CNN Fear & Greed, Myfxbook sentiment retail,
MCP Claude (Alpha Vantage RSI/ATR + TipRanks sentiment — via mcp_context.json).

Chaque fetcher est fail-safe : cache TTL + retour NEUTRE en cas d'échec.
Aucune source n'est bloquante pour la génération de signal.
"""

import json
import os
import re
import time
import urllib.request

_MCP_CONTEXT_PATH = os.path.join(os.path.dirname(__file__), "mcp_context.json")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

_cache: dict[str, tuple[float, dict]] = {}


def _get(url: str, timeout: int = 8, headers: dict | None = None) -> str:
    h = {"User-Agent": _UA}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _cached(key: str, ttl: int, fetch):
    now = time.time()
    if key in _cache and now - _cache[key][0] < ttl:
        return _cache[key][1]
    result = fetch()
    _cache[key] = (now, result)
    return result


# ── CNN Fear & Greed ─────────────────────────────────────────────────────────

def fetch_fear_greed() -> dict:
    """CNN Fear & Greed Index. <25 extreme fear (LONG contrarian),
    >75 extreme greed (SHORT contrarian)."""
    def _fetch():
        try:
            raw = _get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
                       headers={"Accept": "application/json",
                                "Referer": "https://edition.cnn.com/markets/fear-and-greed",
                                "Origin": "https://edition.cnn.com"})
            data = json.loads(raw)
            score = float(data["fear_and_greed"]["score"])
            rating = data["fear_and_greed"]["rating"]
            if score <= 25:
                bias = "LONG_CONTRARIAN"
            elif score >= 75:
                bias = "SHORT_CONTRARIAN"
            else:
                bias = "NEUTRE"
            return {"score": round(score, 1), "rating": rating, "bias": bias, "ok": True}
        except Exception:
            return {"score": None, "rating": "unknown", "bias": "NEUTRE", "ok": False}
    return _cached("fear_greed", 1800, _fetch)


# ── COT CFTC (E-mini Nasdaq-100) ─────────────────────────────────────────────

def fetch_cot_nasdaq() -> dict:
    """Rapport COT hebdo CFTC — positionnement non-commercial (smart money)
    sur E-MINI NASDAQ-100. Net long > 0 = biais HAUSSIER institutionnel."""
    def _fetch():
        try:
            raw = _get("https://www.cftc.gov/dea/newcot/deafut.txt", timeout=15)
            for line in raw.splitlines():
                if "NASDAQ-100" in line.upper() and "MINI" in line.upper():
                    parts = [p.strip() for p in line.split(",")]
                    # Format legacy : col 8 = noncomm long, col 9 = noncomm short
                    nc_long, nc_short = int(parts[8]), int(parts[9])
                    net = nc_long - nc_short
                    total = nc_long + nc_short
                    net_pct = round(100 * net / total, 1) if total else 0.0
                    bias = "HAUSSIER" if net_pct > 10 else "BAISSIER" if net_pct < -10 else "NEUTRE"
                    return {"net": net, "net_pct": net_pct, "bias": bias, "ok": True}
            return {"net": 0, "net_pct": 0.0, "bias": "NEUTRE", "ok": False}
        except Exception:
            return {"net": 0, "net_pct": 0.0, "bias": "NEUTRE", "ok": False}
    return _cached("cot_nq", 21600, _fetch)  # publié le vendredi — 6h de cache


# ── CME FedWatch (répliqué via Fed Funds futures ZQ=F) ───────────────────────

def fetch_fedwatch() -> dict:
    """Probabilité implicite de mouvement Fed via les futures Fed Funds (ZQ).
    Prix ZQ = 100 - taux implicite. Baisse anticipée = HAUSSIER NQ."""
    def _fetch():
        try:
            import yfinance as yf
            df = yf.download("ZQ=F", period="5d", interval="1d", progress=False, auto_adjust=False)
            if df.empty:
                raise ValueError("no data")
            close = df["Close"].squeeze()
            implied_rate = round(100.0 - float(close.iloc[-1]), 3)
            prev_rate = round(100.0 - float(close.iloc[0]), 3)
            drift = round(implied_rate - prev_rate, 3)
            # drift < 0 : marché price des baisses → HAUSSIER NQ
            bias = "HAUSSIER" if drift < -0.02 else "BAISSIER" if drift > 0.02 else "NEUTRE"
            return {"implied_rate": implied_rate, "drift_5d": drift, "bias": bias, "ok": True}
        except Exception:
            return {"implied_rate": None, "drift_5d": 0.0, "bias": "NEUTRE", "ok": False}
    return _cached("fedwatch", 3600, _fetch)


# ── Myfxbook — sentiment retail NAS100 ───────────────────────────────────────

def fetch_myfxbook_sentiment() -> dict:
    """Sentiment communauté Myfxbook sur NAS100 — signal CONTRARIAN :
    >70% retail long = SHORT bias, >70% retail short = LONG bias."""
    def _fetch():
        try:
            html = _get("https://www.myfxbook.com/community/outlook/NAS100", timeout=10)
            m = re.search(r"Short[^0-9]{0,80}?(\d{1,2})%[^0-9]{0,200}?Long[^0-9]{0,80}?(\d{1,2})%",
                          html, re.S | re.I)
            if not m:
                m = re.search(r"(\d{1,2})%\s*</td>.*?(\d{1,2})%\s*</td>", html, re.S)
            if not m:
                raise ValueError("pattern not found")
            short_pct, long_pct = int(m.group(1)), int(m.group(2))
            if long_pct >= 70:
                bias = "SHORT_CONTRARIAN"
            elif short_pct >= 70:
                bias = "LONG_CONTRARIAN"
            else:
                bias = "NEUTRE"
            return {"long_pct": long_pct, "short_pct": short_pct, "bias": bias, "ok": True}
        except Exception:
            return {"long_pct": None, "short_pct": None, "bias": "NEUTRE", "ok": False}
    return _cached("myfxbook", 900, _fetch)


# ── Trading Economics — calendrier éco (API guest) ───────────────────────────

def fetch_te_calendar() -> dict:
    """Événements USD High impact des prochaines 24h.
    Backend : ForexFactory JSON (l'API guest Trading Economics est morte — HTTP 410).
    high_event_soon = ne pas ouvrir de position dans l'heure précédant la news."""
    def _fetch():
        try:
            from datetime import datetime, timezone
            raw = _get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=10)
            events = json.loads(raw)
            now = datetime.now(timezone.utc)
            upcoming = []
            for ev in events:
                if ev.get("country") != "USD" or ev.get("impact") != "High":
                    continue
                try:
                    ts = datetime.fromisoformat(ev["date"])
                except Exception:
                    continue
                delta_h = (ts - now).total_seconds() / 3600
                if 0 <= delta_h <= 24:
                    upcoming.append({"event": ev.get("title", "?"), "in_hours": round(delta_h, 1)})
            upcoming.sort(key=lambda e: e["in_hours"])
            high_soon = any(e["in_hours"] <= 1.0 for e in upcoming)
            return {"upcoming": upcoming[:5], "high_event_soon": high_soon, "ok": True}
        except Exception:
            return {"upcoming": [], "high_event_soon": False, "ok": False}
    return _cached("te_calendar", 1800, _fetch)


# ── FinancialJuice — headlines temps réel ────────────────────────────────────

_FJ_BEARISH = ("miss", "cut", "recession", "hawkish", "tariff", "war", "crash",
               "selloff", "sell-off", "downgrade", "layoff", "shutdown")
_FJ_BULLISH = ("beat", "dovish", "rally", "surge", "stimulus", "cut rates",
               "soft landing", "upgrade", "record high")


def fetch_financialjuice() -> dict:
    """Headlines FinancialJuice (RSS) — comptage bull/bear sur les 20 derniers titres."""
    def _fetch():
        try:
            raw = _get("https://www.financialjuice.com/feed.ashx?xy=rss", timeout=10)
            titles = re.findall(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", raw)[1:21]
            bear = sum(1 for t in titles for k in _FJ_BEARISH if k in t.lower())
            bull = sum(1 for t in titles for k in _FJ_BULLISH if k in t.lower())
            bias = "HAUSSIER" if bull > bear + 2 else "BAISSIER" if bear > bull + 2 else "NEUTRE"
            return {"bull": bull, "bear": bear, "bias": bias,
                    "headlines": titles[:3], "ok": True}
        except Exception:
            return {"bull": 0, "bear": 0, "bias": "NEUTRE", "headlines": [], "ok": False}
    return _cached("financialjuice", 300, _fetch)


# ── MCP Claude context (Alpha Vantage RSI/ATR + TipRanks) ────────────────────

def fetch_mcp_context() -> dict:
    """Lit mcp_context.json (écrit par Claude via MCP plugins).
    TTL = ttl_hours défini dans le fichier (défaut 4h).
    Retourne un dict avec bias/confluences ou NEUTRE si absent/périmé."""
    try:
        if not os.path.exists(_MCP_CONTEXT_PATH):
            return {"bias": "NEUTRE", "ok": False, "reason": "file_absent"}
        with open(_MCP_CONTEXT_PATH, encoding="utf-8") as f:
            data = json.load(f)
        updated_at = data.get("_meta", {}).get("updated_at", "")
        ttl_hours = float(data.get("_meta", {}).get("ttl_hours", 4))
        if updated_at:
            from datetime import datetime, timezone
            ts = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
            if age_h > ttl_hours:
                return {"bias": "NEUTRE", "ok": False, "reason": f"stale_{age_h:.1f}h"}
        macro = data.get("macro_bias", {})
        sentiment = data.get("sentiment", {})
        technicals = data.get("technicals", {})
        return {
            "bias": macro.get("direction", "NEUTRE"),
            "confidence": macro.get("confidence", 0.0),
            "tipranks_sentiment": sentiment.get("tipranks_sentiment", "unknown"),
            "contrarian_signal": sentiment.get("contrarian_signal", "NEUTRE"),
            "rsi_h1": technicals.get("rsi_h1"),
            "rsi_trend": technicals.get("rsi_trend", "unknown"),
            "atr_h1": technicals.get("atr_h1"),
            "atr_trend": technicals.get("atr_trend", "unknown"),
            "reasoning": macro.get("reasoning", ""),
            "ok": True,
        }
    except Exception:
        return {"bias": "NEUTRE", "ok": False, "reason": "parse_error"}


# ── Agrégation SKILL 20 ──────────────────────────────────────────────────────

def analyze_extra_intel(direction: str) -> dict:
    """Agrège les 6 sources en confluences/warnings pour score_setup.

    Retourne {confluences: [...], warnings: [...], veto: bool, detail: {...}}.
    veto=True uniquement si un événement macro critique tombe dans l'heure.
    """
    fg   = fetch_fear_greed()
    cot  = fetch_cot_nasdaq()
    fw   = fetch_fedwatch()
    myfx = fetch_myfxbook_sentiment()
    te   = fetch_te_calendar()
    fj   = fetch_financialjuice()
    mcp  = fetch_mcp_context()

    confluences: list[str] = []
    warnings:    list[str] = []

    dir_bias = "HAUSSIER" if direction == "LONG" else "BAISSIER"
    contrarian_match = "LONG_CONTRARIAN" if direction == "LONG" else "SHORT_CONTRARIAN"
    contrarian_against = "SHORT_CONTRARIAN" if direction == "LONG" else "LONG_CONTRARIAN"

    if fg["bias"] == contrarian_match:
        confluences.append(f"F&G {fg['score']} ({fg['rating']}) — contrarian {direction}")
    elif fg["bias"] == contrarian_against:
        warnings.append(f"F&G {fg['score']} ({fg['rating']}) — foule contre {direction}")

    if cot["bias"] == dir_bias:
        confluences.append(f"COT net {cot['net_pct']:+.1f}% — smart money aligné {direction}")
    elif cot["ok"] and cot["bias"] != "NEUTRE":
        warnings.append(f"COT net {cot['net_pct']:+.1f}% — smart money contre {direction}")

    if fw["bias"] == dir_bias:
        confluences.append(f"FedWatch drift {fw['drift_5d']:+.3f} — taux alignés {direction}")
    elif fw["ok"] and fw["bias"] != "NEUTRE":
        warnings.append(f"FedWatch drift {fw['drift_5d']:+.3f} — taux contre {direction}")

    if myfx["bias"] == contrarian_match:
        confluences.append(f"Myfxbook retail {myfx['long_pct']}%L/{myfx['short_pct']}%S — fade the crowd")
    elif myfx["bias"] == contrarian_against:
        warnings.append(f"Myfxbook retail extrême dans le sens du trade — prudence")

    if fj["bias"] == dir_bias:
        confluences.append(f"FinancialJuice {fj['bull']}B/{fj['bear']}b — news flow aligné")
    elif fj["ok"] and fj["bias"] != "NEUTRE":
        warnings.append(f"FinancialJuice {fj['bull']}B/{fj['bear']}b — news flow contre {direction}")

    veto = False
    if te["high_event_soon"]:
        ev = te["upcoming"][0] if te["upcoming"] else {"event": "?", "in_hours": 0}
        warnings.append(f"TE: {ev['event']} dans {ev['in_hours']}h — VETO nouvelle entrée")
        veto = True

    # MCP Claude — contrarian TipRanks + RSI/ATR cross-validation
    if mcp["ok"]:
        bias = mcp.get("bias", "NEUTRE")
        contrarian = mcp.get("contrarian_signal", "NEUTRE")
        rsi = mcp.get("rsi_h1")
        rsi_trend = mcp.get("rsi_trend", "")
        atr_trend = mcp.get("atr_trend", "")
        sentiment_label = mcp.get("tipranks_sentiment", "")

        if direction == "LONG":
            if contrarian == "BULLISH":
                confluences.append(
                    f"MCP TipRanks {sentiment_label} → contrarian LONG "
                    f"(RSI H1={rsi}, {rsi_trend})"
                )
            if atr_trend == "compressing":
                confluences.append("MCP ATR H1 compressant → qualité entrée améliorée")
            if bias == "cautious_bullish" and rsi and float(rsi) > 55:
                confluences.append(
                    f"MCP macro_bias={bias} conf={mcp.get('confidence', 0):.0%}"
                )
            if rsi and float(rsi) > 70:
                warnings.append(f"MCP RSI H1={rsi} proche surachat — prudence LONG")
        elif direction == "SHORT":
            if contrarian == "BEARISH":
                confluences.append(
                    f"MCP TipRanks {sentiment_label} → contrarian SHORT "
                    f"(RSI H1={rsi}, {rsi_trend})"
                )
            if bias in ("cautious_bearish", "bearish"):
                confluences.append(
                    f"MCP macro_bias={bias} conf={mcp.get('confidence', 0):.0%}"
                )
            if rsi and float(rsi) < 30:
                warnings.append(f"MCP RSI H1={rsi} proche survente — prudence SHORT")

    return {
        "confluences": confluences,
        "warnings": warnings,
        "veto": veto,
        "detail": {"fear_greed": fg, "cot": cot, "fedwatch": fw,
                   "myfxbook": myfx, "te": te, "financialjuice": fj, "mcp": mcp},
    }
