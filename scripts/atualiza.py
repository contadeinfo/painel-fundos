#!/usr/bin/env python3
"""Robô do Relatório Peers.

Baixa o informe diário de fundos da CVM (dados abertos), guarda só as linhas
dos fundos de fundos.json e calcula retorno (dia, mês, ano, 12/24/36/48/60
meses), patrimônio e captação líquida no ano. Também calcula IBOV e CDI nas
mesmas janelas. Resultado: data/peers.json (lido pelo Painel Comercial).

Fontes:
  CVM  https://dados.cvm.gov.br/dados/FI/DOC/INF_DIARIO/DADOS/inf_diario_fi_AAAAMM.zip
  BCB  SGS série 12 (CDI diário)
  Yahoo Finance ^BVSP (Ibovespa)
"""
import csv, io, json, os, re, sys, time, zipfile, datetime as dt, urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(RAIZ, 'data', 'cvm')          # um CSV pequeno por mês, só com os nossos CNPJs
SAIDA = os.path.join(RAIZ, 'data', 'peers.json')
CVM = 'https://dados.cvm.gov.br/dados/FI/DOC/INF_DIARIO/DADOS/inf_diario_fi_{}.zip'
CVM_HIST = 'https://dados.cvm.gov.br/dados/FI/DOC/INF_DIARIO/DADOS/HIST/inf_diario_fi_{}.zip'
UA = {'User-Agent': 'Mozilla/5.0 (painel-fundos; dados abertos CVM)'}
MESES_HIST = 62          # 60 meses + folga
REBAIXAR = 2             # mês atual e anterior são sempre baixados de novo (CVM revisa)


def baixa(url, tent=4):
    for i in range(tent):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            err = e
        except Exception as e:  # rede instável
            err = e
        time.sleep(5 * (i + 1))
    raise RuntimeError(f'falhou {url}: {err}')


def so_digitos(s):
    return re.sub(r'\D', '', s or '').zfill(14)


def num(s):
    s = (s or '').strip()
    return float(s) if s else None


def meses_ate(hoje, n):
    a, m = hoje.year, hoje.month
    out = []
    for _ in range(n):
        out.append(f'{a}{m:02d}')
        m -= 1
        if m == 0:
            a, m = a - 1, 12
    return out[::-1]


def filtra_zip(conteudo, alvo):
    """Lê o zip da CVM e devolve linhas [cnpj, data, cota, pl, capt, resg] dos CNPJs alvo."""
    linhas = []
    with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
        for nome in z.namelist():
            with z.open(nome) as f:
                rd = csv.reader(io.TextIOWrapper(f, encoding='latin-1', newline=''), delimiter=';')
                cab = [c.strip().upper() for c in next(rd)]
                ic = next(i for i, c in enumerate(cab) if c.startswith('CNPJ_FUNDO'))
                isub = cab.index('ID_SUBCLASSE') if 'ID_SUBCLASSE' in cab else None
                idt, iq, ipl = cab.index('DT_COMPTC'), cab.index('VL_QUOTA'), cab.index('VL_PATRIM_LIQ')
                icap, ires = cab.index('CAPTC_DIA'), cab.index('RESG_DIA')
                icot = cab.index('NR_COTST') if 'NR_COTST' in cab else None
                for r in rd:
                    if len(r) <= ires:
                        continue
                    c = so_digitos(r[ic])
                    if c not in alvo:
                        continue
                    if isub is not None and r[isub].strip():
                        continue  # subclasse: usamos a linha da classe
                    linhas.append([c, r[idt][:10], r[iq], r[ipl], r[icap], r[ires], r[icot] if icot is not None and len(r) > icot else ''])
    return linhas


