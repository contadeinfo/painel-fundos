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
            for k in ('dy', 'rent_pat', 'rent_ef', 'amort'):   # a CVM manda em fração (0,0069 = 0,69%)
                if h[k] is not None:
                    h[k] = round(h[k] * 100, 4)
            h['rend_cota'] = round(h['dy'] * h['vp'] / 100, 4) if h['dy'] is not None and h['vp'] else None
        u12 = [h for h in hist if h['d'] > (dt.date.fromisoformat(datas[-1]) - dt.timedelta(days=360)).isoformat()]
        rend12 = sum(h['rend_cota'] or 0 for h in u12) if u12 else None
        dy12_pat = sum(h['dy'] or 0 for h in u12) if u12 else None
        # composição do ativo (valores em R$ do ativo/passivo)
        compos = {}
        ATIVO = ['Disponibilidades', 'Titulos_Publicos', 'Titulos_Privados', 'Fundos_Renda_Fixa', 'Terrenos', 'Imoveis_Renda_Acabados', 'Imoveis_Renda_Construcao',
                 'Imoveis_Venda_Acabados', 'Imoveis_Venda_Construcao', 'Outros_Direitos_Reais', 'Acoes', 'Debentures', 'Bonus_Subscricao',
                 'Certificados_Deposito_Valores_Mobiliarios', 'Cedulas_Debentures', 'Fundo_Acoes', 'FIP', 'FII', 'FDIC', 'Outras_Cotas_FI', 'Notas_Promissorias',
                 'Acoes_Sociedades_Atividades_FII', 'Cotas_Sociedades_Atividades_FII', 'CEPAC', 'CRI', 'CRI_CRA', 'Letras_Hipotecarias', 'LCI', 'LCI_LCA', 'LIG',
                 'Outros_Valores_Mobliarios', 'Contas_Receber_Aluguel', 'Contas_Receber_Venda_Imoveis', 'Outros_Valores_Receber']
        for k in ATIVO:   # só as linhas de detalhe (os totais repetiriam valores)
            x = num(ap.get(k))
            if x and x > 0:
                compos[k] = x
        tot = sum(compos.values()) or None
        grupos = {'Imóveis': r'^(Terrenos|Imoveis_|Outros_Direitos_Reais|Acoes_Sociedades_Atividades_FII|Cotas_Sociedades_Atividades_FII|CEPAC)',
                  'CRI': r'^CRI', 'Cotas de FII': r'^FII$', 'LCI/LH/LIG': r'^(LCI|Letras_Hipotecarias|LIG)',
                  'Caixa e renda fixa': r'^(Disponibilidades|Titulos_Publicos|Titulos_Privados|Fundos_Renda_Fixa)',
                  'Aluguéis e vendas a receber': r'^(Contas_Receber|Outros_Valores_Receber)'}
        gr = {}
        for k, x in compos.items():
            alvo = next((nome for nome, rx in grupos.items() if re.search(rx, k)), 'Ações, debêntures e outros')
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
            'dy_mes_pat': hist[-1]['dy'] if hist else None, 'dy12_pat': round(dy12_pat, 3) if dy12_pat is not None else None, 'rend12': round(rend12, 4) if rend12 is not None else None,
            'ult_rend': hist[-1]['rend_cota'] if hist else None, 'composicao': gp,
            'taxa_adm_aa': round(txadm * 12 * 100, 3) if txadm is not None else None,
            'cotistas_12m': next((h['cotistas'] for h in hist if h['d'] >= (dt.date.fromisoformat(datas[-1]) - dt.timedelta(days=365)).isoformat()), None),
        }
        fundos[tk] = {'info': info, 'geral': limpa(geral), 'complemento': limpa(comp), 'ativo_passivo': limpa(ap), 'historico': hist}
        resumo.append(info)

    # ---- trimestral: imóveis (vacância, inadimplência), inquilinos, ativos financeiros e vencimento dos contratos
    def ultimo_por_cnpj(parte):
        out = {}
        for r in T.get(parte, []):
            c, d = cnpj_de(r), data_de(r)
            if c and d:
                out.setdefault(c, {}).setdefault(d, []).append(r)
        return {c: (max(ds), ds[max(ds)]) for c, ds in out.items()}
    IM, INQ, ATV, TC = (ultimo_por_cnpj(x) for x in ('imovel', 'imovel_renda_acabado_inquilino', 'ativo', 'complemento'))
    por_cnpj = {f['info']['cnpj']: f for f in fundos.values()}
    for c, F in por_cnpj.items():
        info = F['info']
        if c in IM:
            d, rows = IM[c]
            L = [{'nome': r.get('Nome_Imovel', '').strip(), 'classe': r.get('Classe', '').strip(), 'endereco': r.get('Endereco', '').strip(),
                  'area': num(r.get('Area')), 'unidades': num(r.get('Numero_Unidades')), 'vac': num(r.get('Percentual_Vacancia')),
                  'inad': num(r.get('Percentual_Inadimplencia')), 'receita': num(r.get('Percentual_Receitas_FII')),
                  'pct_inv': num(r.get('Percentual_Imovel_Total_Investido')), 'outras': (r.get('Outras_Caracteristicas_Relevantes') or '').strip()[:300]}
                 for r in rows]
            L = [x for x in L if x['nome'] or x['endereco']]
            # cada administrador informa de um jeito: fração (0,05) ou percentual (5). Se algum valor do fundo é
            # fração "quebrada" (entre 0 e 1), tratamos todos como fração; senão, como percentual.
            for campo in ('vac', 'inad', 'receita', 'pct_inv'):
                vals = [x[campo] for x in L if x[campo] is not None]
                fra = vals and max(vals) <= 1 and any(0 < v < 1 for v in vals)
                if fra:
                    for x in L:
                        if x[campo] is not None:
                            x[campo] = round(x[campo] * 100, 2)
            renda = [x for x in L if x['vac'] is not None and 'renda' in x['classe'].lower()] or [x for x in L if x['vac'] is not None]
            def media(campo):
                xs = [x for x in renda if x[campo] is not None]
                if not xs:
                    return None
                w = sum(x['area'] or 0 for x in xs)
                return round(sum(x[campo] * (x['area'] or 0) for x in xs) / w, 2) if w else round(sum(x[campo] for x in xs) / len(xs), 2)
            F['imoveis'] = {'ref': d, 'lista': sorted(L, key=lambda x: -(x['receita'] or x['pct_inv'] or 0))[:150]}
            info.update({'imoveis': len(L), 'vacancia': media('vac'), 'inadimplencia': media('inad'), 'area': round(sum(x['area'] or 0 for x in L)) or None})
        if c in INQ:
            d, rows = INQ[c]
            setores = {}
            for r in rows:
                v = num(r.get('Percentual_Receitas_FII')) or 0
                setores[(r.get('Setor_Atuacao') or 'Não informado').strip()] = setores.get((r.get('Setor_Atuacao') or 'Não informado').strip(), 0) + v
            tot = sum(setores.values()) or 1
            F['inquilinos'] = {'ref': d, 'setores': [[k, round(v / tot * 100, 1)] for k, v in sorted(setores.items(), key=lambda x: -x[1])[:12]], 'n': len(rows)}
        if c in ATV:
            d, rows = ATV[c]
            A = [{'tipo': (r.get('Tipo') or '').strip(), 'nome': (r.get('Nome_Ativo') or r.get('Emissor') or '').strip(), 'emissor': (r.get('Emissor') or '').strip(),
                  'codigo': (r.get('Codigo_Acao') or '').strip(), 'venc': (r.get('Data_Vencimento') or '')[:10], 'valor': num(r.get('Valor'))} for r in rows]
            A = [x for x in A if x['valor']]
            tot = sum(x['valor'] for x in A) or 1
            tipos = {}
            for x in A:
                tipos[x['tipo'] or 'Outros'] = tipos.get(x['tipo'] or 'Outros', 0) + x['valor']
            F['ativos'] = {'ref': d, 'top': [dict(x, pct=round(x['valor'] / tot * 100, 2)) for x in sorted(A, key=lambda x: -x['valor'])[:25]],
                           'por_tipo': [[k, round(v / tot * 100, 1)] for k, v in sorted(tipos.items(), key=lambda x: -x[1])], 'n': len(A)}
        if c in TC:
            d, rows = TC[c]
            r = rows[0]
            venc = [[k.split('Faixa_')[-1].replace('_', ' '), num(v)] for k, v in r.items() if k and k.startswith('Percentual_Vencimento_Receita_FII_Faixa') and num(v) is not None]
            if any(v for _, v in venc):
                fra = max(v for _, v in venc) <= 1.0001
                F['vencimentos'] = {'ref': d, 'faixas': [[k, round(v * 100 if fra else v, 2)] for k, v in venc]}
            F['trimestral'] = limpa(r)
        # segmento mais útil quando a CVM diz só "Multicategoria"/"Outros"
        seg = info['segmento']
        if seg in ('Multicategoria', 'Outros', 'Não informado', 'Híbrido', 'Títulos e Val. Mob.'):
            info['segmento_painel'] = {'Papel': 'Papel (CRI e recebíveis)', 'Fundo de fundos': 'Fundo de fundos', 'Tijolo': 'Tijolo multicategoria', 'Híbrido': 'Híbrido'}.get(info['tipo'], seg)
        else:
            info['segmento_painel'] = seg
    os.makedirs(PASTA, exist_ok=True)
    for tk, F in fundos.items():
        json.dump(F, open(os.path.join(PASTA, tk + '.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    resumo = [f['info'] for f in fundos.values()]
    json.dump({'gerado_em': dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'n': len(resumo), 'fundos': resumo},
              open(os.path.join(RAIZ, 'data', 'fii.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('OK fii.json', len(resumo), 'FIIs com ticker;', sum(1 for f in resumo if f.get('imoveis')), 'com imóveis')


if __name__ == '__main__':
    sys.exit(main())
