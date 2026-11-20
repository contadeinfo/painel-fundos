#!/usr/bin/env python3
"""Bolsa por dentro: fluxo por tipo de investidor, aluguel de ações e negociações de insiders.

- Fluxo: saldo diário de compras menos vendas na B3 por tipo de investidor (estrangeiro, institucional,
  pessoa física, instituição financeira, outros), dados da B3 compilados por dadosdemercado.com.br.
- Aluguel: posições em aberto de empréstimo de ações (Boletim Diário da B3, tabela BTBLendingOpenPosition).
- Insiders: valores mobiliários negociados por controladores, diretores e conselheiros (CVM, formulário
  do art. 11 da Resolução 44, consolidado mensal).
Saída: data/bolsa.json (+ histórico em data/bolsa/).
"""
import csv, html, io, json, os, re, sys, zipfile, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from atualiza import baixa, so_digitos, RAIZ  # noqa: E402

PASTA = os.path.join(RAIZ, 'data', 'bolsa')
SAIDA = os.path.join(RAIZ, 'data', 'bolsa.json')
VLMO = 'https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/VLMO/DADOS/vlmo_cia_aberta_{}.zip'
csv.field_size_limit(10 ** 8)


def jload(p, d):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return d


def jsave(p, o):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(o, open(p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))


def br_num(t):
    t = html.unescape(re.sub(r'<[^>]+>', '', t)).strip().replace('\xa0', ' ')
    m = re.match(r'(-?[\d.]+(?:,\d+)?)\s*(mi|bi|mil)?', t)
    if not m:
        return None
    v = float(m.group(1).replace('.', '').replace(',', '.'))
    return v * {'bi': 1000, 'mil': 0.001}.get(m.group(2), 1)   # em R$ milhões


# ---------------- fluxo por tipo de investidor ----------------
def fluxo():
    H = jload(os.path.join(PASTA, 'fluxo.json'), {})   # {AAAA-MM-DD: [estrangeiro, institucional, pf, if, outros]} em R$ mi
    s = baixa('https://www.dadosdemercado.com.br/fluxo').decode('utf-8', 'replace')
    i = s.find('id="flow"')
    tb = s[i:s.find('</table>', i)]
    n = 0
    for tr in re.findall(r'<tr>(.*?)</tr>', tb, re.S):
        tds = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)
        if len(tds) < 6:
            continue
        d = re.sub(r'<[^>]+>', '', tds[0]).strip()
        try:
            iso = dt.datetime.strptime(d, '%d/%m/%Y').date().isoformat()
        except ValueError:
            continue
        H[iso] = [br_num(x) for x in tds[1:6]]
        n += 1
    print('fluxo:', n, 'dias lidos;', len(H), 'no histórico')
    jsave(os.path.join(PASTA, 'fluxo.json'), H)
    return H


# ---------------- aluguel (BDI da B3) ----------------
def aluguel():
    from playwright.sync_api import sync_playwright
    linhas, colunas, data_ref = [], None, None
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto('https://arquivos.b3.com.br/bdi/', timeout=90000)
        pg.wait_for_timeout(4000)
        hoje = dt.date.today()
        for k in range(1, 8):
            d = (hoje - dt.timedelta(days=k))
            if d.weekday() >= 5:
                continue
            ds = d.isoformat()
            pag = 1
            while True:
                r = pg.request.post(f'https://arquivos.b3.com.br/bdi/table/BTBLendingOpenPosition/{ds}/{ds}/{pag}/1000',
                                    data='{}', headers={'content-type': 'application/json'})
                if not r.ok:
                    print('aluguel', ds, r.status); break
                j = r.json()
                t = j.get('table') or {}
                cols = t.get('columns') or j.get('columns')
                vals = t.get('values') or j.get('values') or []
                if pag == 1:
                    print('aluguel', ds, 'chaves', list(j)[:8], 'colunas', [c.get('name') for c in (cols or [])][:12], 'linhas', len(vals))
                if cols and vals:
                    colunas = [c.get('name') for c in cols]
                    linhas += vals
                pc = t.get('pageCount') or j.get('pageCount') or 1
                if pag >= pc or not vals:
                    break
                pag += 1
            if linhas:
                data_ref = ds
                break
        b.close()
    if not linhas:
        return None
    idx = {n: i for i, n in enumerate(colunas)}
    def col(*nomes):
        for n in colunas:
            if any(x.lower() in n.lower() for x in nomes):
                return idx[n]
    i_tk, i_qt, i_rs, i_pm = col('TckrSymb', 'Ticker'), col('StockBalance', 'BalQty'), idx.get('Balance', col('BalVal')), col('AvgPric', 'AvrgPric')
    print('colunas', colunas, '->', i_tk, i_qt, i_rs, i_pm)
    por = {}
    for v in linhas:
        tk = str(v[i_tk]).strip().upper()
        if not re.fullmatch(r'[A-Z0-9]{4}\d{1,2}', tk):
            continue
        x = por.setdefault(tk, [0.0, 0.0])
        x[0] += float(v[i_qt] or 0)
        x[1] += float(v[i_rs] or 0) if i_rs is not None else 0
    print('aluguel:', data_ref, len(por), 'códigos')
    return data_ref, por


