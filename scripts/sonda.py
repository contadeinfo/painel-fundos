import urllib.request, json, re, datetime as dt
UA={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36','Accept':'*/*'}
def get(u):
    try:
        r=urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=90); b=r.read(); print('OK', r.status, len(b), u[:160]); return b
    except Exception as e: print('ERR', u[:160], str(e)[:150])
def show(b,n=600):
    if b: print('   ', b[:n].decode('utf-8','replace').replace('\n',' | '))
for d in ['2026-11-18','2026-11-17']:
    for t in ['TradeInformationConsolidated','InstrumentsConsolidated','LendingOpenPosition','LendingOpenPositionConsolidated','OpenPositionLending','LoanBalance','SecuritiesLendingOpenPosition','LendingOpenPositions','EmprestimoAtivos','BTBOpenPosition']:
        show(get(f'https://arquivos.b3.com.br/tabelas/table/{t}/{d}/1'),300)
    break
show(get('https://arquivos.b3.com.br/tabelas/'),800)
show(get('https://arquivos.b3.com.br/api/tables'),400)
b=get('https://www.dadosdemercado.com.br/fluxo')
if b:
    s=b.decode('utf-8','replace')
    i=s.find('<table'); print(s[i:i+3000])
    for m in re.finditer(r'(fetch|api|json|data-)[^"\']{0,80}', s[:200000]):
        pass
    print(re.findall(r'https?://[^"\' ]+\.(?:json|csv)', s)[:10])
    j=s.find('<script'); print([x[:300] for x in re.findall(r'<script[^>]*>(.{20,800}?)</script>', s, re.S)][:6])
b=get('https://www.dadosdemercado.com.br/aluguel-de-acoes'); 
if b:
    s=b.decode('utf-8','replace'); i=s.find('<table'); print(s[i:i+2000])
