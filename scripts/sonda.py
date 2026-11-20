import urllib.request, json, re
UA={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36','Accept':'*/*'}
def get(u):
    try:
        r=urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=90); b=r.read(); print('OK', r.status, len(b), u[:160]); return b
    except Exception as e: print('ERR', u[:160], str(e)[:150])
h=get('https://arquivos.b3.com.br/tabelas/').decode()
for js in re.findall(r'src="(/tabelas/static/js/[^"]+)"', h):
    s=get('https://arquivos.b3.com.br'+js).decode('utf-8','replace')
    for m in set(re.findall(r'["\'`](/?(?:api|tabelas)/[A-Za-z0-9_/\-{}$.]+)', s)): print('  url', m)
    for m in set(re.findall(r'https://[a-z0-9.\-]+b3[^"\'` ]+', s)): print('  abs', m[:120])
for u in ['https://arquivos.b3.com.br/api/download/requestname?fileName=InstrumentsConsolidatedFile&date=2026-11-18',
          'https://arquivos.b3.com.br/api/channels/34dcaaeb-0306-4f45-a83e-4f66a23b42fa/subchannels/','https://arquivos.b3.com.br/tabelas/api/table']:
    b=get(u); print(b[:500] if b else '')
s=get('https://www.dadosdemercado.com.br/').decode('utf-8','replace')
print(sorted(set(re.findall(r'href="(/[^"#?]+)"', s)))[:200])
