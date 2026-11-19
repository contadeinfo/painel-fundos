"""Ficha completa de cada fundo: data/fundos/<cnpj>.json

Junta tudo o que a CVM publica em dados abertos sobre o fundo:
  - cadastro antigo (cad_fi.csv) e cadastro novo da Resolução 175 (registro_fundo_classe.zip)
  - lâmina mais recente (taxas, aplicação mínima, prazos, composição da carteira)
  - informe diário: cota, patrimônio, cotistas, captação e resgate (5 anos)
e calcula indicadores de risco e retorno contra Ibovespa e CDI.
"""
import csv, io, json, math, os, zipfile, datetime as dt

CAD_ANTIGO = 'https://dados.cvm.gov.br/dados/FI/CAD/DADOS/cad_fi.csv'
CAD_175 = 'https://dados.cvm.gov.br/dados/FI/CAD/DADOS/registro_fundo_classe.zip'
LAMINA = 'https://dados.cvm.gov.br/dados/FI/DOC/LAMINA/DADOS/lamina_fi_{}.zip'

csv.field_size_limit(10 ** 8)


def _ler_csv(fbytes):
    txt = fbytes.decode('latin-1')
    return list(csv.DictReader(io.StringIO(txt), delimiter=';'))


def _limpa(d):
    return {k.strip(): v.strip() for k, v in d.items() if k and v is not None and str(v).strip() not in ('', 'N/A')}


def _col_cnpj(row):
    for k in row:
        if k and (k.upper().startswith('CNPJ_FUNDO') or k.upper() == 'CNPJ_CLASSE'):
            return k
    return None


def cadastro(alvo, baixa, dig):
    out = {c: {} for c in alvo}
    try:
        rows = _ler_csv(baixa(CAD_ANTIGO))
        for r in rows:
            c = dig(r.get('CNPJ_FUNDO'))
            if c in alvo:
                r = _limpa(r)
                # cad_fi pode ter mais de uma linha (registros cancelados); fica a que está em funcionamento
                if not out[c].get('cad_fi') or r.get('SIT', '').upper().startswith('EM FUNCIONAMENTO'):
                    out[c]['cad_fi'] = r
    except Exception as e:
        print('aviso cad_fi', e)
    try:
        z = zipfile.ZipFile(io.BytesIO(baixa(CAD_175)))
        T = {n.lower(): _ler_csv(z.read(n)) for n in z.namelist() if n.lower().endswith('.csv')}
        fundo = next((v for k, v in T.items() if 'registro_fundo' in k), [])
        classe = next((v for k, v in T.items() if 'registro_classe' in k), [])
        sub = next((v for k, v in T.items() if 'registro_subclasse' in k), [])
        por_id_fundo = {r.get('ID_Registro_Fundo'): r for r in fundo}
        for r in classe:
            c = dig(r.get('CNPJ_Classe') or r.get('CNPJ_CLASSE'))
            if c in alvo:
                out[c]['classe'] = _limpa(r)
                f = por_id_fundo.get(r.get('ID_Registro_Fundo'))
                if f:
                    out[c]['fundo'] = _limpa(f)
                idc = r.get('ID_Registro_Classe')
                subs = [_limpa(s) for s in sub if s.get('ID_Registro_Classe') == idc]
                if subs:
                    out[c]['subclasses'] = subs
        for r in fundo:  # fundos cujo CNPJ é o do próprio fundo (sem classe com CNPJ próprio)
            c = dig(r.get('CNPJ_Fundo') or r.get('CNPJ_FUNDO'))
            if c in alvo and 'fundo' not in out[c]:
                out[c]['fundo'] = _limpa(r)
    except Exception as e:
        print('aviso registro_fundo_classe', e)
    return out


def lamina(alvo, baixa, dig, hoje):
    out = {c: {} for c in alvo}
    a, m = hoje.year, hoje.month
    for _ in range(8):  # a lâmina sai com defasagem; procura o mês mais recente publicado
        am = f'{a}{m:02d}'
        try:
            zb = baixa(LAMINA.format(am))
        except Exception:
            zb = None
        if zb:
            z = zipfile.ZipFile(io.BytesIO(zb))
            for n in z.namelist():
                if not n.lower().endswith('.csv'):
                    continue
                parte = n.lower().replace(f'_{am}.csv', '').replace('lamina_fi', '').strip('_') or 'lamina'
                for r in _ler_csv(z.read(n)):
                    k = _col_cnpj(r)
                    c = dig(r.get(k)) if k else None
                    if c in alvo:
                        r = _limpa(r)
                        if parte == 'lamina':
                            out[c]['lamina'] = r
                        else:
                            out[c].setdefault(parte, []).append(r)
            for c in out:
                if out[c]:
                    out[c]['competencia'] = f'{m:02d}/{a}'
            print('  lâmina', am, sum(1 for c in out if out[c]), 'fundos')
            break
        m -= 1
        if m == 0:
            a, m = a - 1, 12
    return out


