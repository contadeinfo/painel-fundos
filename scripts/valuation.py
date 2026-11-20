#!/usr/bin/env python3
"""Valuation da bolsa: P/L agregado do Ibovespa (composição atual), sem Petrobras e sem Petrobras e Vale.

Dados públicos:
  - CVM: ITR e DFP (lucro líquido atribuído aos controladores, trimestre a trimestre; quantidade de ações)
         e FCA (códigos de negociação de cada companhia)
  - B3:  COTAHIST (fechamento oficial de cada ação) e carteira teórica do Ibovespa
  - Tesouro Direto: taxa do Tesouro IPCA+ (NTN-B Principal) de ~10 anos, para o prêmio de risco

P/L agregado = soma do valor de mercado ÷ soma do lucro dos últimos 12 meses (lucros negativos entram).
Saída: data/valuation.json ; cache em data/valuation/ (preços mensais e lucros já processados).
"""
import base64, csv, io, json, math, os, re, sys, zipfile, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from atualiza import baixa, so_digitos, RAIZ  # noqa: E402

ANO0 = 2011
PASTA = os.path.join(RAIZ, 'data', 'valuation')
SAIDA = os.path.join(RAIZ, 'data', 'valuation.json')
PETRO, VALE = '33000167000101', '33592510000154'
ITR = 'https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_{}.zip'
DFP = 'https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{}.zip'
FCA = 'https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_{}.zip'
COTA = 'https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{}.ZIP'
TESOURO = ('https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/resource/'
           '796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv')
csv.field_size_limit(10 ** 8)


def ler(z, padrao):
    for n in z.namelist():
        if re.search(padrao, n, re.I):
            with z.open(n) as f:
                yield from csv.DictReader(io.TextIOWrapper(f, encoding='latin-1', newline=''), delimiter=';')


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def json_load(nome, padrao):
    try:
        return json.load(open(os.path.join(PASTA, nome), encoding='utf-8'))
    except Exception:
        return padrao


def json_save(nome, obj):
    os.makedirs(PASTA, exist_ok=True)
    json.dump(obj, open(os.path.join(PASTA, nome), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))


# ---------------- carteira do Ibovespa ----------------
def carteira_ibov():
    q = base64.b64encode(json.dumps({"language": "pt-br", "pageNumber": 1, "pageSize": 150, "index": "IBOV", "segment": "1"}).encode()).decode()
    j = json.loads(baixa('https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall/GetPortfolioDay/' + q))
    out = {}
    for r in j.get('results', []):
        tk = (r.get('cod') or r.get('code') or '').strip().upper()
        p = num(str(r.get('part') or '0').replace(',', '.'))
        if tk:
            out[tk] = p
    print('carteira IBOV:', len(out), 'ações; data', (j.get('header') or {}).get('date'))
    return out


# ---------------- tickers por CNPJ (FCA) ----------------
def tickers():
    tk2c, nome = {}, {}
    for a in range(max(ANO0, dt.date.today().year - 4), dt.date.today().year + 1):
        try:
            zb = baixa(FCA.format(a))
        except Exception as e:
            print('aviso FCA', a, e); zb = None
        if not zb:
            continue
        z = zipfile.ZipFile(io.BytesIO(zb))
        for r in ler(z, r'valor_mobiliario'):
            tk = (r.get('Codigo_Negociacao') or '').strip().upper()
            if re.fullmatch(r'[A-Z0-9]{4}\d{1,2}', tk or ''):
                c = so_digitos(r.get('CNPJ_Companhia'))
                tk2c[tk] = c
                nome[c] = (r.get('Nome_Empresarial') or '').strip()
    print('FCA:', len(tk2c), 'códigos de negociação')
    return tk2c, nome


# ---------------- preços mensais (COTAHIST) ----------------
TK_OK = re.compile(r'^[A-Z]{4}(3|4|5|6|7|8|11)$')