def atualiza_cache(alvo, hoje):
    os.makedirs(CACHE, exist_ok=True)
    marca = os.path.join(CACHE, 'cnpjs.txt')
    lista = 'v2\n' + '\n'.join(sorted(alvo))  # v2: inclui número de cotistas
    mudou = not os.path.exists(marca) or open(marca).read() != lista
    if mudou:
        print('  lista de fundos mudou: rebaixando todo o histórico')
    meses = meses_ate(hoje, MESES_HIST)
    recentes = set(meses[-REBAIXAR:])
    for am in meses:
        arq = os.path.join(CACHE, f'{am}.csv')
        if os.path.exists(arq) and am not in recentes and not mudou:
            continue
        z = baixa(CVM.format(am)) or baixa(CVM_HIST.format(am))
        if z is None:
            print(f'  {am}: ainda não publicado')
            continue
        L = filtra_zip(z, alvo)
        with open(arq, 'w', encoding='utf-8', newline='') as f:
            w = csv.writer(f)
            w.writerow(['cnpj', 'data', 'cota', 'pl', 'capt', 'resg', 'cotst'])
            w.writerows(sorted(L))
        print(f'  {am}: {len(L)} linhas, {len({l[0] for l in L})} fundos')
    with open(marca, 'w') as f:
        f.write(lista)


def le_cache():
    S = {}
    for arq in sorted(os.listdir(CACHE)):
        if not re.fullmatch(r'\d{6}\.csv', arq):
            continue
        with open(os.path.join(CACHE, arq), encoding='utf-8') as f:
            for r in csv.DictReader(f):
                S.setdefault(r['cnpj'], {})[r['data']] = (num(r['cota']), num(r['pl']), num(r['capt']) or 0, num(r['resg']) or 0, num(r.get('cotst')))
    return S


def menos_meses(d, n):
    a, m = d.year, d.month - n
    while m <= 0:
        a, m = a - 1, m + 12
    import calendar
    return dt.date(a, m, min(d.day, calendar.monthrange(a, m)[1]))


def valor_em(serie, datas, limite):
    """Último valor com data <= limite."""
    import bisect
    i = bisect.bisect_right(datas, limite) - 1
    return serie[datas[i]] if i >= 0 else None, (datas[i] if i >= 0 else None)


def janelas(serie_cota, ref):
    """serie_cota: {date: valor}. Retornos em % até ref.

    Convenção (igual à do Comdinheiro, conferida em 19/11/2026):
    - dia: contra a cota anterior;
    - mês e ano: contra a última cota do mês/ano anterior;
    - 12 a 60 meses: contra a primeira cota DEPOIS da mesma data N meses antes.
    """
    import bisect
    datas = sorted(d for d in serie_cota if d <= ref)
    if not datas:
        return {}
    ult = datas[-1]
    if ult < ref - dt.timedelta(days=5):
        return {}  # sem cota recente (fundo encerrado ou informe parado): não inventa retorno
    fim = serie_cota[ult]
    def ate(lim):  # última cota <= lim
        i = bisect.bisect_right(datas, lim) - 1
        if i < 0 or datas[i] < lim - dt.timedelta(days=12):
            return None
        return (fim / serie_cota[datas[i]] - 1) * 100
    def depois(lim):  # primeira cota > lim
        if datas[0] > lim:
            return None  # série não cobre a janela
        i = bisect.bisect_right(datas, lim)
        if i >= len(datas) or datas[i] > lim + dt.timedelta(days=12):
            return None
        return (fim / serie_cota[datas[i]] - 1) * 100
    ant = datas[-2] if len(datas) > 1 else None
    out = {
        'dia': (fim / serie_cota[ant] - 1) * 100 if ant else None,
        'mes': ate(dt.date(ult.year, ult.month, 1) - dt.timedelta(days=1)),
        'ano': ate(dt.date(ult.year, 1, 1) - dt.timedelta(days=1)),
    }
    for n in (12, 24, 36, 48, 60):
        out[f'm{n}'] = depois(menos_meses(ult, n))
    return out


def cdi_completo(ini, fim):
    """Índice acumulado do CDI (SGS 12), em blocos de 4 anos (limite da API)."""
    tx, a = {}, ini
    while a <= fim:
        b = min(fim, dt.date(a.year + 4, a.month, 1))
        J = json.loads(baixa('https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados?formato=json'
                             f'&dataInicial={a:%d/%m/%Y}&dataFinal={b:%d/%m/%Y}'))
        for x in J:
            tx[dt.datetime.strptime(x['data'], '%d/%m/%Y').date()] = float(x['valor'])
        a = b + dt.timedelta(days=1)
    out, acc = {}, 1.0
    for d in sorted(tx):
        acc *= 1 + tx[d] / 100   # índice no fechamento de d (convenção da cota de fundo)
        out[d] = acc
    return out


