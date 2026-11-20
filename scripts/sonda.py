import urllib.request, json, re, base64
UA={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36','Accept':'*/*'}
def get(u):
    try:
        r=urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=90); b=r.read(); print('OK', r.status, len(b), u[:170]); return b
    except Exception as e: print('ERR', u[:170], str(e)[:150])
b=get('https://arquivos.b3.com.br/tabelas/config.js'); print(b[:1500] if b else '')
s=get('https://arquivos.b3.com.br/tabelas/static/js/main.d7e13d96.chunk.js').decode('utf-8','replace'); print(s[:9300])
q=lambda d: base64.b64encode(json.dumps(d).encode()).decode()
for u in ['https://sistemaswebb3-listados.b3.com.br/securitiesLendingProxy/SecuritiesLendingCall/GetOpenPositions/'+q({"language":"pt-br","pageNumber":1,"pageSize":20}),
          'https://sistemaswebb3-listados.b3.com.br/lendingProxy/LendingCall/GetOpenPosition/'+q({"language":"pt-br","pageNumber":1,"pageSize":20}),
          'https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/consultas/outros-servicos/emprestimo-de-ativos/']:
    b=get(u); print(b[:300] if b else '')
s=get('https://www.dadosdemercado.com.br/acoes/PETR4')
if s:
    s=s.decode('utf-8','replace'); 
    for k in ['alugu','empr','short','Aluguel']:
        i=s.find(k); print(k, s[max(0,i-200):i+400].replace('\n',' ') if i>=0 else None)
    print(sorted(set(re.findall(r'href="(/acoes/PETR4[^"#?]*)"', s))))