def precos(anos_novos):
    """Fechamento do último pregão de cada mês, por código (lote padrão). Um arquivo por ano em data/valuation/;
    anos fechados não são baixados de novo (o arquivo da B3 tem ~100 MB por ano)."""
    hoje = dt.date.today()
    P = {}
    for a in range(ANO0, hoje.year + 1):
        nome = f'precos_{a}.json'
        cache = json_load(nome, None)
        if cache is None or a in anos_novos:
            try:
                zb = baixa(COTA.format(a))
            except Exception as e:
                print('aviso COTAHIST', a, e); zb = None
            if zb:
                z = zipfile.ZipFile(io.BytesIO(zb))
                mes = {}
                with z.open(z.namelist()[0]) as f:
                    for raw in f:
                        if raw[:2] != b'01' or raw[10:12] != b'02' or raw[24:27] != b'010':
                            continue
                        ln = raw.decode('latin-1')
                        tk = ln[12:24].strip()
                        if not TK_OK.match(tk):
                            continue
                        d = ln[2:10]
                        pu = int(ln[108:121]) / 100 / (int(ln[210:217] or 1) or 1)
                        vol = int(ln[170:188]) / 100
                        k = f'{d[:4]}-{d[4:6]}'
                        x = mes.setdefault(tk, {}).get(k)
                        if x is None:
                            mes[tk][k] = [round(pu, 4), vol, d]
                        else:
                            x[1] += vol
                            if d >= x[2]:
                                x[0], x[2] = round(pu, 4), d
                cache = {tk: {k: [v[0], round(v[1]), v[2]] for k, v in ms.items()} for tk, ms in mes.items()}
                json_save(nome, cache)
                print('COTAHIST', a, len(cache), 'códigos')
                del zb, z, mes
        for tk, ms in (cache or {}).items():
            P.setdefault(tk, {}).update(ms)
    return P


# ---------------- lucros e ações (ITR + DFP) ----------------
CONTROLADORA = re.compile(r'atribu[ií]d[oa]s? (a|aos) s[oó]cios da (empresa )?controladora', re.I)
LUCRO = re.compile(r'lucro.*(per[ií]odo|exerc[ií]cio)|resultado l[ií]quido', re.I)


def lucro_de(linhas):
    """Escolhe o lucro líquido (preferência: atribuído aos controladores; senão o total do período)."""
    ctrl = [r for r in linhas if CONTROLADORA.search(r['DS_CONTA']) and r['CD_CONTA'].count('.') == 2]
    if ctrl:
        return ctrl[0]
    cod = lambda r: tuple(int(x) for x in re.findall(r'\d+', r['CD_CONTA']))
    tot = sorted((r for r in linhas if LUCRO.search(r['DS_CONTA']) and r['CD_CONTA'].count('.') == 1), key=cod)
    return tot[-1] if tot else None


def balancos(anos_novos):
    L = json_load('lucros.json', {})     # {cnpj: {AAAA-MM-DD: {'q': lucro_trimestre, 'a': lucro_anual}}}
    S = json_load('acoes.json', {})      # {cnpj: {AAAA-MM-DD: [on, pn]}}
    feitos = set(json_load('anos_balancos.json', []))
    hoje = dt.date.today()
    for a in range(ANO0, hoje.year + 1):
        if str(a) in feitos and a not in anos_novos:
            continue
        for tipo, url in (('ITR', ITR), ('DFP', DFP)):
            try:
                zb = baixa(url.format(a))
            except Exception as e:
                print('aviso', tipo, a, e); continue
            if not zb:
                continue
            z = zipfile.ZipFile(io.BytesIO(zb))
            grupos = {}
            for parte in ('DRE_con', 'DRE_ind'):
                for r in ler(z, parte + r'_\d{4}'):
                    if r.get('ORDEM_EXERC', '').upper() not in ('ÚLTIMO', 'ULTIMO'):
                        continue
                    c = so_digitos(r['CNPJ_CIA'])
                    k = (c, r['DT_REFER'], r['DT_INI_EXERC'], r['DT_FIM_EXERC'])
                    g = grupos.setdefault(parte, {}).setdefault(k, {})
                    v = int(r.get('VERSAO') or 0)
                    if v >= g.get('_v', -1):
                        if v > g.get('_v', -1):
                            g.clear(); g['_v'] = v
                        g.setdefault('linhas', []).append(r)
            for parte in ('DRE_con', 'DRE_ind'):
                for (c, ref, ini, fim), g in grupos.get(parte, {}).items():
                    if parte == 'DRE_ind' and any(k[0] == c and k[1] == ref for k in grupos.get('DRE_con', {})):
                        continue   # há consolidado: fica o consolidado
                    r = lucro_de(g.get('linhas', []))
                    if not r:
                        continue
                    esc = 1000 if (r.get('ESCALA_MOEDA') or '').upper().startswith('MIL') else 1
                    v = num(r.get('VL_CONTA'))
                    if v is None:
                        continue
                    dias = (dt.date.fromisoformat(fim) - dt.date.fromisoformat(ini)).days
                    reg = L.setdefault(c, {}).setdefault(fim, {})
                    if tipo == 'ITR' and dias <= 100:
                        reg['q'] = v * esc
                    elif tipo == 'DFP' and dias >= 330:
                        reg['a'] = v * esc
            for r in ler(z, r'composicao_capital'):
                c = so_digitos(r['CNPJ_CIA'])
                on = (num(r.get('QT_ACAO_ORDIN_CAP_INTEGR')) or 0) - (num(r.get('QT_ACAO_ORDIN_TESOURO')) or 0)
                pn = (num(r.get('QT_ACAO_PREF_CAP_INTEGR')) or 0) - (num(r.get('QT_ACAO_PREF_TESOURO')) or 0)
                if on + pn > 0:
                    S.setdefault(c, {})[r['DT_REFER']] = [on, pn]
            print(tipo, a, 'ok')
            del zb, z, grupos
        if a < hoje.year - 1:     # anos fechados (o DFP do ano anterior sai em março)
            feitos.add(str(a))
    json_save('lucros.json', L)
    json_save('acoes.json', S)
    json_save('anos_balancos.json', sorted(feitos))
    return L, S


