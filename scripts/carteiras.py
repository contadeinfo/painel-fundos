#!/usr/bin/env python3
"""Carteira dos peers (CDA da CVM): composição mensal de cada fundo da lista, olhando através dos
fundos de cotas até as ações do fundo "master". Compara com o mês anterior (entradas, saídas,
maiores aumentos e reduções) e consolida: quais ações aparecem em mais peers.

A CVM publica a CDA com atraso, e cada fundo pode manter posições em sigilo por até 90 dias
(às vezes mais); posições em sigilo não aparecem e o fundo fica marcado como "com sigilo".
Saída: data/carteiras.json
"""
import csv, io, json, os, sys, zipfile, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from atualiza import baixa, so_digitos, RAIZ  # noqa: E402

URL = 'https://dados.cvm.gov.br/dados/FI/DOC/CDA/DADOS/cda_fi_{}.zip'
SAIDA = os.path.join(RAIZ, 'data', 'carteiras.json')
csv.field_size_limit(10 ** 8)


def membros(z, tag):
    return [n for n in z.namelist() if tag in n.upper() and n.lower().endswith('.csv')]


def linhas(z, nome):
    with z.open(nome) as f:
        for r in csv.DictReader(io.TextIOWrapper(f, encoding='latin-1', newline=''), delimiter=';'):
            yield r


def cnpj_de(r, *cands):
    for c in cands:
        if r.get(c):
            return so_digitos(r[c])
    return None


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def le_cda(zb, alvo):
    z = zipfile.ZipFile(io.BytesIO(zb))
    b2 = membros(z, 'BLC_2')
    # 1) fundos investidos (até 3 níveis: FIC -> FIC -> master)
    cotas, conjunto = {}, set(alvo)
    for _ in range(3):
        novos = set()
        for n in b2:
            for r in linhas(z, n):
                c = cnpj_de(r, 'CNPJ_FUNDO_CLASSE', 'CNPJ_FUNDO')
                if c not in conjunto:
                    continue
                q = cnpj_de(r, 'CNPJ_FUNDO_CLASSE_COTA', 'CNPJ_FUNDO_COTA')
                if not q:
                    continue
                k = (q, r.get('NM_FUNDO_CLASSE_COTA') or r.get('NM_FUNDO_COTA') or '')
                cotas.setdefault(c, {})[k] = num(r.get('VL_MERC_POS_FINAL'))
                if q not in conjunto:
                    novos.add(q)
        if not novos:
            break
        conjunto |= novos
    # 2) ações (BLC_4) e patrimônio
    acoes, nomes, sigilo = {}, {}, set()
    for n in membros(z, 'BLC_4'):
        for r in linhas(z, n):
            c = cnpj_de(r, 'CNPJ_FUNDO_CLASSE', 'CNPJ_FUNDO')
            if c not in conjunto:
                continue
            tk = (r.get('CD_ATIVO') or '').strip()
            if not tk:
                continue
            acoes.setdefault(c, {})
            acoes[c][tk] = acoes[c].get(tk, 0) + num(r.get('VL_MERC_POS_FINAL'))
            nomes.setdefault(tk, (r.get('DS_ATIVO') or '').strip())
    for n in membros(z, 'CONFID'):
        for r in linhas(z, n):
            c = cnpj_de(r, 'CNPJ_FUNDO_CLASSE', 'CNPJ_FUNDO')
            if c in conjunto:
                sigilo.add(c)
    pl = {}
    for n in membros(z, '_PL'):
        for r in linhas(z, n):
            c = cnpj_de(r, 'CNPJ_FUNDO_CLASSE', 'CNPJ_FUNDO')
            if c in conjunto:
                pl[c] = num(r.get('VL_PATRIM_LIQ'))
    comp = None
    for n in membros(z, '_PL'):
        for r in linhas(z, n):
            comp = (r.get('DT_COMPTC') or '')[:10]
            break
        break

    def olha(c, peso, prof, acc, via):
        P = pl.get(c) or 0
        if P <= 0 or prof > 3:
            return
        for tk, v in acoes.get(c, {}).items():
            acc[tk] = acc.get(tk, 0) + peso * v / P
        for (q, nm), v in cotas.get(c, {}).items():
            if v > 0:
                via.append({'cnpj': q, 'nome': nm, 'pct': round(peso * v / P * 100, 2)})
                olha(q, peso * v / P, prof + 1, acc, via)

    out = {}
    for c in alvo:
        acc, via = {}, []
        olha(c, 1.0, 0, acc, via)
        tem_sigilo = c in sigilo or any(v['cnpj'] in sigilo for v in via)
        out[c] = {'pl': pl.get(c), 'pos': {tk: round(p * 100, 3) for tk, p in acc.items() if p > 0.0005},
                  'via': [v for v in via if v['pct'] >= 1][:6], 'sigilo': tem_sigilo}
    return out, nomes, comp


