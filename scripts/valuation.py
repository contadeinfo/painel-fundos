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
# códigos que o FCA às vezes não traz (CNPJ conferido no cadastro da CVM)
CNPJ_EXTRA = {'BPAC': '30306294000145', 'CSNA': '33042730000104', 'CMIN': '08902291000115', 'MBRF': '03853896000140'}
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
    q = base64.b64encode(json.dumps({"language": "pt-br", "pageNumber": 1, "pageSize": 150, "index": "IBOV", "segment": "2"}).encode()).decode()
    j = json.loads(baixa('https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall/GetPortfolioDay/' + q))
    out = {}
    for r in j.get('results', []):
        tk = (r.get('cod') or r.get('code') or '').strip().upper()
        p = num(str(r.get('part') or '0').replace('.', '').replace(',', '.'))
        if tk:
            out[tk] = (p, setor_de(r.get('segment') or ''))
    print('carteira IBOV:', len(out), 'ações; data', (j.get('header') or {}).get('date'))
    return out


SETORES = [(r'financ', 'Financeiro'), (r'petr', 'Petróleo e gás'), (r'mat', 'Materiais básicos'), (r'util', 'Energia e saneamento'),
           (r'cons|divers', 'Consumo e varejo'), (r'bens', 'Indústria e logística'), (r'sa[uú]de', 'Saúde'), (r'comunic|tec', 'Telecom e tecnologia')]


def setor_de(seg):
    x = seg.lower()
    return next((nome for rx, nome in SETORES if re.search(rx, x.split('/')[0])), 'Outros')


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
TK_OK = re.compile(r'^[A-Z0-9]{4}(3|4|5|6|7|8|11)$')


def precos(anos_novos):
    """Fechamento do último pregão de cada mês, por código (lote padrão). Um arquivo por ano em data/valuation/;
    anos fechados não são baixados de novo (o arquivo da B3 tem ~100 MB por ano)."""
    hoje = dt.date.today()
    P = {}
    for a in range(ANO0, hoje.year + 1):
        nome = f'precos_v2_{a}.json'
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
    PL = json_load('patrimonio.json', {})   # {cnpj: {AAAA-MM-DD: patrimônio líquido dos controladores}}
    PV = json_load('proventos.json', {})    # {cnpj: {AAAA-MM-DD: dividendos + JCP acumulados no ano (DVA)}}
    EN = json_load('entregas.json', {})     # {cnpj: {AAAA-MM-DD (fim do período): data de entrega à CVM}}
    PC = json_load('proventos_caixa.json', {})  # {cnpj: {AAAA-MM-DD: dividendos + JCP pagos acumulados no ano (DFC)}}
    feitos = set(json_load('anos_balancos_v4.json', []))
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
                    elif tipo == 'ITR' and dias > 100:
                        reg['y'] = v * esc      # acumulado no ano (algumas empresas só preenchem esta coluna)
                    elif tipo == 'DFP' and dias >= 330:
                        reg['a'] = v * esc
            for r in ler(z, r'composicao_capital'):
                c = so_digitos(r['CNPJ_CIA'])
                on = (num(r.get('QT_ACAO_ORDIN_CAP_INTEGR')) or 0) - (num(r.get('QT_ACAO_ORDIN_TESOURO')) or 0)
                pn = (num(r.get('QT_ACAO_PREF_CAP_INTEGR')) or 0) - (num(r.get('QT_ACAO_PREF_TESOURO')) or 0)
                if 0 < on + pn < 5e7:     # várias companhias informam a quantidade em milhares
                    on, pn = on * 1000, pn * 1000
                if on + pn > 0:
                    S.setdefault(c, {})[r['DT_REFER']] = [on, pn]
            le_extras(z, tipo, PL, PV, EN, PC)
            print(tipo, a, 'ok')
            del zb, z, grupos
        if a < hoje.year - 1:     # anos fechados (o DFP do ano anterior sai em março)
            feitos.add(str(a))
    json_save('lucros.json', L)
    json_save('acoes.json', S)
    json_save('patrimonio.json', PL)
    json_save('proventos.json', PV)
    json_save('entregas.json', EN)
    json_save('proventos_caixa.json', PC)
    json_save('anos_balancos_v4.json', sorted(feitos))
    return L, S, PL, PV, EN, PC


