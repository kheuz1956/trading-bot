"""
Session Analytics — Historique des trades + Kelly Criterion + stats par kill zone
Inspiré de : Steenbarger "The Daily Trading Coach" + Van Tharp "Trade Your Way to Financial Freedom"

Kelly Criterion: f* = W - (1-W)/R
  W = taux de réussite (win rate)
  R = avg_win / avg_loss (rapport gain/perte)
  Half-Kelly (sécurisé) = f*/2, cappé entre 10% et 25%
"""

from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict
from typing import Optional

HISTORY_FILE = Path(__file__).parent / "trade_history.jsonl"
MIN_TRADES_FOR_KELLY = 15   # minimum avant d'appliquer Kelly
KELLY_MIN = 0.10            # fraction min de la taille de base
KELLY_MAX = 0.30            # fraction max (30% → évite surlevier)


@dataclass
class TradeRecord:
    timestamp:   str    # ISO UTC
    direction:   str    # LONG | SHORT
    entry:       float
    exit_price:  float
    pnl_pts:     float
    pnl_usd:     float
    volume:      float
    grade:       str    # A+ | A | B
    kill_zone:   str
    regime:      str    # TRENDING | RANGING | VOLATILE | TRANSITIONING
    reason:      str    # TP1 | TP2 | SL | MANUAL | TRAIL


def record_trade(
    direction:  str,
    entry:      float,
    exit_price: float,
    volume:     float,
    grade:      str = "B",
    kill_zone:  str = "",
    regime:     str = "UNKNOWN",
    reason:     str = "MANUAL",
    pip_value:  float = 20.0,
) -> TradeRecord:
    """Enregistre un trade terminé dans trade_history.jsonl."""
    pnl_pts = (entry - exit_price) if direction == "SHORT" else (exit_price - entry)
    pnl_usd = pnl_pts * volume * pip_value
    rec = TradeRecord(
        timestamp  = datetime.now(timezone.utc).isoformat(),
        direction  = direction,
        entry      = round(entry, 2),
        exit_price = round(exit_price, 2),
        pnl_pts    = round(pnl_pts, 2),
        pnl_usd    = round(pnl_usd, 2),
        volume     = round(volume, 3),
        grade      = grade,
        kill_zone  = kill_zone or "HORS_ZONE",
        regime     = regime,
        reason     = reason,
    )
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(rec)) + "\n")
    return rec


def load_history(days: int = 60) -> list[dict]:
    """Charge les N derniers jours de trade_history.jsonl."""
    if not HISTORY_FILE.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    records = []
    with open(HISTORY_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                ts = datetime.fromisoformat(r.get("timestamp", "2000-01-01T00:00:00+00:00"))
                if ts >= cutoff:
                    records.append(r)
            except Exception:
                pass
    return records


def compute_kelly(records: list[dict]) -> dict:
    """
    Calcule la fraction Kelly demi-Kelly cappée.
    Returns dict avec kelly, win_rate, avg_win, avg_loss, profit_factor.
    """
    if len(records) < MIN_TRADES_FOR_KELLY:
        return {
            "kelly":         1.0,    # neutre = taille nominale inchangée
            "win_rate":      None,
            "avg_win":       None,
            "avg_loss":      None,
            "profit_factor": None,
            "note":          f"données insuffisantes ({len(records)}/{MIN_TRADES_FOR_KELLY})",
        }

    wins   = [r["pnl_pts"] for r in records if r["pnl_pts"] > 0]
    losses = [abs(r["pnl_pts"]) for r in records if r["pnl_pts"] < 0]

    if not wins or not losses:
        return {
            "kelly": 1.0, "win_rate": len(wins)/len(records),
            "avg_win": None, "avg_loss": None, "profit_factor": None,
            "note": "pas de gains ou pas de pertes — Kelly non calculable",
        }

    W       = len(wins) / len(records)
    avg_win = sum(wins)   / len(wins)
    avg_los = sum(losses) / len(losses)
    R       = avg_win / avg_los

    kelly_full = W - (1 - W) / R
    kelly_half = kelly_full / 2
    kelly_cap  = max(KELLY_MIN, min(KELLY_MAX, kelly_half))

    return {
        "kelly":         round(kelly_cap, 3),
        "win_rate":      round(W, 3),
        "avg_win":       round(avg_win, 1),
        "avg_loss":      round(avg_los, 1),
        "profit_factor": round(avg_win * len(wins) / (avg_los * max(len(losses), 1)), 2),
        "note":          (
            f"Kelly={kelly_full:.3f} → ½Kelly={kelly_half:.3f} "
            f"→ cappé={kelly_cap:.3f} (W={W:.0%} R={R:.2f})"
        ),
    }


def get_kill_zone_stats(records: list[dict]) -> dict[str, dict]:
    """Win rate et P&L moyen par kill zone."""
    stats: dict[str, dict] = {}
    for r in records:
        kz = r.get("kill_zone") or "HORS_ZONE"
        if kz not in stats:
            stats[kz] = {"trades": 0, "wins": 0, "pnl_total": 0.0}
        stats[kz]["trades"] += 1
        if r["pnl_pts"] > 0:
            stats[kz]["wins"] += 1
        stats[kz]["pnl_total"] += r["pnl_pts"]

    for kz, s in stats.items():
        n = s["trades"]
        s["win_rate"] = round(s["wins"] / n, 2) if n else 0
        s["avg_pnl"]  = round(s["pnl_total"] / n, 1) if n else 0
    return stats


def get_regime_stats(records: list[dict]) -> dict[str, dict]:
    """Performance par régime de marché."""
    stats: dict[str, dict] = {}
    for r in records:
        rg = r.get("regime") or "UNKNOWN"
        if rg not in stats:
            stats[rg] = {"trades": 0, "wins": 0, "pnl_total": 0.0}
        stats[rg]["trades"] += 1
        if r["pnl_pts"] > 0:
            stats[rg]["wins"] += 1
        stats[rg]["pnl_total"] += r["pnl_pts"]

    for rg, s in stats.items():
        n = s["trades"]
        s["win_rate"] = round(s["wins"] / n, 2) if n else 0
        s["avg_pnl"]  = round(s["pnl_total"] / n, 1) if n else 0
    return stats


def print_analytics_report(records: list[dict]) -> None:
    """Log un rapport de performance."""
    import logging
    log = logging.getLogger("xtb_pw")
    if not records:
        log.info("  [ANALYTICS] Aucun historique disponible")
        return

    kelly  = compute_kelly(records)
    kz_st  = get_kill_zone_stats(records)
    rg_st  = get_regime_stats(records)

    log.info(f"  [ANALYTICS] {len(records)} trades analysés")
    log.info(f"  [KELLY] {kelly['note']}")
    log.info("  [KILL ZONES]")
    for kz, s in sorted(kz_st.items(), key=lambda x: x[1]["pnl_total"], reverse=True):
        log.info(f"    {kz:20s}: {s['trades']:2d} trades | WR={s['win_rate']:.0%} | avg={s['avg_pnl']:+.1f}pts")
    log.info("  [RÉGIMES]")
    for rg, s in sorted(rg_st.items(), key=lambda x: x[1]["pnl_total"], reverse=True):
        log.info(f"    {rg:15s}: {s['trades']:2d} trades | WR={s['win_rate']:.0%} | avg={s['avg_pnl']:+.1f}pts")