def ibov_serie():
    url = 'https://query1.finance.yahoo.com/v8/finance/chart/%5EBVSP?range=10y&interval=1d'
    J = json.loads(baixa(url))['chart']['result'][0]
    ts, cl = J['timestamp'], J['indicators']['quote'][0]['close']
    s = {}
    for t, c in zip(ts, cl):
        if c:
            s[(dt.datetime.utcfromtimestamp(t) - dt.timedelta(hours=3)).date()] = c
    return s


def main():
    fundos = json.load(open(os.path.join(RAIZ, 'fundos.json'), encoding='utf-8'))
    alvo = {so_digitos(f['cnpj']) for f in fundos}
    hoje = dt.date.today()
    print('Baixando informe diário da CVM…')
    atualiza_cache(alvo, hoje)
    S = le_cache()

    # data de referência: a última data com cota para a maioria dos fundos (evita dia parcial)
    ult = sorted(max(map(dt.date.fromisoformat, s)) for s in S.values() if s)
    ref = ult[len(ult) // 2] if ult else hoje
    print('Data de referência:', ref)

    rows, info = [], []
    for f in fundos:
        c = so_digitos(f['cnpj'])
        s = {dt.date.fromisoformat(d): v for d, v in S.get(c, {}).items()}
        cot = {d: v[0] for d, v in s.items() if v[0]}
        J = janelas(cot, ref) if cot else {}
        datas = sorted(d for d in s if d <= ref)
        recente = bool(datas) and datas[-1] >= ref - dt.timedelta(days=5)
        pl = s[datas[-1]][1] if recente else None
        capt = sum(v[2] - v[3] for d, v in s.items() if d.year == ref.year and d <= ref) if recente else None
        ult_d = datas[-1].isoformat() if datas else None
        r = [f['nome']]
        for k in ('dia', 'mes', 'ano', 'm12', 'm24', 'm36', 'm48', 'm60'):
            v = J.get(k)
            r += [round(v, 6) if v is not None else None, None]
        r += [round(pl, 2) if pl else None, None, round(capt, 2) if capt is not None else None, None]
        rows.append(r)
        info.append({'nome': f['nome'], 'cnpj': c, 'ultima_cota': ult_d, 'atrasado': bool(ult_d and ult_d < ref.isoformat())})

    # rankings (posição entre os fundos) nas mesmas colunas
    for j in range(1, 21, 2):
        vals = sorted((r[j] for r in rows if r[j] is not None), reverse=True)
        for r in rows:
            r[j + 1] = vals.index(r[j]) + 1 if r[j] is not None else None

    IDX = {}
    for nome, serie in (('IBOV', lambda: ibov_serie()), ('CDI', lambda: cdi_completo(menos_meses(ref, 62), ref))):
        try:
            IDX[nome] = serie()
            J = janelas(IDX[nome], ref)
            r = [nome]
            for k in ('dia', 'mes', 'ano', 'm12', 'm24', 'm36', 'm48', 'm60'):
                v = J.get(k)
                r += [round(v, 6) if v is not None else None, None]
            rows.append(r + [None] * 4)
        except Exception as e:
            print('aviso', nome, e)

    out = {'data': ref.strftime('%d/%m/%Y'), 'gerado_em': dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'),
           'fonte': 'CVM (informe diário) · BCB · Yahoo', 'rows': rows, 'fundos': info}
    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    try:  # ficha completa de cada fundo (cadastro, lâmina, séries e risco); não impede o peers.json
        import detalhe
        detalhe.gera(fundos, S, IDX, ref, rows, os.path.join(RAIZ, 'data', 'fundos'), baixa, so_digitos)
        out['detalhe'] = True
    except Exception as e:
        import traceback; traceback.print_exc()
        print('aviso detalhe', e)
    with open(SAIDA, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    print(f'OK: {len(rows)} linhas em {SAIDA}')


if __name__ == '__main__':
    sys.exit(main())
