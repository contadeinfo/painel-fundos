import urllib.request, json
UA={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36','Accept':'*/*'}
def get(u):
    try:
        r=urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60); return r.read()
    except Exception as e: return ('ERR '+str(e)[:80]).encode()
names=['LendingOpenPosition','LendingOpenPositionFile','SecuritiesLendingOpenPosition','OpenPositionsLending','LendingPositions','Lending','LendingTrades','LendingOpenInterest','EmprestimoAtivosPosicaoAberto','BTBPositions','OpenPositions','PositionLimits','DerivativesOpenPosition','EquitiesOpenPosition','OptionsOpenPosition','EconomicIndicatorPrice','LoanOpenPosition','LoanPositions','LendingContracts','SecLendingOpenPosition']
for n in names:
    for d in ['2026-11-13','2025-06-10']:
        b=get(f'https://arquivos.b3.com.br/tabelas/table/{n}/{d}/1')
        print(n,d,b[:160].decode('utf-8','replace'))
for n in ['LendingOpenPositionFile','InstrumentsConsolidatedFile','TradeInformationConsolidatedFile']:
    b=get(f'https://arquivos.b3.com.br/api/download/requestname?fileName={n}&date=2026-11-13'); print(n, b[:300])
