import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from xtb_bot_playwright import get_ohlcv, generate_signal, calc_levels, is_trading_session
import config

df = get_ohlcv()
signal, snap = generate_signal(df)
levels = calc_levels(signal, snap) if signal != 'SKIP' else {}
skip = snap.get('skip_reason', '')

print(f"Signal   : {signal}" + (f" [{skip}]" if skip else ""))
print(f"Close    : {snap['close']:.2f}")
print(f"ATR      : {snap['atr']:.2f}")
print(f"ADX      : {snap['adx']:.1f}  (min={config.ADX_MIN})")
print(f"RSI      : {snap['rsi']:.1f}")
print(f"MACD_H   : {snap['macd_hist']:+.2f}")
print(f"Kumo     : {snap['kumo_bot']:.2f} - {snap['kumo_top']:.2f}")
print(f"In kumo  : {snap['in_kumo']}")
print(f"Tenkan   : {snap['tenkan']:.2f}  Kijun: {snap['kijun']:.2f}")
session_str = "NY OUVERTE" if is_trading_session() else "FERMEE (hors plage)"
print(f"Session  : {session_str}")
if levels:
    print(f"SL       : {levels['sl']}")
    print(f"TP1      : {levels['tp1']}")
    print(f"TP2      : {levels['tp2']}")
    print(f"R:R      : {levels['rr']}")