PL_RX = re.compile(r'^patrim[oô]nio l[ií]quido', re.I)
NC_RX = re.compile(r'n[aã]o controladores', re.I)
JCP_RX = re.compile(r'^juros sobre (o )?capital pr[oó]prio', re.I)
DIV_RX = re.compile(r'^dividendos', re.I)


PAGO_RX = re.compile(r'dividend|juros sobre (o )?capital', re.I)
NAO_RX = re.compile(r'recebid|n[aã]o controlador|minorit', re.I)


def le_extras(z, tipo, PL, PV, EN, PC):
    """Patrimônio (BPP), dividendos + JCP (DVA, acumulado no ano) e data de entrega de cada formulário."""
    ult = lambda r: r.get('ORDEM_EXERC', '').upper() in ('ÚLTIMO', 'ULTIMO')
    for parte in ('con', 'ind'):
        tmp = {}
        for r in ler(z, rf'BPP_{parte}_\d{{4}}'):
            if not ult(r):
                continue
            c, ref, cd = so_digitos(r['CNPJ_CIA']), r['DT_REFER'], r['CD_CONTA']
            esc = 1000 if (r.get('ESCALA_MOEDA') or '').upper().startswith('MIL') else 1
            v = num(r.get('VL_CONTA'))
            if v is None:
                continue
            d = tmp.setdefault((c, ref), {})
            if cd.count('.') == 1 and PL_RX.search(r['DS_CONTA']):
                d['pl'] = v * esc; d['raiz'] = cd
            elif cd.count('.') == 2 and NC_RX.search(r['DS_CONTA']):
                d.setdefault('nc', {})[cd.rsplit('.', 1)[0]] = v * esc
        for (c, ref), d in tmp.items():
            if 'pl' not in d or (parte == 'ind' and ref in PL.get(c, {})):
                continue
            PL.setdefault(c, {})[ref] = d['pl'] - (d.get('nc') or {}).get(d['raiz'], 0)
        tmp = {}
        for r in ler(z, rf'DVA_{parte}_\d{{4}}'):
            if not ult(r) or not r['CD_CONTA'].startswith('7.'):
                continue
            ds = r['DS_CONTA'].strip()
            if not (JCP_RX.search(ds) or DIV_RX.search(ds)) or r['CD_CONTA'].count('.') != 3:
                continue
            c, fim = so_digitos(r['CNPJ_CIA']), r['DT_FIM_EXERC']
            if not r['DT_INI_EXERC'].endswith('-01-01'):
                continue
            esc = 1000 if (r.get('ESCALA_MOEDA') or '').upper().startswith('MIL') else 1
            k = (c, fim)
            tmp[k] = tmp.get(k, 0) + (num(r.get('VL_CONTA')) or 0) * esc
        for (c, fim), v in tmp.items():
            if parte == 'ind' and fim in PV.get(c, {}):
                continue
            PV.setdefault(c, {})[fim] = v
    for parte in ('con', 'ind'):
        tmp = {}
        for r in ler(z, rf'DFC_M[DI]_{parte}_\d{{4}}'):
            cd = r['CD_CONTA']
            if not ult(r) or not cd.startswith('6.03.') or cd.count('.') != 2 or not r['DT_INI_EXERC'].endswith('-01-01'):
                continue
            ds = r['DS_CONTA']
            if not PAGO_RX.search(ds) or NAO_RX.search(ds):
                continue
            esc = 1000 if (r.get('ESCALA_MOEDA') or '').upper().startswith('MIL') else 1
            k = (so_digitos(r['CNPJ_CIA']), r['DT_FIM_EXERC'])
            tmp[k] = tmp.get(k, 0) + abs(num(r.get('VL_CONTA')) or 0) * esc
        for (c, fim), v in tmp.items():
            if parte == 'ind' and fim in PC.get(c, {}):
                continue
            PC.setdefault(c, {})[fim] = v
    for r in ler(z, rf'^(itr|dfp)_cia_aberta_\d{{4}}\.csv$'):
        c = so_digitos(r['CNPJ_CIA'])
        atual = EN.setdefault(c, {}).get(r['DT_REFER'])
        if r.get('DT_RECEB') and (atual is None or r['DT_RECEB'] < atual):   # primeira entrega (não a reapresentação)
            EN[c][r['DT_REFER']] = r['DT_RECEB']


