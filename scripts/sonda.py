import urllib.request, json, re
UA={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36','Accept':'application/json, text/plain, */*','Content-Type':'application/json'}
def post(u, body=b'{}'):
    try:
        r=urllib.request.urlopen(urllib.request.Request(u, data=body, headers=UA, method='POST'), timeout=60); return r.read()
    except Exception as e: return ('ERR '+str(e)[:100]).encode()
def get(u):
    try:
        r=urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60); return r.read()
    except Exception as e: return ('ERR '+str(e)[:100]).encode()
d='2026-11-17'
for n in ['TradeInformationConsolidated','LendingOpenPosition','LendingOpenPositions','OpenLendingPosition','EmprestimoAtivosPosicaoAberto','LendingOpenPositionConsolidated','AssetLendingOpenPosition','SecuritiesLendingOpenPosition','LoanOpenPosition','BTBOpenPosition','LendingPosition']:
    b=post(f'https://arquivos.b3.com.br/bdi/table/{n}/{d}/{d}/1/20'); print('POST',n,b[:300])
b=get('https://arquivos.b3.com.br/bdi/'); print(b[:300])
h=b.decode('utf-8','replace')
for js in re.findall(r'src="([^"]+\.js)"', h)[:6]:
    u=js if js.startswith('http') else 'https://arquivos.b3.com.br'+(js if js.startswith('/') else '/bdi/'+js)
    s=get(u).decode('utf-8','replace'); print('JS',u,len(s))
    for m in sorted(set(re.findall(r'["\'`]([A-Z][A-Za-z]{6,60}(?:Position|Lending|Loan|Emprestimo)[A-Za-z]*)["\'`]', s))): print('   name', m)
    for m in sorted(set(re.findall(r'(?:table|download)/[A-Za-z/${}.+]{0,80}', s)))[:20]: print('   path', m)
