"""
jesse_adapter.py — Bridge entre jesse-mcp et signal_runner.py

Utilise les outils jesse-mcp pour enrichir les signaux avec :
- Détection de régime de marché (regime_detector)
- Rapport de risque (risk_report / VaR)
- Corrélation inter-actifs
- Validation des niveaux de stop-loss via Monte Carlo

jesse-mcp fonctionne en mode mock si Jesse backend n'est pas disponible.
"""
import os
import logging
from typing import Optional
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

# Configurer l'URL Jesse depuis l'environnement
os.environ.setdefault("JESSE_URL", os.getenv("JESSE_URL", "http://localhost:9000"))
os.environ.setdefault("JESSE_PASSWORD", os.getenv("JESSE_PASSWORD", "trading"))

try:
    from jesse_mcp.server import (
        jesse_status,
        regime_detector,
        var_calculation,
        risk_report,
        monte_carlo,
    )
    JESSE_MCP_AVAILABLE = True
    log.info("jesse-mcp chargé avec succès")
except ImportError:
    JESSE_MCP_AVAILABLE = False
    log.warning("jesse-mcp non disponible — analyse de risque désactivée")


def get_market_regime(symbol: str = "US100", timeframe: str = "1h") -> dict:
    """
    Détecte le régime de marché actuel (trending / ranging / volatile).
    Retourne un dict avec : regime, confidence, trend_strength
    """
    if not JESSE_MCP_AVAILABLE:
        return {"regime": "unknown", "confidence": 0.0, "available": False}

    try:
        import asyncio
        result = asyncio.run(regime_detector(
            symbol=symbol,
            timeframe=timeframe,
            lookback_days=30
        ))
        return {
            "regime": result.get("regime", "unknown"),
            "confidence": result.get("confidence", 0.0),
            "trend_strength": result.get("trend_strength", 0.0),
            "volatility_percentile": result.get("volatility_percentile", 50.0),
            "available": True
        }
    except Exception as e:
        log.debug(f"regime_detector error: {e}")
        return {"regime": "unknown", "confidence": 0.0, "available": False}


def get_var_estimate(
    symbol: str = "US100",
    position_size: float = 0.05,
    entry_price: float = 30000.0,
    confidence_level: float = 0.95
) -> dict:
    """
    Calcule la Value at Risk (VaR) pour la position courante.
    Retourne la perte maximale estimée au niveau de confiance donné.
    """
    if not JESSE_MCP_AVAILABLE:
        return {"var_usd": None, "available": False}

    try:
        import asyncio
        result = asyncio.run(var_calculation(
            symbol=symbol,
            position_size=position_size,
            entry_price=entry_price,
            confidence_level=confidence_level,
            lookback_days=30
        ))
        return {
            "var_usd": result.get("var_usd"),
            "var_pct": result.get("var_pct"),
            "confidence_level": confidence_level,
            "available": True
        }
    except Exception as e:
        log.debug(f"var_calculation error: {e}")
        return {"var_usd": None, "available": False}


def validate_sl_with_monte_carlo(
    symbol: str = "US100",
    entry_price: float = 30000.0,
    sl_price: float = 29900.0,
    tp_price: float = 30200.0,
    simulations: int = 1000
) -> dict:
    """
    Valide le SL/TP via simulation Monte Carlo.
    Retourne la probabilité d'atteindre TP avant SL.
    """
    if not JESSE_MCP_AVAILABLE:
        return {"tp_probability": None, "available": False}

    try:
        import asyncio
        result = asyncio.run(monte_carlo(
            symbol=symbol,
            entry_price=entry_price,
            stop_loss=sl_price,
            take_profit=tp_price,
            simulations=simulations
        ))
        return {
            "tp_probability": result.get("win_probability"),
            "expected_return": result.get("expected_return"),
            "max_drawdown": result.get("max_drawdown"),
            "available": True
        }
    except Exception as e:
        log.debug(f"monte_carlo error: {e}")
        return {"tp_probability": None, "available": False}


def jesse_health_check() -> bool:
    """Vérifie si jesse-mcp est disponible."""
    if not JESSE_MCP_AVAILABLE:
        return False
    try:
        status = jesse_status()
        return status.get("connected", False) or JESSE_MCP_AVAILABLE
    except Exception:
        return False


if __name__ == "__main__":
    # Test rapide
    logging.basicConfig(level=logging.INFO)
    print("jesse-mcp disponible:", JESSE_MCP_AVAILABLE)
    print("Régime marché:", get_market_regime("US100", "1h"))
    print("VaR:", get_var_estimate("US100", 0.05, 30500.0))
