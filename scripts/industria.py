#!/usr/bin/env python3
"""Panorama da indústria de fundos e radar de concorrentes (dados abertos da CVM).

- data/industria.json: captação líquida e patrimônio por classe CVM, mês a mês (13 meses);
  maiores captações e resgates entre os fundos de ações no mês corrente e no anterior;
  posição do fundo de referência (alertas.json) no ranking de captação dos fundos de ações.
- data/radar.json: fundos de ações livres (ANBIMA) abertos ao público, com patrimônio relevante,
  que ainda não estão na lista de peers, com retorno no mês, no ano e em 12 meses.

Para não contar o mesmo dinheiro duas vezes (fundo que aplica em outro fundo), os totais por classe
somam só classes que NÃO são de cotas (Classe_Cotas = N). As listas de maiores captações mostram
fundos de cotas e fundos diretos, sem os "master" (nome com MASTER) e sem exclusivos.
"""
import csv, io, json, os, re, sys, zipfile, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from atualiza import baixa, so_digitos, meses_ate, CVM, CVM_HIST, RAIZ  # noqa: E402

CAD_175 = 'https://dados.cvm.gov.br/dados/FI/CAD/DADOS/registro_fundo_classe.zip'
HIST = os.path.join(RAIZ, 'data', 'industria_mensal.json')
SAIDA = os.path.join(RAIZ, 'data', 'industria.json')
RADAR = os.path.join(RAIZ, 'data', 'radar.json')
SET = json.load(open(os.path.join(RAIZ, 'alertas.json'), encoding='utf-8')).get('fundo_referencia')
ANBIMA_RADAR = ('Ações Livre', 'Ações Valor/Crescimento', 'Ações Valor / Crescimento', 'Ações Small Caps', 'Ações Dividendos')
PL_MIN_RADAR = 50e6
csv.field_size_limit(10 ** 8)


def cadastro():
    z = zipfile.ZipFile(io.BytesIO(baixa(CAD_175)))
    T = {n.lower(): n for n in z.namelist()}
    nome = next(v for k, v in T.items() if 'registro_classe' in k)
    out = {}
    with z.open(nome) as f:
        for r in csv.DictReader(io.TextIOWrapper(f, encoding='latin-1'), delimiter=';'):
            c = so_digitos(r.get('CNPJ_Classe'))
            out[c] = {'nome': (r.get('Denominacao_Social') or '').strip(), 'classe': (r.get('Classificacao') or 'Outros').strip() or 'Outros',
                      'anbima': (r.get('Classificacao_Anbima') or '').strip(), 'cotas': (r.get('Classe_Cotas') or '').strip(),
                      'exclusivo': (r.get('Exclusivo') or '').strip(), 'publico': (r.get('Publico_Alvo') or '').strip(),
                      'situacao': (r.get('Situacao') or '').strip()}
    return out


def le_mes(am):
    """Linhas do informe diário do mês: {cnpj: [(data, cota, pl, capt, resg)]} (só a classe, sem subclasses)."""
    z = baixa(CVM.format(am)) or baixa(CVM_HIST.format(am))
    if not z:
        return None
    S = {}
    with zipfile.ZipFile(io.BytesIO(z)) as zz:
        for n in zz.namelist():
            with zz.open(n) as f:
                rd = csv.reader(io.TextIOWrapper(f, encoding='latin-1', newline=''), delimiter=';')
                cab = [c.strip().upper() for c in next(rd)]
                ic = next(i for i, c in enumerate(cab) if c.startswith('CNPJ_FUNDO'))
                isub = cab.index('ID_SUBCLASSE') if 'ID_SUBCLASSE' in cab else None
                idt, iq, ipl, icap, ires = (cab.index(x) for x in ('DT_COMPTC', 'VL_QUOTA', 'VL_PATRIM_LIQ', 'CAPTC_DIA', 'RESG_DIA'))
                for r in rd:
                    if len(r) <= ires or (isub is not None and r[isub].strip()):
                        continue
                    try:
                        S.setdefault(so_digitos(r[ic]), []).append((r[idt][:10], float(r[iq] or 0), float(r[ipl] or 0), float(r[icap] or 0), float(r[ires] or 0)))
                    except ValueError:
                        pass
    for v in S.values():
        v.sort()
    return S


def agrega(S, CAD):
    """Totais do mês por classe (sem fundos de cotas) e captação líquida de cada fundo."""
    classes, por_fundo = {}, {}
    for c, L in S.items():
        info = CAD.get(c, {})
        capt = sum(x[3] - x[4] for x in L)
        pl = L[-1][2]
        por_fundo[c] = (capt, pl)
        if info.get('cotas') == 'S':
            continue
        k = info.get('classe') or 'Sem cadastro'
        d = classes.setdefault(k, {'capt': 0.0, 'pl': 0.0, 'n': 0})
        d['capt'] += capt
        d['pl'] += pl
        d['n'] += 1
    return {k: {x: round(v[x], 2) if x != 'n' else v[x] for x in v} for k, v in classes.items()}, por_fundo


