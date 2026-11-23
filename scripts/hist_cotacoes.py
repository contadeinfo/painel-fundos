#!/usr/bin/env python3
"""Histórico diário (10 anos) das cotações dos cartões do painel, para os gráficos de período longo.

O navegador nem sempre consegue buscar o histórico longo direto no Yahoo Finance (bloqueio e limite de tamanho
nos intermediários). O robô baixa aqui uma vez por dia e o painel lê o arquivo pronto.
Saída: data/hist/<símbolo>.json  →  {"s": símbolo, "d": [AAAA-MM-DD...], "c": [fechamento...]}
"""
import json, os, re, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from atualiza import baixa, RAIZ  # noqa: E402

SIMBOLOS = ['^BVSP', '^GSPC', '^IXIC', '^DJI', '^STOXX50E', '^FTSE', '^N225', '^VIX', 'BRL=X', 'EURBRL=X', 'BTC-USD', 'DX-Y.NYB',
            'EWZ', 'GC=F', 'BZ=F', 'CL=F', 'SI=F', 'HG=F', 'TIO=F', '^TNX', 'IFIX.SA', 'SMAL11.SA', 'BOVA11.SA']
PASTA = os.path.join(RAIZ, 'data', 'hist')
nome = lambda s: re.sub(r'[^A-Za-z0-9]+', '_', s).strip('_')


def baixa_serie(s):
    out = {}
    hoje = dt.date.today()
    a = dt.date(hoje.year - 10, hoje.month, 1)
    while a <= hoje:              # blocos de 3 anos: em intervalos longos o Yahoo devolve pontos semanais/mensais
        b = min(hoje + dt.timedelta(days=1), dt.date(a.year + 3, a.month, 1))
        p1 = int(dt.datetime(a.year, a.month, a.day, tzinfo=dt.timezone.utc).timestamp())
        p2 = int(dt.datetime(b.year, b.month, b.day, tzinfo=dt.timezone.utc).timestamp())
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{s.replace("^", "%5E").replace("=", "%3D")}?period1={p1}&period2={p2}&interval=1d'
        try:
            r = json.loads(baixa(url) or b'{}')['chart']['result'][0]
            q = r['indicators']['quote'][0]['close']
            off = (r.get('meta') or {}).get('gmtoffset') or 0
            for t, c in zip(r.get('timestamp') or [], q):
                if c is not None:
                    out[dt.datetime.utcfromtimestamp(t + off).date().isoformat()] = round(c, 6)
        except Exception as e:
            print('  aviso', s, a, e)
        a = b
    return out


def main():
    os.makedirs(PASTA, exist_ok=True)
    ok = 0
    for s in SIMBOLOS:
        D = baixa_serie(s)
        if len(D) < 50:
            print('sem histórico:', s, len(D)); continue
        ks = sorted(D)
        json.dump({'s': s, 'gerado_em': dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'd': ks, 'c': [D[k] for k in ks]},
                  open(os.path.join(PASTA, nome(s) + '.json'), 'w'), separators=(',', ':'))
        ok += 1
        print(s, len(ks), 'dias, de', ks[0], 'a', ks[-1])
    print('OK histórico:', ok, 'de', len(SIMBOLOS))


if __name__ == '__main__':
    sys.exit(main())