def resumo_aluguel(res, V):
    H = jload(os.path.join(PASTA, 'aluguel.json'), {})   # {data: {ticker: [qtd, R$]}}
    if res:
        d, por = res
        H[d] = {tk: [round(q), round(v)] for tk, (q, v) in por.items() if v >= 1e6}
    H = {k: H[k] for k in sorted(H)[-70:]}
    jsave(os.path.join(PASTA, 'aluguel.json'), H)
    if not H:
        return None
    d = max(H)
    atual = H[d]
    k_ant = min(H, key=lambda k: abs((dt.date.fromisoformat(k) - (dt.date.fromisoformat(d) - dt.timedelta(days=30))).days))
    ant = H[k_ant] if k_ant != d else {}
    # % das ações alugadas: ações de cada classe aproximadas pelo total da empresa (CVM)
    acoes = jload(os.path.join(RAIZ, 'data', 'valuation', 'acoes.json'), {})
    emp = {t: e for e in (V or {}).get('empresas', []) for t in e['tks']}
    raiz = {}
    for e in (V or {}).get('empresas', []):
        for t in e['tks']:
            raiz[t[:4]] = e
    out = []
    for tk, (q, v) in atual.items():
        e = emp.get(tk) or raiz.get(tk[:4])
        if not e:
            continue
        sh = acoes.get(e['cnpj'], {})
        pct = None
        if sh:
            on, pn = sh[max(sh)]
            if on < 5e7 and on + pn < 5e7:
                on, pn = on * 1000, pn * 1000
            base = on if tk[4:] == '3' else pn if tk[4:] in ('4', '5', '6') else None
            if base:
                pct = q / base * 100
        q0 = (ant.get(tk) or [None])[0]
        out.append({'tk': tk, 'nome': e['nome'], 'setor': e.get('setor'), 'qtd': q, 'rs': v, 'pct': round(pct, 2) if pct is not None else None,
                    'var_30d': round((q / q0 - 1) * 100, 1) if q0 else None})
    out.sort(key=lambda r: -(r['pct'] or 0))
    tot = sum(v for _, v in atual.values())
    serie = [{'d': k, 'rs_bi': round(sum(v for _, v in H[k].values()) / 1e9, 2)} for k in sorted(H)]
    return {'data': d, 'comparado_com': k_ant if k_ant != d else None,
            'total_bi': round(tot / 1e9, 1), 'acoes': out, 'serie': serie}


# ---------------- insiders (CVM) ----------------
CARGO = [(r'controlador', 'Controlador'), (r'diretor', 'Diretoria'), (r'conselho de administra', 'Conselho'), (r'conselho fiscal', 'Conselho fiscal'),
         (r'estatut|comit', 'Outros órgãos')]


