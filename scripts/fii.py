#!/usr/bin/env python3
"""Fundos imobiliários pela CVM (dados abertos).

Informe mensal (geral, complemento, ativo/passivo) e trimestral (imóveis) de todos os FIIs.
Saídas:
  data/fii.json            resumo de cada FII negociado em bolsa (um por ticker)
  data/fii/<TICKER>.json   ficha: cadastro completo, composição do ativo, imóveis, histórico mensal
"""
import csv, io, json, os, re, sys, zipfile, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from atualiza import baixa, so_digitos, RAIZ  # noqa: E402

MENSAL = 'https://dados.cvm.gov.br/dados/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{}.zip'
TRIM = 'https://dados.cvm.gov.br/dados/FII/DOC/INF_TRIMESTRAL/DADOS/inf_trimestral_fii_{}.zip'
PASTA = os.path.join(RAIZ, 'data', 'fii')
csv.field_size_limit(10 ** 8)


def tabelas(zb):
    z = zipfile.ZipFile(io.BytesIO(zb))
    out = {}
    for n in z.namelist():
        if not n.lower().endswith('.csv'):
            continue
        parte = re.sub(r'^.*?fii_?', '', n.lower().rsplit('/', 1)[-1]).replace('.csv', '')
        parte = re.sub(r'_?\d{4}$', '', parte) or 'principal'
        with z.open(n) as f:
            out[parte] = list(csv.DictReader(io.TextIOWrapper(f, encoding='latin-1', newline=''), delimiter=';'))
    return out


def col(row, *pedacos):
    """Primeira coluna cujo nome contém todos os pedaços (sem diferenciar maiúsculas)."""
    for k in row:
        kk = (k or '').lower()
        if all(p.lower() in kk for p in pedacos):
            return k
    return None


def num(v):
    try:
        return float(str(v).replace(',', '.'))
    except (TypeError, ValueError):
        return None


def limpa(d):
    return {k.strip(): v.strip() for k, v in d.items() if k and v not in (None, '') and str(v).strip() not in ('', 'N/A')}


def cnpj_de(r):
    k = col(r, 'cnpj_fundo') or col(r, 'cnpj')
    return so_digitos(r.get(k)) if k else None


def data_de(r):
    k = col(r, 'data_referencia') or col(r, 'data_refer')
    return (r.get(k) or '')[:10] if k else ''


def ticker(isin):
    isin = (isin or '').strip().upper()
    m = re.match(r'^BR([A-Z]{4})CTF', isin)
    return m.group(1) + '11' if m else None


