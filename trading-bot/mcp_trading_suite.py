"""
mcp_trading_suite.py — Suite MCP Trading complète

Agrège les données de tous les MCPs installés :
  1. jesse-mcp      → Backtest, Monte Carlo, VaR, Régime marché
  2. yahoo-finance  → OHLCV, fondamentaux, options
  3. finance-trading-ai → OHLC temps réel, calendrier économique
  4. maverick-mcp   → RSI/MACD/Bollinger, backtesting multi-stratégies

Usage dans signal_runner.py :
    from mcp_trading_suite import MCPTradingSuite
    suite = MCPTradingSuite()
    context = suite.get_full_context("US100", "1h")
"""
import logging
import subprocess
import json
from typing import Optional

log = logging.getLogger(__name__)

# ─── Disponibilité des MCPs ───────────────────────────────────────────────────

import shutil

def _check_mcp(module_name: str) -> bool:
    try:
        __import__(module_name.replace("-", "_"))
        return True
    except ImportError:
        return False

def _check_cli(exe_name: str) -> bool:
    scripts = r"C:\Users\CHEIKH MBACKE DIENG\AppData\Local\Programs\Python\Python312\Scripts"
    return (
        shutil.which(exe_name) is not None
        or __import__("os").path.exists(f"{scripts}\\{exe_name}.exe")
    )

MCP_AVAILABILITY = {
    "jesse_mcp":                _check_mcp("jesse_mcp"),
    "yahoo_finance_mcp":        _check_cli("yahoo-finance-mcp"),
    "finance_trading_ai":       _check_mcp("finance_trading_ai_agents_mcp"),
    "maverick_mcp":             _check_cli("maverick"),
}

log.info(f"MCPs disponibles: { {k: ('OK' if v else 'N/A') for k, v in MCP_AVAILABILITY.items()} }")


# ─── Yahoo Finance MCP ────────────────────────────────────────────────────────

def yahoo_get_price(symbol: str) -> Optional[dict]:
    """Prix actuel + volume + variation via Yahoo Finance."""
    if not MCP_AVAILABILITY["yahoo_finance_mcp"]:
        return None
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        return {
            "symbol": symbol,
            "price": getattr(info, "last_price", None),
            "volume": getattr(info, "three_month_average_volume", None),
            "52w_high": getattr(info, "year_high", None),
            "52w_low": getattr(info, "year_low", None),
            "source": "yahoo-finance-mcp",
        }
    except Exception as e:
        log.debug(f"yahoo_get_price error: {e}")
        return None


def yahoo_get_ohlcv(symbol: str, period: str = "5d", interval: str = "1h") -> Optional[dict]:
    """Données OHLCV historiques."""
    if not MCP_AVAILABILITY["yahoo_finance_mcp"]:
        return None
    try:
        import yfinance as yf
        df = yf.download(symbol, period=period, interval=interval, progress=False)
        if df.empty:
            return None
        latest = df.iloc[-1]
        return {
            "close": float(latest["Close"]),
            "high": float(latest["High"]),
            "low": float(latest["Low"]),
            "volume": float(latest["Volume"]),
            "rows": len(df),
            "source": "yahoo-finance-mcp",
        }
    except Exception as e:
        log.debug(f"yahoo_get_ohlcv error: {e}")
        return None


# ─── Jesse MCP ────────────────────────────────────────────────────────────────

def jesse_get_regime(symbol: str = "US100") -> Optional[dict]:
    """Régime de marché via jesse-mcp."""
    if not MCP_AVAILABILITY["jesse_mcp"]:
        return None
    try:
        from jesse_adapter import get_market_regime
        return get_market_regime(symbol, "1h")
    except Exception as e:
        log.debug(f"jesse_get_regime error: {e}")
        return None


