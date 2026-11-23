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
                nm = next((v for kk, v in r.items() if kk and v and ('COTA' in kk.upper()) and (kk.upper().startswith('NM_') or 'DENOM' in kk.upper())), '')
                k = (q, nm.strip())
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
    # a CVM deixa posições em sigilo por até 90 dias: lemos os últimos 8 meses publicados e, para cada
    # fundo, ficamos com o mês mais recente em que as ações aparecem (e o anterior a ele, para comparar)
    meses, a, m = [], hoje.year, hoje.month
    for _ in range(10):
        meses.append(f'{a}{m:02d}')
        m -= 1
        if m == 0:
            a, m = a - 1, 12
    ultimo_pub = None
    LIDO, NOMES = {}, {}
    for am in meses:
        if len(LIDO) >= 8:
            break
        try:
            zb = baixa(URL.format(am))
        except Exception as e:
            print('aviso', am, e)
            zb = None
        if not zb:
            continue
        if ultimo_pub is None:
            ultimo_pub = am
            if old.get('competencia_arquivo') == am and old.get('fundos') and old.get('versao') == 2:
                print('CDA já processada:', am)
                return
        r, nomes, comp = le_cda(zb, alvo)
        del zb
        LIDO[am] = (r, comp)
        NOMES.update(nomes)
        print('CDA', am, comp, sum(1 for v in r.values() if v['pos']), 'fundos com ações abertas')
    if not LIDO:
        print('nenhuma CDA encontrada')
        return
    ordem = sorted(LIDO, reverse=True)
    res, consol = {}, {}
    for c, nome in alvo.items():
        abertos = [am for am in ordem if sum(LIDO[am][0].get(c, {}).get('pos', {}).values()) >= 30]
        am0 = abertos[0] if abertos else ordem[0]
        A = LIDO[am0][0].get(c, {})
        B = LIDO[abertos[1]][0].get(c, {}) if len(abertos) > 1 else {}
        pa, pb = A.get('pos', {}), B.get('pos', {})
        top = sorted(pa.items(), key=lambda x: -x[1])
        mud = sorted(((tk, pa.get(tk, 0) - pb.get(tk, 0)) for tk in set(pa) | set(pb)), key=lambda x: -abs(x[1]))
        res[c] = {'nome': nome, 'competencia': LIDO[am0][1], 'comparado_com': LIDO[abertos[1]][1] if len(abertos) > 1 else None,
                  'pl': A.get('pl'), 'sigilo': LIDO[ordem[0]][0].get(c, {}).get('sigilo'), 'via': A.get('via'),
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
        x['nome'] = NOMES.get(x['tk'], '')
        x.pop('soma')
        x['fundos'] = x['fundos'][:12]
    out = {'versao': 2, 'gerado_em': dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'competencia': LIDO[ordem[0]][1],
           'competencia_arquivo': ultimo_pub, 'meses_lidos': [LIDO[am][1] for am in ordem], 'fundos': res, 'consolidado': cons,
           'nomes': {tk: NOMES.get(tk, '') for f in res.values() for tk in [t['tk'] for t in f['top']] + [x['tk'] for x in cons]}}
    json.dump(out, open(SAIDA, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('OK carteiras', sum(1 for v in res.values() if v['n_acoes']), 'fundos com ações')


if __name__ == '__main__':
    sys.exit(main())