def main():
    hoje = dt.date.today()
    anos = [hoje.year - 1, hoje.year]
    M = {}
    for a in anos:
        try:
            zb = baixa(MENSAL.format(a))
        except Exception as e:
            print('aviso mensal', a, e)
            zb = None
        if not zb:
            continue
        for parte, linhas in tabelas(zb).items():
            M.setdefault(parte, []).extend(linhas)
            if linhas:
                print('mensal', a, parte, len(linhas), 'colunas:', list(linhas[0].keys())[:60])
    T = {}
    for a in anos:
        try:
            zb = baixa(TRIM.format(a))
        except Exception as e:
            print('aviso trimestral', a, e)
            zb = None
        if not zb:
            continue
        for parte, linhas in tabelas(zb).items():
            T.setdefault(parte, []).extend(linhas)
            if linhas and a == anos[-1]:
                print('trimestral', a, parte, len(linhas), 'colunas:', list(linhas[0].keys())[:40])

    # ---- informe mensal: por CNPJ e mês
    por = {}   # cnpj -> data -> {parte: row}
    for parte, linhas in M.items():
        for r in linhas:
            c, d = cnpj_de(r), data_de(r)
            if c and d:
                por.setdefault(c, {}).setdefault(d, {})[parte] = r
    fundos, resumo = {}, []
    for c, meses in por.items():
        datas = sorted(meses)
        ult = meses[datas[-1]]
        geral = ult.get('geral') or next(iter(ult.values()))
        isin = geral.get(col(geral, 'isin') or '', '')
        tk = ticker(isin)
        if not tk:
            # às vezes o ISIN vem só num mês ou em outra tabela
            for d in reversed(datas):
                for r in meses[d].values():
                    k = col(r, 'isin')
                    if k and ticker(r.get(k)):
                        tk = ticker(r.get(k))
                        break
                if tk:
                    break
        if not tk:
            continue
        comp = ult.get('complemento') or {}
        ap = ult.get('ativo_passivo') or {}
        g = lambda r, *p: num(r.get(col(r, *p) or '', None))
        pl = g(comp, 'patrimonio_liquido')
        vp = g(comp, 'valor_patrimonial_cota')
        cot = g(comp, 'numero_cotistas') or g(comp, 'total_numero_cotistas')
        cotas = g(comp, 'cotas_emitidas') or g(geral, 'cotas_emitidas')
        txadm = g(comp, 'taxa_administracao')
        hist = []
        for d in datas[-24:]:
            cm = meses[d].get('complemento') or {}
            hist.append({'d': d, 'dy': g(cm, 'dividend_yield'), 'rent_pat': g(cm, 'rentabilidade_patrimonial'),
                         'rent_ef': g(cm, 'rentabilidade_efetiva'), 'pl': g(cm, 'patrimonio_liquido'),
                         'vp': g(cm, 'valor_patrimonial_cota'), 'cotistas': g(cm, 'numero_cotistas') or g(cm, 'total_numero_cotistas'),
                         'amort': g(cm, 'amortizacao')})
        # rendimento por cota estimado (DY do mês × valor patrimonial da cota)
        for h in hist:
            h['rend_cota'] = round(h['dy'] * h['vp'] / 100, 4) if h['dy'] is not None and h['vp'] else None
        u12 = [h for h in hist if h['d'] > (dt.date.fromisoformat(datas[-1]) - dt.timedelta(days=360)).isoformat()]
        rend12 = sum(h['rend_cota'] or 0 for h in u12) if u12 else None
        dy12_pat = sum(h['dy'] or 0 for h in u12) if u12 else None
        # composição do ativo (valores em R$ do ativo/passivo)
        compos = {}
        for k, v in ap.items():
            x = num(v)
            if x and x > 0 and k and not re.search(r'cnpj|data|total|passivo|pagar|distribuir|provis|obriga|outros_valores_pagar', k, re.I):
                compos[k] = x
        tot = sum(compos.values()) or None
        grupos = {'Imóveis': r'imove|terreno|direitos_bens|imovel', 'CRI': r'\bcri|certificado.*receb', 'Cotas de FII': r'fii|cotas.*fundo',
                  'LCI/LH/LIG': r'lci|lh\b|letras_hipot|lig', 'Caixa e renda fixa': r'disponib|titulos_pub|titulos_priv|fundos_renda_fixa|aplica|deposito|caixa|cdb|lca',
                  'Ações e outros': r'acoes|debent|outros|bonus|warrant|sociedade'}
        gr = {}
        for k, x in compos.items():
            alvo = next((nome for nome, rx in grupos.items() if re.search(rx, k, re.I)), 'Ações e outros')
            gr[alvo] = gr.get(alvo, 0) + x
        gp = {k: round(v / tot * 100, 1) for k, v in sorted(gr.items(), key=lambda x: -x[1])} if tot else {}
        tipo = None
        if gp:
            im, pa, fo = gp.get('Imóveis', 0), gp.get('CRI', 0) + gp.get('LCI/LH/LIG', 0), gp.get('Cotas de FII', 0)
            tipo = 'Tijolo' if im >= 60 else 'Papel' if pa >= 60 else 'Fundo de fundos' if fo >= 60 else 'Híbrido'
        segmento = geral.get(col(geral, 'segmento') or '', '') or 'Não informado'
        info = {
            'tk': tk, 'cnpj': c, 'nome': geral.get(col(geral, 'nome_fundo') or '', '') or '', 'isin': isin,
            'segmento': segmento.strip(), 'mandato': (geral.get(col(geral, 'mandato') or '', '') or '').strip(),
            'gestao': (geral.get(col(geral, 'tipo_gestao') or '', '') or '').strip(), 'tipo': tipo,
            'publico': (geral.get(col(geral, 'publico_alvo') or '', '') or '').strip(),
            'admin': (geral.get(col(geral, 'nome_administrador') or '', '') or '').strip(),
            'ref': datas[-1], 'pl': pl, 'vp': vp, 'cotistas': cot, 'cotas': cotas, 'taxa_adm': txadm,
            'dy_mes_pat': hist[-1]['dy'] if hist else None, 'dy12_pat': dy12_pat, 'rend12': rend12,
            'ult_rend': hist[-1]['rend_cota'] if hist else None, 'composicao': gp,
        }
        fundos[tk] = {'info': info, 'geral': limpa(geral), 'complemento': limpa(comp), 'ativo_passivo': limpa(ap), 'historico': hist}
        resumo.append(info)

    # ---- trimestral: imóveis (vacância, inadimplência, área)
    imov = {}
    for parte, linhas in T.items():
        if 'imovel' not in parte and 'imoveis' not in parte:
            continue
        for r in linhas:
            c, d = cnpj_de(r), data_de(r)
            if c and d:
                imov.setdefault(c, {}).setdefault(d, []).append((parte, r))
    por_cnpj = {f['info']['cnpj']: f for f in fundos.values()}
    for c, ds in imov.items():
        F = por_cnpj.get(c)
        if not F:
            continue
        d = max(ds)
        L = []
        for parte, r in ds[d]:
            L.append({'classe': parte, 'nome': r.get(col(r, 'nome_imovel') or col(r, 'nome') or '', ''), 'endereco': r.get(col(r, 'endereco') or '', ''),
                      'area': num(r.get(col(r, 'area') or '', None)), 'vac': num(r.get(col(r, 'vacancia') or '', None)),
                      'inad': num(r.get(col(r, 'inadimplencia') or '', None)), 'receita': num(r.get(col(r, 'percentual_receita') or col(r, 'receitas') or '', None)),
                      'unidades': num(r.get(col(r, 'unidades') or '', None)), 'outras': r.get(col(r, 'outras_caracteristicas') or '', '')})
        L = [x for x in L if x['nome']]
        renda = [x for x in L if x['vac'] is not None]
        def media(campo):
            xs = [x for x in renda if x[campo] is not None]
            if not xs:
                return None
            w = sum(x['area'] or 0 for x in xs)
            return sum(x[campo] * (x['area'] or 0) for x in xs) / w if w else sum(x[campo] for x in xs) / len(xs)
        vac, inad = media('vac'), media('inad')
        # a CVM manda vacância às vezes em fração (0,05) e às vezes em % (5): normaliza para %
        norm = lambda v: None if v is None else v * 100 if v <= 1 and any((x['vac'] or 0) <= 1 for x in renda) else v
        F['imoveis'] = {'ref': d, 'lista': L[:200]}
        F['info'].update({'imoveis': len(L), 'vacancia': norm(vac), 'inadimplencia': norm(inad), 'area': sum(x['area'] or 0 for x in L) or None})
    os.makedirs(PASTA, exist_ok=True)
    for tk, F in fundos.items():
        json.dump(F, open(os.path.join(PASTA, tk + '.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    resumo = [f['info'] for f in fundos.values()]
    json.dump({'gerado_em': dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'n': len(resumo), 'fundos': resumo},
              open(os.path.join(RAIZ, 'data', 'fii.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('OK fii.json', len(resumo), 'FIIs com ticker;', sum(1 for f in resumo if f.get('imoveis')), 'com imóveis')


if __name__ == '__main__':
    sys.exit(main())