def lucro_12m(Lc, ate):
    """Lucro dos últimos 4 trimestres conhecidos até a data 'ate' (AAAA-MM-DD), respeitando o atraso de divulgação."""
    pontos = []
    for fim, reg in Lc.items():
        d = dt.date.fromisoformat(fim)
        atraso = 90 if d.month == 12 else 45
        if (d + dt.timedelta(days=atraso)).isoformat() <= ate:
            pontos.append((fim, reg))
    if not pontos:
        return None, None
    pontos.sort()
    trimestres = {}
    for fim, reg in pontos:
        d = dt.date.fromisoformat(fim)
        if 'q' in reg:
            trimestres[(d.year, (d.month - 1) // 3)] = reg['q']
        if 'a' in reg and d.month == 12:
            q = [trimestres.get((d.year, i)) for i in range(3)]
            if all(x is not None for x in q):
                trimestres[(d.year, 3)] = reg['a'] - sum(q)
    ultimo = dt.date.fromisoformat(pontos[-1][0])
    y, q = ultimo.year, (ultimo.month - 1) // 3
    seq = []
    for _ in range(4):
        seq.append(trimestres.get((y, q)))
        q -= 1
        if q < 0:
            y, q = y - 1, 3
    if all(x is not None for x in seq):
        return sum(seq), pontos[-1][0]
    reg = Lc.get(f'{ultimo.year - 1}-12-31') or {}
    if 'a' in reg and (ultimo - dt.date(ultimo.year - 1, 12, 31)).days < 200:
        return reg['a'], f'{ultimo.year - 1}-12-31'
    return None, None


def acoes_em(Sc, ate, hoje):
    """Quantidade de ações do formulário mais próximo da data (antes ou depois): a quantidade não é
    informação de mercado, e assim desdobramentos/grupamentos ficam alinhados com o preço o quanto antes."""
    if not Sc:
        return None
    alvo = dt.date.fromisoformat(ate)
    k = min(Sc, key=lambda k: abs((dt.date.fromisoformat(k) - alvo).days))
    return Sc[k]


# ---------------- juro real (Tesouro IPCA+) ----------------
def juro_real():
    txt = baixa(TESOURO).decode('latin-1').splitlines()
    rd = csv.reader(txt, delimiter=';')
    next(rd)
    por_mes = {}
    for t, venc, base, tx, *_ in rd:
        if t.strip() != 'Tesouro IPCA+':
            continue
        try:
            d = dt.datetime.strptime(base, '%d/%m/%Y').date()
            v = dt.datetime.strptime(venc, '%d/%m/%Y').date()
            x = float(tx.replace(',', '.'))
        except ValueError:
            continue
        anos = (v - d).days / 365.25
        k = d.strftime('%Y-%m')
        cand = (abs(anos - 10), -d.toordinal(), x, v.year)
        if k not in por_mes or cand < por_mes[k]:
            por_mes[k] = cand
    out = {k: {'taxa': v[2], 'venc': v[3]} for k, v in por_mes.items()}
    print('Tesouro IPCA+:', len(out), 'meses')
    return out


def main():
    hoje = dt.date.today()
    # preços: o ano corrente todo dia (e o anterior só em janeiro); balanços: segunda-feira ou quando forçado
    anos_precos = {hoje.year} | ({hoje.year - 1} if hoje.month == 1 else set())
    anos_bal = {hoje.year, hoje.year - 1} if (hoje.weekday() == 0 or os.environ.get('FORCA_BALANCOS')) else set()
    cart = carteira_ibov()
    tk2c, nomes = tickers()
    P = precos(anos_precos)
    L, S = balancos(anos_bal)
    try:
        NTNB = juro_real()
    except Exception as e:
        print('aviso Tesouro', e); NTNB = {}
    # empresas da carteira atual e seus códigos (ON e PN mais negociada)
    emp = {}
    for tk, peso in cart.items():
        c = tk2c.get(tk)
        if not c:
            base = tk[:4]
            c = next((cc for t2, cc in tk2c.items() if t2.startswith(base)), None)
        if not c:
            print('sem CNPJ para', tk)
            continue
        e = emp.setdefault(c, {'cnpj': c, 'nome': nomes.get(c, ''), 'tks': set(), 'peso': 0})
        e['tks'].add(tk)
        e['peso'] += peso or 0
    for c, e in emp.items():
        todos = [t for t, cc in tk2c.items() if cc == c and t in P]
        e['on'] = [t for t in todos if t[4:] == '3']
        e['pn'] = [t for t in todos if t[4:] in ('4', '5', '6', '7', '8')]
    meses = sorted({k for t in P.values() for k in t})
    meses = [m for m in meses if m >= f'{ANO0}-06']

    def preco(lista, m):
        best = None
        for t in lista:
            x = P.get(t, {}).get(m)
            if x and (best is None or x[1] > best[1]):
                best = x
        return best[0] if best else None

    serie, detalhe_ult = [], []
    for m in meses:
        a, mm = int(m[:4]), int(m[5:])
        fim_mes = (dt.date(a + (mm == 12), mm % 12 + 1, 1) - dt.timedelta(days=1)).isoformat()
        ref = min(fim_mes, hoje.isoformat())
        tot = {'ibov': [0, 0, 0], 'ex_petro': [0, 0, 0], 'ex_petro_vale': [0, 0, 0]}
        det = []
        for c, e in emp.items():
            sh = acoes_em(S.get(c, {}), ref, hoje)
            lu, base_lu = lucro_12m(L.get(c, {}), ref)
            p_on, p_pn = preco(e['on'], m), preco(e['pn'], m)
            if not sh or lu is None or (p_on is None and p_pn is None):
                continue
            on, pn = sh
            vm = (on * (p_on if p_on is not None else p_pn)) + (pn * (p_pn if p_pn is not None else p_on))
            if vm <= 0:
                continue
            for k in tot:
                if (k == 'ex_petro' and c == PETRO) or (k == 'ex_petro_vale' and c in (PETRO, VALE)):
                    continue
                tot[k][0] += vm; tot[k][1] += lu; tot[k][2] += 1
            det.append({'cnpj': c, 'nome': e['nome'], 'tks': sorted(e['tks']), 'vm': round(vm), 'lucro': round(lu), 'base': base_lu,
                        'pl': round(vm / lu, 2) if lu > 0 else None})
        if tot['ibov'][2] < 25:
            continue
        reg = {'m': m, 'n': tot['ibov'][2]}
        for k, (vm, lu, n) in tot.items():
            reg[k] = round(vm / lu, 2) if lu > 0 else None
            if k == 'ibov':
                reg['vm'] = round(vm / 1e9, 1); reg['lucro'] = round(lu / 1e9, 1)
        jr = NTNB.get(m)
        if jr:
            reg['ntnb'] = jr['taxa']
        serie.append(reg)
        detalhe_ult = det
    def estat(k):
        xs = [r[k] for r in serie if r.get(k) and 0 < r[k] < 60]
        if len(xs) < 12:
            return None
        mu = sum(xs) / len(xs)
        sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / (len(xs) - 1))
        atual = serie[-1].get(k)
        pct = sum(1 for x in xs if x <= atual) / len(xs) * 100 if atual else None
        return {'media': round(mu, 2), 'dp': round(sd, 2), 'min': min(xs), 'max': max(xs), 'atual': atual,
                'z': round((atual - mu) / sd, 2) if atual and sd else None, 'percentil': round(pct) if pct is not None else None,
                'media_10a': round(sum(xs[-120:]) / len(xs[-120:]), 2)}
    tot_vm = sum(d['vm'] for d in detalhe_ult) or 1
    out = {'gerado_em': dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'ultimo_pregao': max((x[2] for t in P.values() for x in t.values()), default=None),
           'serie': serie, 'estatisticas': {k: estat(k) for k in ('ibov', 'ex_petro', 'ex_petro_vale')},
           'empresas': sorted([dict(d, peso_vm=round(d['vm'] / tot_vm * 100, 2)) for d in detalhe_ult], key=lambda d: -d['vm']),
           'carteira_n': len(cart), 'empresas_n': len(detalhe_ult)}
    if serie and serie[-1].get('ntnb') is None and NTNB:
        out['ntnb_atual'] = NTNB[max(NTNB)]
    json.dump(out, open(SAIDA, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    u = serie[-1] if serie else {}
    print('OK valuation:', len(serie), 'meses; último', u)
    print('estatísticas', out['estatisticas'])


if __name__ == '__main__':
    sys.exit(main())