def lista_top(por_fundo, CAD, n=15):
    elegiveis = [(c, v) for c, v in por_fundo.items()
                 if CAD.get(c, {}).get('classe') == 'Ações' and CAD[c].get('exclusivo') != 'S' and 'MASTER' not in CAD[c].get('nome', '').upper()]
    ordem = sorted(elegiveis, key=lambda x: x[1][0], reverse=True)
    item = lambda c, v, pos: {'cnpj': c, 'nome': CAD[c]['nome'], 'anbima': CAD[c].get('anbima'), 'capt': round(v[0], 2), 'pl': round(v[1], 2), 'pos': pos}
    top = [item(c, v, i + 1) for i, (c, v) in enumerate(ordem[:n])]
    fundo = [item(c, v, len(ordem) - i) for i, (c, v) in enumerate(reversed(ordem[-n:]))]
    set_pos = next((item(c, v, i + 1) for i, (c, v) in enumerate(ordem) if c == SET), None)
    return {'captacao': top, 'resgate': fundo, 'referencia': set_pos, 'total_fundos': len(ordem)}


def cota_em(L, lim):
    """Última cota com data <= lim (L ordenada)."""
    v = None
    for d, q, *_ in L:
        if d <= lim:
            v = q
        else:
            break
    return v


def main():
    hoje = dt.date.today()
    print('Cadastro da CVM…')
    CAD = cadastro()
    try:
        H = json.load(open(HIST, encoding='utf-8'))
    except Exception:
        H = {}
    meses = meses_ate(hoje, 14)
    recentes = set(meses[-2:])
    MES = {}
    for am in meses:
        if am in H and am not in recentes:
            continue
        S = le_mes(am)
        if S is None:
            print('  ', am, 'ainda não publicado')
            continue
        cl, pf = agrega(S, CAD)
        ult = max(L[-1][0] for L in S.values())
        H[am] = {'classes': cl, 'ate': ult}
        print('  ', am, len(S), 'fundos, até', ult)
        if am in recentes:          # só os 2 meses recentes ficam na memória (o resto vira total por classe)
            MES[am] = (S, pf)
        del S
    H = {k: H[k] for k in sorted(H)[-24:]}
    json.dump(H, open(HIST, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))

    pub = sorted(MES)
    if not pub:
        print('nenhum mês recente publicado'); return
    out = {'gerado_em': dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'mensal': H, 'tops': {}}
    for am in pub[-2:]:
        out['tops'][am] = lista_top(MES[am][1], CAD) | {'ate': H[am]['ate']}
    json.dump(out, open(SAIDA, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('OK industria.json')

    # ---------- radar de concorrentes ----------
    peers = {so_digitos(f['cnpj']) for f in json.load(open(os.path.join(RAIZ, 'fundos.json'), encoding='utf-8'))}
    am = pub[-1]
    S = MES[am][0]
    ref = H[am]['ate']
    ref_d = dt.date.fromisoformat(ref)
    # meses necessários: anterior (mês), dezembro passado (ano) e 12 meses atrás
    precisa = {f'{(ref_d.replace(day=1) - dt.timedelta(days=1)):%Y%m}', f'{ref_d.year - 1}12', f'{ref_d.year - 1}{ref_d.month:02d}'}
    extra = {}
    for x in sorted(precisa):
        extra[x] = MES[x][0] if x in MES else le_mes(x)
    for x in list(MES):
        if x != am and x not in precisa:
            MES.pop(x)
    def base(cnpj, am_base, dia):
        L = (extra.get(am_base) or {}).get(cnpj)
        return cota_em(L, dia) if L else None
    fim_mes_ant = (ref_d.replace(day=1) - dt.timedelta(days=1)).isoformat()
    fim_ano_ant = f'{ref_d.year - 1}-12-31'
    m12 = ref_d.replace(year=ref_d.year - 1).isoformat()
    radar = []
    for c, L in S.items():
        info = CAD.get(c)
        if not info or c in peers or info.get('exclusivo') == 'S' or 'MASTER' in info.get('nome', '').upper():
            continue
        if info.get('anbima') not in ANBIMA_RADAR or 'Profissional' in info.get('publico', ''):
            continue
        pl = L[-1][2]
        if pl < PL_MIN_RADAR or L[-1][0] < (ref_d - dt.timedelta(days=5)).isoformat():
            continue
        q = L[-1][1]
        r = lambda b: (q / b - 1) * 100 if b else None
        radar.append({'cnpj': c, 'nome': info['nome'], 'anbima': info['anbima'], 'publico': info['publico'], 'cotas': info['cotas'],
                      'pl': round(pl, 2), 'mes': r(base(c, fim_mes_ant[:7].replace('-', ''), fim_mes_ant)),
                      'ano': r(base(c, f'{ref_d.year - 1}12', fim_ano_ant)),
                      'm12': r(base(c, m12[:7].replace('-', ''), m12)),
                      'capt_mes': round(sum(x[3] - x[4] for x in L), 2)})
    radar.sort(key=lambda x: -x['pl'])
    json.dump({'gerado_em': out['gerado_em'], 'ref': ref, 'criterio': {'anbima': ANBIMA_RADAR, 'pl_min': PL_MIN_RADAR},
               'fundos': radar}, open(RADAR, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('OK radar.json', len(radar), 'fundos')


if __name__ == '__main__':
    sys.exit(main())
