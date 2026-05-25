import sys, traceback
sys.path.insert(0, '.')

results = []
modules = [
    ('playwright.async_api', 'async_playwright'),
    ('market_intelligence', 'MarketIntelligenceEngine'),
    ('macro_intelligence', 'MacroIntelligenceEngine'),
    ('economic_calendar', 'EconomicCalendarEngine'),
    ('news_surveillance', 'NewsSurveillanceEngine'),
    ('strategy_pro', 'generate_pro_signal'),
]

for mod, attr in modules:
    try:
        m = __import__(mod, fromlist=[attr])
        getattr(m, attr)
        results.append(f'OK  {mod}.{attr}')
    except Exception as e:
        results.append(f'ERR {mod}.{attr}: {e}')

for r in results:
    print(r)
