#!/usr/bin/env python3
"""Histórico completo do fundo de referência (alertas.json), desde o primeiro informe diário na CVM.

Lê os arquivos anuais (HIST) e mensais do informe diário da CVM só para o CNPJ de referência e guarda,
mês a mês: retorno, cota, patrimônio, cotistas e captação líquida. Junta Ibovespa (B3, com o Banco Central
de reserva) e CDI (Banco Central) do mesmo mês. Anos fechados ficam em cache (data/referencia/).
Saída: data/referencia.json
"""
import base64, json, os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from atualiza import baixa, filtra_zip, num, so_digitos, CVM, CVM_HIST, RAIZ  # noqa: E402

CFG = json.load(open(os.path.join(RAIZ, 'alertas.json'), encoding='utf-8'))
REF = so_digitos(CFG['fundo_referencia'])
PASTA = os.path.join(RAIZ, 'data', 'referencia')
SAIDA = os.path.join(RAIZ, 'data', 'referencia.json')


def jl(p, d):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return d


def linhas_ano(a, hoje):
    """Linhas diárias do fundo no ano a: arquivo anual (HIST) ou os 12 mensais."""
    arq = os.path.join(PASTA, f'cvm_{a}.json')
    fechado = a < hoje.year - 1 or (a == hoje.year - 1 and hoje.month > 2)
    if fechado and os.path.exists(arq):
        return jl(arq, [])
    L = []
    z = baixa(CVM_HIST.format(a)) if a <= 2020 else None
    if z:
        L = filtra_zip(z, {REF})
    else:
        for m in range(1, 13):
            if dt.date(a, m, 1) > hoje:
                break
            am = f'{a}{m:02d}'
            z = baixa(CVM.format(am)) or baixa(CVM_HIST.format(am))
            if z:
                L += filtra_zip(z, {REF})
    L = sorted({tuple(x[1:]) for x in L})
    os.makedirs(PASTA, exist_ok=True)
    json.dump(L, open(arq, 'w'), separators=(',', ':'))
    print('CVM', a, len(L), 'dias')
    return L


def ibov_mensal(ini, fim):
    """Fechamento mensal do Ibovespa: B3 (histórico anual do índice); reserva: Banco Central (SGS 7)."""
    out = {}
    # (a B3 não tem uma consulta pública estável do histórico do índice; fica o Banco Central)
    for a in []:
        try:
            q = base64.b64encode(json.dumps({"index": "IBOV", "language": "pt-br", "year": str(a)}).encode()).decode()
            j = json.loads(baixa('https://sistemaswebb3-listados.b3.com.br/indexStatisticsProxy/IndexCall/GetYearlyHistory/' + q))
            for r in j.get('results', []):
                for m in range(1, 13):
                    v = r.get(f'rateValue{m}')
                    if v:
                        out[f'{a}-{m:02d}'] = num(str(v).replace('.', '').replace(',', '.'))  # o último dia que aparece fica
        except Exception as e:
            print('aviso B3 IBOV', a, e)
    if len(out) < 12:
        a = ini
        while a <= fim:          # o Banco Central limita a série diária a 10 anos por consulta
            b = min(fim, dt.date(a.year + 5, a.month, 1))
            try:
                j = json.loads(baixa(f'https://api.bcb.gov.br/dados/serie/bcdata.sgs.7/dados?formato=json&dataInicial={a:%d/%m/%Y}&dataFinal={b:%d/%m/%Y}'))
                for x in j:
                    d = dt.datetime.strptime(x['data'], '%d/%m/%Y')
                    out[f'{d.year}-{d.month:02d}'] = float(x['valor'])
            except Exception as e:
                print('aviso BCB IBOV', a, e)
            a = b + dt.timedelta(days=1)
    print('Ibovespa:', len(out), 'meses')
    return out


def cdi_mensal(ini, fim):
    out = {}
    try:
        j = json.loads(baixa(f'https://api.bcb.gov.br/dados/serie/bcdata.sgs.4391/dados?formato=json&dataInicial={ini:%d/%m/%Y}&dataFinal={fim:%d/%m/%Y}'))
        for x in j:
            d = dt.datetime.strptime(x['data'], '%d/%m/%Y')
            out[f'{d.year}-{d.month:02d}'] = float(x['valor'])
    except Exception as e:
        print('aviso CDI', e)
    return out


def main():
    hoje = dt.date.today()
    dias = []
    for a in range(2000, hoje.year + 1):
        try:
            dias += [tuple(x) for x in linhas_ano(a, hoje)]
        except Exception as e:
            print('aviso CVM', a, e)
    if not dias:
        print('sem dados'); return
    dias.sort()
    mes = {}
    for d, q, pl, cap, res, cot in dias:
        q, pl = num(q), num(pl)
        if not q:
            continue
        k = d[:7]
        x = mes.setdefault(k, {'capt': 0.0})
        x.update(d=d, cota=q, pl=pl, cotst=num(cot) if cot else x.get('cotst'))
        x['capt'] += (num(cap) or 0) - (num(res) or 0)
    ks = sorted(mes)
    ini = dt.date.fromisoformat(mes[ks[0]]['d'])
    IB, CD = ibov_mensal(ini, hoje), cdi_mensal(ini, hoje)
    ibk = sorted(IB)
    serie = []
    for i, k in enumerate(ks):
        x = mes[k]
        ant = mes[ks[i - 1]] if i else None
        ret = (x['cota'] / ant['cota'] - 1) * 100 if ant else None
        j = ibk.index(k) if k in IB else -1
        ib = (IB[k] / IB[ibk[j - 1]] - 1) * 100 if j > 0 else None
        serie.append({'m': k, 'ate': x['d'], 'ret': round(ret, 4) if ret is not None else None, 'ibov': round(ib, 4) if ib is not None else None,
                      'cdi': CD.get(k), 'cota': x['cota'], 'pl': round(x['pl'] or 0, 2), 'cotst': x.get('cotst'), 'capt': round(x['capt'], 2)})
    out = {'gerado_em': dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'inicio': mes[ks[0]]['d'], 'ref': dias[-1][0], 'mensal': serie}
    json.dump(out, open(SAIDA, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('OK referencia:', len(serie), 'meses, de', ks[0], 'a', ks[-1], '| com Ibovespa:', sum(1 for s in serie if s['ibov'] is not None),
          '| com CDI:', sum(1 for s in serie if s['cdi'] is not None))


if __name__ == '__main__':
    sys.exit(main())