def insiders(V):
    hoje = dt.date.today()
    linhas = []
    tipos = {}
    for a in sorted({hoje.year, (hoje - dt.timedelta(days=120)).year}):
        zb = baixa(VLMO.format(a))
        if not zb:
            continue
        z = zipfile.ZipFile(io.BytesIO(zb))
        n = next(x for x in z.namelist() if '_con_' in x)
        with z.open(n) as f:
            for r in csv.DictReader(io.TextIOWrapper(f, encoding='latin-1', newline=''), delimiter=';'):
                mov = (r.get('Tipo_Movimentacao') or '').strip()
                tipos[mov] = tipos.get(mov, 0) + 1
                if (r.get('Tipo_Empresa') or '').strip() != 'Companhia' or not (r.get('Tipo_Ativo') or '').lower().startswith('aç'):
                    continue
                m = mov.lower()
                lado = 'compra' if 'compra' in m else 'venda' if 'venda' in m else None
                if not lado:
                    continue
                try:
                    vol = float((r.get('Volume') or '0').replace(',', '.'))
                except ValueError:
                    vol = 0
                if vol <= 0:
                    try:
                        vol = float(r.get('Quantidade') or 0) * float((r.get('Preco_Unitario') or '0').replace(',', '.'))
                    except ValueError:
                        vol = 0
                cg = (r.get('Tipo_Cargo') or '').lower()
                cargo = next((nm for rx, nm in CARGO if re.search(rx, cg)), 'Outros')
                linhas.append((so_digitos(r['CNPJ_Companhia']), r['Nome_Companhia'].strip(), r['Data_Referencia'][:7], cargo, lado, vol,
                               (r.get('Caracteristica_Valor_Mobiliario') or '').strip()))
    print('VLMO tipos de movimentação:', sorted(tipos.items(), key=lambda x: -x[1])[:15])
    if not linhas:
        return None
    meses = sorted({l[2] for l in linhas})[-4:]
    tks = {}
    for e in (V or {}).get('empresas', []):
        tks[e['cnpj']] = e['tks']
    ag = {}
    for c, nome, m, cargo, lado, vol, classe in linhas:
        if m not in meses:
            continue
        k = (c, m)
        x = ag.setdefault(k, {'cnpj': c, 'nome': nome, 'mes': m, 'tks': tks.get(c, []), 'ibov': c in tks, 'compra': 0.0, 'venda': 0.0, 'cargos': {}})
        x[lado] += vol
        cc = x['cargos'].setdefault(cargo, [0.0, 0.0])
        cc[0 if lado == 'compra' else 1] += vol
    lista = []
    for x in ag.values():
        x['liquido'] = x['compra'] - x['venda']
        if max(x['compra'], x['venda']) < 1e6:
            continue
        x['cargos'] = {k: [round(a), round(b)] for k, (a, b) in x['cargos'].items()}
        x['compra'], x['venda'], x['liquido'] = round(x['compra']), round(x['venda']), round(x['liquido'])
        lista.append(x)
    lista.sort(key=lambda x: (x['mes'], abs(x['liquido'])), reverse=True)
    print('insiders:', len(lista), 'empresa-mês com mais de R$ 1 mi; meses', meses)
    return {'meses': meses, 'movimentos': lista[:300]}


def main():
    V = jload(os.path.join(RAIZ, 'data', 'valuation.json'), {})
    out = jload(SAIDA, {})
    out['gerado_em'] = dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ')
    try:
        H = fluxo()
        dias = sorted(H)[-260:]
        out['fluxo'] = {'colunas': ['Estrangeiro', 'Institucional', 'Pessoa física', 'Inst. financeira', 'Outros'], 'dias': [[d] + H[d] for d in dias]}
    except Exception as e:
        print('aviso fluxo', e)
    try:
        al = resumo_aluguel(aluguel(), V)
        if al:
            out['aluguel'] = al
    except Exception as e:
        print('aviso aluguel', repr(e))
    hoje = dt.date.today()
    if hoje.weekday() == 0 or 'insiders' not in out or os.environ.get('FORCA'):
        try:
            ins = insiders(V)
            if ins:
                out['insiders'] = ins
        except Exception as e:
            print('aviso insiders', e)
    jsave(SAIDA, out)
    print('OK bolsa.json', list(out))


if __name__ == '__main__':
    sys.exit(main())
