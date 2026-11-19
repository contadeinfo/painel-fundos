"""Diagnóstico de fontes (temporário)."""
import io, zipfile, csv, json, sys, os, base64, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from atualiza import baixa
def tenta(nome, u, n=400):
    try:
        b = baixa(u)
        print('OK', nome, len(b) if b else None)
        return b
    except Exception as e:
        print('FALHA', nome, repr(e)[:200]); return None
b = tenta('cotahist2026', 'https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A2026.ZIP')
if b:
    z = zipfile.ZipFile(io.BytesIO(b)); n = z.namelist()[0]; L = z.open(n).read().decode('latin-1').splitlines(); print(n, len(L)); print(L[1][:250]); print([l for l in L if l[12:24].strip()=='PETR4'][-1][:250])
q = base64.b64encode(json.dumps({"language":"pt-br","pageNumber":1,"pageSize":120,"index":"IBOV","segment":"1"}).encode()).decode()
b = tenta('carteira IBOV', 'https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall/GetPortfolioDay/' + q)
if b: j = json.loads(b); print(list(j.keys())); print(j.get('results', [])[:2]); print(len(j.get('results', [])))
for nome, u in [('itr2025', 'https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_2025.zip'), ('dfp2024', 'https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_2024.zip'), ('fca2025', 'https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_2025.zip')]:
    b = tenta(nome, u)
    if not b: continue
    z = zipfile.ZipFile(io.BytesIO(b)); print(nome, [x for x in z.namelist()][:30])
    for x in z.namelist():
        if any(k in x for k in ('DRE_con', 'composicao_capital', 'valor_mobiliario')):
            rd = list(csv.DictReader(io.TextIOWrapper(z.open(x), encoding='latin-1'), delimiter=';'))
            print(x, len(rd), list(rd[0].keys()))
            pet = [r for r in rd if '33000167' in (r.get('CNPJ_CIA') or r.get('CNPJ_Companhia') or '')]
            for r in pet[:40]:
                if 'DRE' in x and not (r.get('CD_CONTA', '').startswith('3.1') ): continue
                print('  ', {k: r[k] for k in list(r)[:16]})
b = tenta('tesouro', 'https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv')
if b: L = b.decode('latin-1').splitlines(); print(len(L)); print(L[:3]); print([l for l in L if 'IPCA+ 20' in l][-3:])