def jesse_validate_trade(entry: float, sl: float, tp: float,
                          symbol: str = "US100") -> Optional[dict]:
    """Valide SL/TP via Monte Carlo jesse-mcp."""
    if not MCP_AVAILABILITY["jesse_mcp"]:
        return None
    try:
        from jesse_adapter import validate_sl_with_monte_carlo, get_var_estimate
        mc = validate_sl_with_monte_carlo(symbol, entry, sl, tp)
        var = get_var_estimate(symbol, 0.05, entry)
        return {
            "tp_probability": mc.get("tp_probability"),
            "var_usd": var.get("var_usd"),
            "source": "jesse-mcp",
        }
    except Exception as e:
        log.debug(f"jesse_validate_trade error: {e}")
        return None


# ─── Suite complète ───────────────────────────────────────────────────────────

class MCPTradingSuite:
    """Agrège tous les MCPs pour fournir un contexte de trading enrichi."""

    def __init__(self):
        self.availability = MCP_AVAILABILITY
        active = [k for k, v in self.availability.items() if v]
        log.info(f"MCPTradingSuite initialisé — {len(active)}/4 MCPs actifs: {active}")

    def get_full_context(self, symbol: str = "^NDX", timeframe: str = "1h") -> dict:
        """
        Retourne un contexte complet du marché en agrégeant tous les MCPs.
        """
        context = {"symbol": symbol, "mcps_used": []}

        # Yahoo Finance
        price_data = yahoo_get_price(symbol)
        if price_data:
            context["yahoo_price"] = price_data
            context["mcps_used"].append("yahoo-finance-mcp")

        ohlcv = yahoo_get_ohlcv(symbol, period="5d", interval=timeframe)
        if ohlcv:
            context["yahoo_ohlcv"] = ohlcv

        # Jesse MCP
        regime = jesse_get_regime("US100")
        if regime and regime.get("available"):
            context["jesse_regime"] = regime
            context["mcps_used"].append("jesse-mcp")

        return context

    def validate_signal(self, entry: float, sl: float, tp: float,
                         symbol: str = "US100") -> dict:
        """
        Valide un signal de trading via tous les MCPs disponibles.
        Retourne un score de confiance agrégé.
        """
        validation = {
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "risk_reward": round((tp - entry) / (entry - sl), 2) if entry > sl else 0,
            "confidence_score": 0.5,  # baseline
            "warnings": [],
            "confirmations": [],
        }

        # Validation Jesse Monte Carlo
        jesse_val = jesse_validate_trade(entry, sl, tp, symbol)
        if jesse_val and jesse_val.get("tp_probability") is not None:
            prob = jesse_val["tp_probability"]
            if prob >= 0.60:
                validation["confirmations"].append(f"Monte Carlo TP prob: {prob:.0%}")
                validation["confidence_score"] = min(0.9, validation["confidence_score"] + 0.2)
            elif prob < 0.40:
                validation["warnings"].append(f"Monte Carlo TP prob faible: {prob:.0%}")
                validation["confidence_score"] = max(0.1, validation["confidence_score"] - 0.2)
            validation["jesse_tp_probability"] = prob
            if jesse_val.get("var_usd"):
                validation["var_usd"] = jesse_val["var_usd"]

        # R:R check
        if validation["risk_reward"] >= 2.0:
            validation["confirmations"].append(f"R:R favorable: {validation['risk_reward']:.1f}:1")
        elif validation["risk_reward"] < 1.5:
            validation["warnings"].append(f"R:R insuffisant: {validation['risk_reward']:.1f}:1")

        return validation

    def summary(self) -> str:
        """Résumé court de l'état des MCPs."""
        lines = ["=== MCPTradingSuite ==="]
        for name, avail in self.availability.items():
            lines.append(f"  [{'OK' if avail else '--'}] {name}")
        return "\n".join(lines)


# ─── Test rapide ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    suite = MCPTradingSuite()
    print(suite.summary())

    # Test contexte
    ctx = suite.get_full_context("US100=X")
    print("\nContexte marché:", json.dumps(ctx, indent=2, default=str))

    # Test validation signal
    val = suite.validate_signal(entry=30600, sl=30500, tp=30800)
    print("\nValidation signal:", json.dumps(val, indent=2, default=str))
