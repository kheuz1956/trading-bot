import os
from dotenv import load_dotenv

load_dotenv()

# ─── Compte XTB ──────────────────────────────────────────────────────────────
ACCOUNT_ID = os.getenv("XTB_ACCOUNT_ID", "")
PASSWORD   = os.getenv("XTB_PASSWORD", "")
DEMO       = True  # True = démo | False = RÉEL (ne changer qu'après tests complets)

# ─── Actif ───────────────────────────────────────────────────────────────────
SYMBOL  = "US100"
VOLUME  = 0.10  # lots par trade — fallback si USE_DYNAMIC_SIZING=False

# ─── Dynamic Position Sizing (Van Tharp — 0.5% risk per trade) ───────────────
USE_DYNAMIC_SIZING       = True
RISK_PCT_PER_TRADE       = 0.005    # 0.5% de l'equity par trade
US100_PIP_VALUE_PER_LOT  = 20.0    # $20/pt par lot (XTB US100 CFD)
MIN_VOLUME               = 0.01    # lot minimum
MAX_VOLUME               = 1.00    # lot maximum (cap sécurité)

# ─── VIX Gate (Soros — réduire/bloquer sur panique marché) ───────────────────
VIX_HIGH_THRESHOLD    = 25.0  # VIX > 25 → volume réduit 50%
VIX_EXTREME_THRESHOLD = 35.0  # VIX > 35 → stop trading

# ─── Risk management ─────────────────────────────────────────────────────────
MAX_DAILY_LOSS_USD       = 600   # stop si perte journalière > 600 USD (0.2% equity ~300k)
DAILY_DRAWDOWN_MAX_PCT   = 0.02  # stop si equity intraday -2% (Raschke)
MAX_OPEN_TRADES          = 1     # 1 seul trade ouvert simultanément
BREAKEVEN_TRIGGER_PTS    = 60    # active le breakeven après +60 pts de profit
TP1_CLOSE_RATIO          = 0.50  # ferme 50% de la position à TP1
MIN_RR                   = 1.5   # R:R minimum pour ouvrir un trade

# ─── Position sizing dynamique (grade-based) ─────────────────────────────────
# Appliqué au volume de base (VOLUME) — multiplié par size_factor news ensuite
VOLUME_A_PLUS = 1.00   # Grade A+ : full size (confluences maximales)
VOLUME_A      = 0.75   # Grade A  : 75% (signal solide, quelques réserves)
VOLUME_B      = 0.50   # Grade B  : 50% (M15 fallback, risque plus élevé)

# ─── Trailing stop (actif après TP1) ─────────────────────────────────────────
TRAILING_ATR_MULT = 0.5   # trail SL = prix courant ± (ATR × 0.5)

# ─── Timing ──────────────────────────────────────────────────────────────────
SCAN_INTERVAL_SEC = 20    # analyse toutes les 20 secondes (mode scalp 40+ trades)
CANDLES_NEEDED    = 150   # bougies H1 à charger (≥ 52+26 pour Ichimoku)

# ─── Session filter (UTC) ────────────────────────────────────────────────────
# US100 liquide uniquement pendant la session NY (13:30–20:00 UTC, lun-ven)
SESSION_START_H = 13
SESSION_START_M = 30
SESSION_END_H   = 20
SESSION_END_M   = 0
FORCE_SESSION   = True   # True = ignorer le filtre session (trade 24/5)

# ─── Ichimoku ────────────────────────────────────────────────────────────────
TENKAN_PERIOD   = 9
KIJUN_PERIOD    = 26
SENKOU_B_PERIOD = 52
DISPLACEMENT    = 26

# ─── ATR (Stop Loss / Take Profit adaptatifs) ────────────────────────────────
# Paramètres optimisés par grid search sur 2 ans NQ=F H1 (PF 1.44, Sharpe 0.158)
ATR_PERIOD   = 14
ATR_SL_MULT  = 1.0   # SL = entry ± ATR × 1.0  (optimisé : ×1.5 → ×1.0)
ATR_TP1_MULT = 1.0   # TP1 = entry ± ATR × 1.0  (R:R 1:1)
ATR_TP2_MULT = 2.0   # TP2 = entry ± ATR × 2.0  (optimisé : ×3.0 → ×2.0, TP2 rate ×2)

# ─── ADX (filtre de tendance) ────────────────────────────────────────────────
ADX_PERIOD = 14
ADX_MIN    = 22  # abaissé 25→22 pour NY_OPEN avec tendance forte (core CPI 3.4%, NQ -1.4%)

# ─── RSI ─────────────────────────────────────────────────────────────────────
RSI_PERIOD = 14
RSI_MAX    = 70  # au-dessus → skip long
RSI_MIN    = 30  # en-dessous → skip short

# ─── MACD ────────────────────────────────────────────────────────────────────
MACD_FAST   = 12
MACD_SLOW   = 26
MACD_SIGNAL = 9

# ─── Mode scalping haute fréquence (M5) ──────────────────────────────────────
SCALP_MODE         = True   # Active le chemin M5 scalp dans generate_pro_signal
SCALP_ATR_SL_MULT  = 0.8   # SL scalp = entry ± ATR×0.8 (serré)
SCALP_ATR_TP1_MULT = 1.0   # TP1 scalp = entry ± ATR×1.0
SCALP_ATR_TP2_MULT = 1.8   # TP2 scalp = entry ± ATR×1.8  (R:R ~1:2.25)
SCALP_MIN_RR       = 1.2   # R:R minimum scalp (assoupli vs swing 1.5)
SCALP_ADX_MIN      = 18    # ADX minimum M5 (signal momentum suffisant)

# ─── Post-circuit-breaker recovery ───────────────────────────────────────────
MAX_DAILY_LOSSES           = 3    # stop trading après 3 pertes dans la journée
POST_BREAKER_VOLUME_MULT   = 0.5  # demi-taille jusqu'à POST_BREAKER_WINS_REQUIRED gains
POST_BREAKER_WINS_REQUIRED = 1    # gains consécutifs pour sortir du mode reprise

# ─── Limite d'opérations ──────────────────────────────────────────────────────
MAX_TRADES_PER_SESSION     = 2    # max trades par jour UTC (discipline stricte)
COOLDOWN_AFTER_TRADE_SEC   = 3600 # 60 min de pause après clôture d'une position