def _alinha(serie_idx, datas):
    """valor do índice na data (ou último anterior)."""
    import bisect
    ks = sorted(serie_idx)
    out = []
    for d in datas:
        i = bisect.bisect_right(ks, d) - 1
        out.append(serie_idx[ks[i]] if i >= 0 else None)
    return out


def _risco(datas, cota, ibov, cdi, ini):
    idx = [i for i, d in enumerate(datas) if d >= ini]
    if len(idx) < 40:
        return None
    i0 = max(idx[0] - 1, 0)
    rf, ri, rc = [], [], []
    for i in range(i0 + 1, idx[-1] + 1):
        if cota[i - 1] and cota[i]:
            rf.append(cota[i] / cota[i - 1] - 1)
            ri.append(ibov[i] / ibov[i - 1] - 1 if ibov[i] and ibov[i - 1] else 0)
            rc.append(cdi[i] / cdi[i - 1] - 1 if cdi[i] and cdi[i - 1] else 0)
    n = len(rf)
    if n < 40:
        return None
    mf, mi = sum(rf) / n, sum(ri) / n
    vf = math.sqrt(sum((x - mf) ** 2 for x in rf) / (n - 1))
    vi = math.sqrt(sum((x - mi) ** 2 for x in ri) / (n - 1))
    cov = sum((a - mf) * (b - mi) for a, b in zip(rf, ri)) / (n - 1)
    anos = (datas[idx[-1]] - datas[i0]).days / 365.25
    tot = cota[idx[-1]] / cota[i0]
    tot_c = cdi[idx[-1]] / cdi[i0] if cdi[i0] else None
    ret_a = tot ** (1 / anos) - 1 if anos > 0 else None
    cdi_a = tot_c ** (1 / anos) - 1 if tot_c and anos > 0 else None
    pico, dd, d_pico, d_fundo, d_pico_max = cota[i0], 0, datas[i0], datas[i0], datas[i0]
    for i in range(i0, idx[-1] + 1):
        if cota[i] > pico:
            pico, d_pico = cota[i], datas[i]
        x = cota[i] / pico - 1
        if x < dd:
            dd, d_fundo, d_pico_max = x, datas[i], d_pico
    neg = [x for x in rf if x < 0]
    vneg = math.sqrt(sum(x * x for x in neg) / len(neg)) * math.sqrt(252) if neg else None
    vol = vf * math.sqrt(252)
    return {
        'vol': vol * 100,
        'vol_ibov': vi * math.sqrt(252) * 100,
        'beta': cov / (vi * vi) if vi else None,
        'correl': cov / (vf * vi) if vf and vi else None,
        'ret_anual': ret_a * 100 if ret_a is not None else None,
        'cdi_anual': cdi_a * 100 if cdi_a is not None else None,
        'sharpe': (ret_a - cdi_a) / vol if ret_a is not None and cdi_a is not None and vol else None,
        'sortino': (ret_a - cdi_a) / vneg if ret_a is not None and cdi_a is not None and vneg else None,
        'drawdown': dd * 100, 'dd_pico': d_pico_max.isoformat(), 'dd_fundo': d_fundo.isoformat(),
        'dias_alta': sum(1 for x in rf if x > 0) / n * 100,
        'pior_dia': min(rf) * 100, 'melhor_dia': max(rf) * 100,
    }


