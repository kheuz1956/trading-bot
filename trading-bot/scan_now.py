import sys, traceback, io

BOT_DIR = r'C:\Users\CHEIKH MBACKE DIENG\Documents\CLAUDE\CODE\.claude\worktrees\nervous-margulis-1c105b\trading-bot'
OUT_FILE = BOT_DIR + r'\scan_result.txt'

sys.path.insert(0, BOT_DIR)

buf = io.StringIO()

def log(msg=''):
    buf.write(str(msg) + '\n')
    print(msg, flush=True)

log('=== SCAN MTF LONDON OPEN ===')
try:
    log('Import strategy_pro...')
    from strategy_pro import load_mtf, generate_pro_signal, print_pro_signal
    log('OK - chargement MTF...')
    mtf = load_mtf()
    log('OK - generation signal...')
    sig = generate_pro_signal(mtf)

    import io as _io
    old_stdout = sys.stdout
    sys.stdout = cap = _io.StringIO()
    print_pro_signal(sig)
    sys.stdout = old_stdout
    signal_txt = cap.getvalue()
    log(signal_txt)

    log('---')
    log(f'DIRECTION : {sig.direction}')
    log(f'GRADE     : {sig.grade}')
    log(f'ENTRY     : {sig.entry}')
    log(f'SL        : {sig.sl}')
    log(f'TP        : {sig.tp2}')
    log(f'RR        : {sig.rr}')
    log(f'ATR       : {sig.atr:.1f}')
except Exception as e:
    log(f'ERREUR: {e}')
    log(traceback.format_exc())

with open(OUT_FILE, 'w', encoding='utf-8') as f:
    f.write(buf.getvalue())

print('Fichier ecrit:', OUT_FILE, flush=True)
