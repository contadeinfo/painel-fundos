import urllib.request, json, base64, io, zipfile, csv, datetime as dt, re
UA={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36','Accept':'*/*'}
def get(u, data=None, h=None, n=600):
    try:
        r=urllib.request.urlopen(urllib.request.Request(u, data=data, headers={**UA, **(h or {})}), timeout=90)
        b=r.read(); print('OK', r.status, len(b), u[:150]); return b
    except Exception as e:
        print('ERR', u[:150], str(e)[:200]); return None
def show(b, n=700):
    if b: print('   ', b[:n].decode('utf-8','replace').replace('\n',' | '))
hoje=dt.date.today()
d=[(hoje-dt.timedelta(days=i)) for i in range(1,8)]; d=[x for x in d if x.weekday()<5]
# carteira IBOV campos
q=base64.b64encode(json.dumps({"language":"pt-br","pageNumber":1,"pageSize":3,"index":"IBOV","segment":"2"}).encode()).decode()
show(get('https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall/GetPortfolioDay/'+q),900)
# aluguel B3
for x in d[:2]:
    show(get(f'https://arquivos.b3.com.br/tabelas/table/LendingOpenPosition/{x}/1'),900)
    show(get(f'https://arquivos.b3.com.br/api/download/requestname?fileName=LendingOpenPositionFile&date={x}'),400)
    show(get(f'https://arquivos.b3.com.br/tabelas/table/LendingOpenPositionFile/{x}/1'),400)
show(get('https://arquivos.b3.com.br/apinegocios/tickercsv/2024-01-10'),200)
# fluxo estrangeiro candidatos
for u in ['https://sistemaswebb3-listados.b3.com.br/investorParticipationProxy/investorParticipationCall/GetInvestorParticipation/eyJsYW5ndWFnZSI6InB0LWJyIn0=',
          'https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/consultas/mercado-a-vista/participacao-dos-investidores/volume-total/',
          'https://www.dadosdemercado.com.br/fluxo',
          'https://www.dadosdemercado.com.br/api/fluxo-estrangeiro',
          'https://sistemaswebb3-listados.b3.com.br/marketDataProxy/MarketDataCall/GetForeignInvestors/eyJsYW5ndWFnZSI6InB0LWJyIn0=']:
    show(get(u),500)
# CVM: cadastro, VLMO, ITR principal, IPE
b=get('https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv'); show(b,500)
for y in (hoje.year,):
    b=get(f'https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/VLMO/DADOS/vlmo_cia_aberta_{y}.zip')
    if b:
        z=zipfile.ZipFile(io.BytesIO(b)); print(z.namelist())
        for n in z.namelist():
            with z.open(n) as f: print(n, f.read(1500).decode('latin-1').replace('\n',' | ')[:1500])
    b=get(f'https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_{y}.zip')
    if b:
        z=zipfile.ZipFile(io.BytesIO(b)); print([n for n in z.namelist()])
        n=[n for n in z.namelist() if re.fullmatch(r'itr_cia_aberta_\d{4}\.csv',n)][0]
        with z.open(n) as f: print(f.read(800).decode('latin-1'))
        for part in ('DVA_con','BPP_con'):
            n=[n for n in z.namelist() if part in n][0]
            with z.open(n) as f:
                rd=csv.DictReader(io.TextIOWrapper(f,encoding='latin-1'),delimiter=';')
                vis=set()
                for r in rd:
                    if r['CNPJ_CIA'] in ('60.872.504/0001-23','33.592.510/0001-54') and r['ORDEM_EXERC'].upper().startswith('Ú') and (r['CNPJ_CIA'],r['CD_CONTA']) not in vis and r['CD_CONTA'].count('.')<=3:
                        vis.add((r['CNPJ_CIA'],r['CD_CONTA']))
                        if part=='BPP_con' and not r['CD_CONTA'].startswith('2.0') : continue
                        if part=='BPP_con' and r['CD_CONTA'].count('.')>2: continue
                        if part=='DVA_con' and not r['CD_CONTA'].startswith('7.08'): continue
                        print(part, r['CNPJ_CIA'][:2], r['DT_REFER'], r['DT_INI_EXERC'] if 'DT_INI_EXERC' in r else '', r['CD_CONTA'], r['DS_CONTA'][:60], r['VL_CONTA'])
    b=get(f'https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{y}.zip')
    if b:
        z=zipfile.ZipFile(io.BytesIO(b)); n=z.namelist()[0]
        with z.open(n) as f:
            rd=csv.DictReader(io.TextIOWrapper(f,encoding='latin-1'),delimiter=';'); print(rd.fieldnames)
            cats={}
            for r in rd:
                k=(r.get('Categoria'),r.get('Tipo'))
                cats[k]=cats.get(k,0)+1
                if r.get('Categoria','').startswith('Calend') and cats[k]<3: print(r)
            print(sorted(cats.items(), key=lambda x:-x[1])[:40])