def gera(fundos, S, IDX, ref, rows, pasta, baixa, dig):
    os.makedirs(pasta, exist_ok=True)
    alvo = {dig(f['cnpj']) for f in fundos}
    print('Cadastro e lâmina da CVM…')
    CAD = cadastro(alvo, baixa, dig)
    LAM = lamina(alvo, baixa, dig, ref)
    por_nome = {r[0]: r for r in rows}
    ibov, cdi = IDX.get('IBOV', {}), IDX.get('CDI', {})
    indice = []
    for f in fundos:
        c = dig(f['cnpj'])
        s = {dt.date.fromisoformat(d): v for d, v in S.get(c, {}).items()}
        datas = sorted(d for d in s if d <= ref and s[d][0])
        cota = [s[d][0] for d in datas]
        ib = _alinha(ibov, datas) if ibov else [None] * len(datas)
        cd = _alinha(cdi, datas) if cdi else [None] * len(datas)
        # mensal: retorno do fundo, Ibovespa e CDI, captação líquida, PL e cotistas no fim do mês
        mensal, ult = [], {}
        for i, d in enumerate(datas):
            ult[(d.year, d.month)] = i
        chaves = sorted(ult)
        for j, k in enumerate(chaves):
            i1 = ult[k]
            i0 = ult[chaves[j - 1]] if j > 0 else None
            capt = sum(v[2] - v[3] for d, v in s.items() if (d.year, d.month) == k)
            reg = {'m': f'{k[0]}-{k[1]:02d}', 'pl': s[datas[i1]][1], 'cotst': s[datas[i1]][4], 'capt': capt,
                   'parcial': datas[i1] == datas[-1] and datas[i1].month == ref.month and datas[i1] < ref.replace(day=28)}
            if i0 is not None:
                reg['ret'] = (cota[i1] / cota[i0] - 1) * 100
                reg['ibov'] = (ib[i1] / ib[i0] - 1) * 100 if ib[i1] and ib[i0] else None
                reg['cdi'] = (cd[i1] / cd[i0] - 1) * 100 if cd[i1] and cd[i0] else None
            mensal.append(reg)
        com = [x for x in mensal if 'ret' in x]
        u12 = com[-12:]
        ult_i = len(datas) - 1
        um_ano = ref.replace(year=ref.year - 1)
        risco = {}
        for nome, ini in (('12m', um_ano), ('36m', ref.replace(year=ref.year - 3)), ('60m', ref.replace(year=ref.year - 5))):
            try:
                if datas and datas[0] <= ini + dt.timedelta(days=10):
                    risco[nome] = _risco(datas, cota, ib, cd, ini)
            except Exception as e:
                print('aviso risco', c, e)
        cot_12 = next((s[d][4] for d in datas if d >= um_ano), None)
        resumo = {
            'pl': s[datas[-1]][1] if datas else None,
            'pl_max': max((s[d][1] or 0) for d in datas) if datas else None,
            'cotistas': s[datas[-1]][4] if datas else None,
            'cotistas_12m': cot_12,
            'capt_12m': sum(v[2] - v[3] for d, v in s.items() if um_ano < d <= ref),
            'capt_ano': sum(v[2] - v[3] for d, v in s.items() if d.year == ref.year and d <= ref),
            'melhor_mes': max(com, key=lambda x: x['ret'], default=None),
            'pior_mes': min(com, key=lambda x: x['ret'], default=None),
            'meses_acima_ibov': sum(1 for x in com if x.get('ibov') is not None and x['ret'] > x['ibov']),
            'meses_acima_cdi': sum(1 for x in com if x.get('cdi') is not None and x['ret'] > x['cdi']),
            'meses_positivos': sum(1 for x in com if x['ret'] > 0),
            'meses': len(com),
            'ret_historico': (cota[-1] / cota[0] - 1) * 100 if len(cota) > 1 else None,
            'inicio_historico': datas[0].isoformat() if datas else None,
            'ultima_cota': datas[-1].isoformat() if datas else None,
            'cota': cota[-1] if cota else None,
        }
        r = por_nome.get(f['nome'])
        ficha = {
            'nome': f['nome'], 'cnpj': c, 'nome_cvm': f.get('nome_cvm'), 'ref': ref.isoformat(),
            'linha': r, 'resumo': resumo, 'risco': risco, 'mensal': mensal,
            'cadastro': CAD.get(c, {}), 'lamina': LAM.get(c, {}),
            'serie': {'d': [d.isoformat() for d in datas], 'cota': [round(x, 8) for x in cota],
                      'ibov': [round(x, 2) if x else None for x in ib], 'cdi': [round(x, 8) if x else None for x in cd],
                      'pl': [round(s[d][1]) if s[d][1] else None for d in datas], 'cotst': [s[d][4] for d in datas]},
        }
        with open(os.path.join(pasta, f'{c}.json'), 'w', encoding='utf-8') as fh:
            json.dump(ficha, fh, ensure_ascii=False, separators=(',', ':'), default=str)
        indice.append(c)
    print(f'  fichas: {len(indice)} fundos')
