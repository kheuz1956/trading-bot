import os
from dotenv import load_dotenv

load_dotenv()

# ─── Compte XTB ──────────────────────────────────────────────────────────────
ACCOUNT_ID = os.getenv("XTB_ACCOUNT_ID", "")
PASSWORD   = os.getenv("XTB_PASSWORD", "")
DEMO       = True  # True = démo | False = RÉEL (ne changer qu'après tests complets)

# ─── Actif ───────────────────────────────────────────────────────────────────
SYMBOL  = "US100"
VOLUME  = 0.10  # lots par trade (0.1 = mini-lot)

# ─── Risk management ─────────────────────────────────────────────────────────
MAX_DAILY_LOSS_USD    = 200   # bot s'arrête si perte journalière > 200 USD
MAX_OPEN_TRADES       = 1     # 1 seul trade ouvert simultanément
BREAKEVEN_TRIGGER_PTS = 60    # active le breakeven après +60 pts de profit
TP1_CLOSE_RATIO       = 0.50  # ferme 50% de la position à TP1
MIN_RR                = 1.5   # R:R minimum pour ouvrir un trade

# ─── Position sizing dynamique (grade-based) ─────────────────────────────────
# Appliqué au volume de base (VOLUME) — multiplié par size_factor news ensuite
VOLUME_A_PLUS = 1.00   # Grade A+ : full size (confluences maximales)
VOLUME_A      = 0.75   # Grade A  : 75% (signal solide, quelques réserves)
VOLUME_B      = 0.50   # Grade B  : 50% (M15 fallback, risque plus élevé)

# ─── Trailing stop (actif après TP1) ─────────────────────────────────────────
TRAILING_ATR_MULT = 0.5   # trail SL = prix courant ± (ATR × 0.5)

# ─── Timing ──────────────────────────────────────────────────────────────────
SCAN_INTERVAL_SEC = 300   # analyse toutes les 5 minutes
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
ADX_MIN    = 25  # optimisé : 20 → 25 (PF +0.03, DD -20%)

# ─── RSI ─────────────────────────────────────────────────────────────────────
RSI_PERIOD = 14
RSI_MAX    = 70  # au-dessus → skip long
RSI_MIN    = 30  # en-dessous → skip short

# ─── MACD ────────────────────────────────────────────────────────────────────
MACD_FAST   = 12
MACD_SLOW   = 26
MACD_SIGNAL = 9