def normaliza_trimestres(L):
    """Quando o trimestre vem zerado ou vazio mas o acumulado do ano existe, o trimestre = acumulado − acumulado anterior."""
    for c, D in L.items():
        for fim in sorted(D):
            reg = D[fim]
            if 'y' not in reg or (reg.get('q') not in (None, 0)):
                continue
            y, m = int(fim[:4]), int(fim[5:7])
            ant = {6: f'{y}-03-31', 9: f'{y}-06-30'}.get(m)
            if not ant or ant not in D:
                continue
            ra = D[ant]
            base = ra.get('y') if m == 9 and ra.get('y') is not None else ra.get('q')
            if m == 9 and ra.get('y') is None and ra.get('q') is not None:
                q1 = D.get(f'{y}-03-31', {}).get('q')
                base = (q1 + ra['q']) if q1 is not None else None
            if base is not None:
                reg['q'] = reg['y'] - base
    return L


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


def corrige_milhares(S):
    for c, d in S.items():
        for k, (on, pn) in d.items():
            if 0 < on + pn < 5e7:
                d[k] = [on * 1000, pn * 1000]
    return S


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
    L, S, PLC, PV, EN, PC = balancos(anos_bal)
    L = normaliza_trimestres(L)
    S = corrige_milhares(S)
    try:
        NTNB = juro_real()
    except Exception as e:
        print('aviso Tesouro', e); NTNB = {}
    # empresas da carteira atual e seus códigos (ON e PN mais negociada)
    emp = {}
    for tk, (peso, setor) in cart.items():
        c = tk2c.get(tk)
        if not c:
            base = tk[:4]
            c = next((cc for t2, cc in tk2c.items() if t2.startswith(base)), None) or CNPJ_EXTRA.get(base)
        if not c:
            print('sem CNPJ para', tk)
            continue
        e = emp.setdefault(c, {'cnpj': c, 'nome': nomes.get(c, ''), 'tks': set(), 'peso': 0, 'setor': setor})
        e['tks'].add(tk)
        e['peso'] += peso or 0
    for c, e in emp.items():
        bases = {t[:4] for t in e['tks']}
        todos = sorted({t for t, cc in tk2c.items() if cc == c and t in P} | {t for t in P if t[:4] in bases})
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

    def disponivel(fim, ref):
        d = dt.date.fromisoformat(fim)
        return (d + dt.timedelta(days=90 if d.month == 12 else 45)).isoformat() <= ref

    def pl_contabil(c, ref):
        ks = [k for k in PLC.get(c, {}) if disponivel(k, ref)]
        return PLC[c][max(ks)] if ks else None

    def prov_12m(c, ref):
        D = PC.get(c) or PV.get(c, {})
        ks = [k for k in D if disponivel(k, ref)]
        if not ks:
            return None
        f = max(ks)
        if f.endswith('-12-31'):
            return D[f]
        ant_ano, ant_mes = f'{int(f[:4]) - 1}-12-31', f'{int(f[:4]) - 1}{f[4:]}'
        if ant_ano in D and ant_mes in D:
            return D[f] + D[ant_ano] - D[ant_mes]
        return None

    CHAVES = ('ibov', 'ex_petro', 'ex_petro_vale')
    serie, detalhe_ult = [], []
    for m in meses:
        a, mm = int(m[:4]), int(m[5:])
        fim_mes = (dt.date(a + (mm == 12), mm % 12 + 1, 1) - dt.timedelta(days=1)).isoformat()
        ref = min(fim_mes, hoje.isoformat())
        tot = {k: [0, 0, 0] for k in CHAVES}
        sets, dy, pvp = {}, [0, 0], [0, 0]
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
            x = sets.setdefault(e['setor'], [0, 0, 0]); x[0] += vm; x[1] += lu; x[2] += 1
            pv, plc = prov_12m(c, ref), pl_contabil(c, ref)
            if pv is not None and pv >= 0:
                dy[0] += pv; dy[1] += vm
            if plc and plc > 0:
                pvp[0] += vm; pvp[1] += plc
            det.append({'cnpj': c, 'nome': e['nome'], 'tks': sorted(e['tks']), 'setor': e['setor'], 'vm': round(vm), 'lucro': round(lu), 'base': base_lu,
                        'pl': round(vm / lu, 2) if lu > 0 else None, 'dy': round(pv / vm * 100, 2) if pv is not None and pv >= 0 else None,
                        'pvp': round(vm / plc, 2) if plc and plc > 0 else None})
        if tot['ibov'][2] < 25:
            continue
        reg = {'m': m, 'n': tot['ibov'][2]}
        for k, (vm, lu, n) in tot.items():
            reg[k] = round(vm / lu, 2) if lu > 0 else None
            if k == 'ibov':
                reg['vm'] = round(vm / 1e9, 1); reg['lucro'] = round(lu / 1e9, 1)
        reg['dy'] = round(dy[0] / dy[1] * 100, 2) if dy[1] > tot['ibov'][0] * .6 else None
        reg['pvp'] = round(pvp[0] / pvp[1], 2) if pvp[1] and pvp[0] > tot['ibov'][0] * .6 else None
        reg['set'] = {k: (round(v[0] / v[1], 2) if v[1] > 0 else None) for k, v in sets.items() if v[2] >= 2}
        jr = NTNB.get(m)
        if jr:
            reg['ntnb'] = jr['taxa']
        serie.append(reg)
        detalhe_ult = det

    def estat_de(xs, atual):
        xs = [x for x in xs if x is not None and 0 < x < 60]
        if len(xs) < 12 or atual is None:
            return None
        mu = sum(xs) / len(xs)
        sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / (len(xs) - 1))
        pct = sum(1 for x in xs if x <= atual) / len(xs) * 100
        q = sorted(xs)
        qt = lambda f: round(q[min(len(q) - 1, int(f * (len(q) - 1) + .5))], 2)
        return {'media': round(mu, 2), 'dp': round(sd, 2), 'min': min(xs), 'max': max(xs), 'atual': atual,
                'mediana': qt(.5), 'p25': qt(.25), 'p75': qt(.75),
                'z': round((atual - mu) / sd, 2) if sd else None, 'percentil': round(pct),
                'media_10a': round(sum(xs[-120:]) / len(xs[-120:]), 2)}
    estat = {k: estat_de([r.get(k) for r in serie], serie[-1].get(k)) for k in CHAVES + ('dy', 'pvp')}
    setores = {}
    for st in sorted({k for r in serie for k in r['set']}):
        e = estat_de([r['set'].get(st) for r in serie], serie[-1]['set'].get(st))
        if e:
            e['n'] = sum(1 for d in detalhe_ult if d['setor'] == st)
            e['vm'] = round(sum(d['vm'] for d in detalhe_ult if d['setor'] == st) / 1e9, 1)
            setores[st] = e

    # ---- lucro trimestre a trimestre (composição atual) ----
    def tri_map(Lc):
        T = {}
        for fim in sorted(Lc):
            reg, d = Lc[fim], dt.date.fromisoformat(fim)
            if 'q' in reg:
                T[(d.year, (d.month - 1) // 3)] = reg['q']
            if 'a' in reg and d.month == 12:
                q = [T.get((d.year, i)) for i in range(3)]
                if all(x is not None for x in q):
                    T[(d.year, 3)] = reg['a'] - sum(q)
        return T
    TM = {c: tri_map(L.get(c, {})) for c in emp}
    todos_t = sorted({t for T in TM.values() for t in T})
    trimestres = []
    for (y, q) in todos_t[-16:]:
        base = [c for c in emp if (y, q) in TM[c]]
        comp = [c for c in base if (y - 1, q) in TM[c]]
        if len(base) < 25:
            continue
        tot_c, ant_c = sum(TM[c][(y, q)] for c in comp), sum(TM[c][(y - 1, q)] for c in comp)
        semp = [c for c in comp if c != PETRO]
        tot_s, ant_s = sum(TM[c][(y, q)] for c in semp), sum(TM[c][(y - 1, q)] for c in semp)
        trimestres.append({'t': f'{q + 1}T{str(y)[2:]}', 'n': len(base), 'lucro': round(sum(TM[c][(y, q)] for c in base) / 1e9, 2),
                           'lucro_ex_petro': round(sum(TM[c][(y, q)] for c in base if c != PETRO) / 1e9, 2),
                           'var_aa': round((tot_c / ant_c - 1) * 100, 1) if ant_c > 0 else None,
                           'var_aa_ex_petro': round((tot_s / ant_s - 1) * 100, 1) if ant_s > 0 else None, 'n_comp': len(comp)})
    resultados = []
    for c, e in emp.items():
        T = TM[c]
        if not T:
            continue
        (y, q) = max(T)
        atual, ant, tri_ant = T[(y, q)], T.get((y - 1, q)), T.get((y, q - 1) if q else (y - 1, 3))
        fim = f'{y}-{[3, 6, 9, 12][q]:02d}-{[31, 30, 30, 31][q]}'
        resultados.append({'tks': sorted(e['tks']), 'nome': e['nome'], 'setor': e['setor'], 't': f'{q + 1}T{str(y)[2:]}', 'fim': fim,
                           'entregue': EN.get(c, {}).get(fim), 'lucro': round(atual / 1e6, 1), 'lucro_aa': round(ant / 1e6, 1) if ant is not None else None,
                           'var_aa': round((atual / ant - 1) * 100, 1) if ant and ant > 0 and atual > 0 else None,
                           'lucro_tri_ant': round(tri_ant / 1e6, 1) if tri_ant is not None else None})
    resultados.sort(key=lambda r: (r['entregue'] or ''), reverse=True)

    # ---- calendário de resultados (estimado pela data do ano anterior) ----
    fins = lambda y: [f'{y}-03-31', f'{y}-06-30', f'{y}-09-30', f'{y}-12-31']
    proximos, recentes = [], []
    lim_rec = (hoje - dt.timedelta(days=21)).isoformat()
    for c, e in emp.items():
        E = EN.get(c, {})
        entregues = sorted(k for k in E)
        for k in entregues:
            if E[k] >= lim_rec:
                recentes.append({'tks': sorted(e['tks']), 'nome': e['nome'], 'periodo': k, 'data': E[k]})
        ult = entregues[-1] if entregues else None
        if not ult:
            continue
        y = int(ult[:4]); seq = fins(y) + fins(y + 1)
        prox = next((f for f in seq if f > ult), None)
        if not prox:
            continue
        ant = E.get(f'{int(prox[:4]) - 1}{prox[4:]}')
        if ant:
            d = dt.date.fromisoformat(ant).replace(year=dt.date.fromisoformat(ant).year + 1)
            while d.weekday() >= 5:
                d -= dt.timedelta(days=1)
            base = 'mesma época do ano anterior'
        else:
            pd_ = dt.date.fromisoformat(prox); d = pd_ + dt.timedelta(days=90 if pd_.month == 12 else 45); base = 'prazo legal'
        limite = dt.date.fromisoformat(prox) + dt.timedelta(days=90 if prox.endswith('12-31') else 45)
        proximos.append({'tks': sorted(e['tks']), 'nome': e['nome'], 'setor': e['setor'], 'periodo': prox, 'previsto': d.isoformat(),
                         'base': base, 'prazo': limite.isoformat(), 'atrasado': hoje > limite})
    proximos.sort(key=lambda r: r['previsto'])
    recentes.sort(key=lambda r: r['data'], reverse=True)

    tot_vm = sum(d['vm'] for d in detalhe_ult) or 1
    out = {'gerado_em': dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'ultimo_pregao': max((x[2] for t in P.values() for x in t.values()), default=None),
           'serie': serie, 'estatisticas': estat, 'setores': setores,
           'empresas': sorted([dict(d, peso_vm=round(d['vm'] / tot_vm * 100, 2)) for d in detalhe_ult], key=lambda d: -d['vm']),
           'trimestres': trimestres, 'resultados': resultados, 'calendario': {'proximos': proximos, 'recentes': recentes[:40]},
           'carteira_n': len(cart), 'empresas_n': len(detalhe_ult)}
    if serie and serie[-1].get('ntnb') is None and NTNB:
        out['ntnb_atual'] = NTNB[max(NTNB)]
    json.dump(out, open(SAIDA, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    u = serie[-1] if serie else {}
    print('OK valuation:', len(serie), 'meses; último', u)
    print('estatísticas', estat)
    print('setores', {k: (v['atual'], v['mediana']) for k, v in setores.items()})
    print('trimestres', trimestres[-4:])
    print('calendário', proximos[:5])


if __name__ == '__main__':
    sys.exit(main())