def main():
    fundos = json.load(open(os.path.join(RAIZ, 'fundos.json'), encoding='utf-8'))
    alvo = {so_digitos(f['cnpj']): f['nome'] for f in fundos}
    try:
        old = json.load(open(SAIDA, encoding='utf-8'))
    except Exception:
        old = {}
    hoje = dt.date.today()
    achados = []
    a, m = hoje.year, hoje.month
    for _ in range(8):
        am = f'{a}{m:02d}'
        if len(achados) < 2:
            try:
                zb = baixa(URL.format(am))
            except Exception as e:
                print('aviso', am, e)
                zb = None
            if zb:
                achados.append((am, zb))
                print('CDA', am, f'{len(zb) / 1e6:.0f} MB')
        m -= 1
        if m == 0:
            a, m = a - 1, 12
    if not achados:
        print('nenhuma CDA encontrada')
        return
    if old.get('competencia_arquivo') == achados[0][0] and old.get('fundos'):
        print('CDA já processada:', achados[0][0])
        return
    atual, nomes, comp = le_cda(achados[0][1], alvo)
    ant = le_cda(achados[1][1], alvo)[0] if len(achados) > 1 else {}
    del achados[1:]
    res, consol = {}, {}
    for c, nome in alvo.items():
        A, B = atual.get(c, {}), ant.get(c, {})
        pa, pb = A.get('pos', {}), B.get('pos', {})
        top = sorted(pa.items(), key=lambda x: -x[1])
        mud = sorted(((tk, pa.get(tk, 0) - pb.get(tk, 0)) for tk in set(pa) | set(pb)), key=lambda x: -abs(x[1]))
        res[c] = {'nome': nome, 'pl': A.get('pl'), 'sigilo': A.get('sigilo'), 'via': A.get('via'),
                  'n_acoes': len(pa), 'acoes_pct': round(sum(pa.values()), 2),
                  'top': [{'tk': tk, 'pct': p} for tk, p in top[:15]],
                  'entradas': [tk for tk in pa if tk not in pb and pa[tk] >= 0.5][:10] if pb else [],
                  'saidas': [tk for tk in pb if tk not in pa and pb[tk] >= 0.5][:10] if pb else [],
                  'mudancas': [{'tk': tk, 'dif': round(d, 2)} for tk, d in mud if abs(d) >= 0.5][:10] if pb else []}
        for tk, p in pa.items():
            d = consol.setdefault(tk, {'tk': tk, 'n': 0, 'soma': 0.0, 'fundos': []})
            d['n'] += 1
            d['soma'] += p
            d['fundos'].append(nome)
    cons = sorted(consol.values(), key=lambda x: (-x['n'], -x['soma']))[:40]
    for x in cons:
        x['media'] = round(x['soma'] / x['n'], 2)
        x['nome'] = nomes.get(x['tk'], '')
        x.pop('soma')
        x['fundos'] = x['fundos'][:12]
    out = {'gerado_em': dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'competencia': comp,
           'competencia_arquivo': achados[0][0], 'fundos': res, 'consolidado': cons,
           'nomes': {tk: nomes.get(tk, '') for f in res.values() for tk in [t['tk'] for t in f['top']]}}
    json.dump(out, open(SAIDA, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('OK carteiras', comp, sum(1 for v in res.values() if v['n_acoes']), 'fundos com ações')


if __name__ == '__main__':
    sys.exit(main())
