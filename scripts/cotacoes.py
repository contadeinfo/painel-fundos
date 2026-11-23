#!/usr/bin/env python3
"""Robô de cotações: a cada minuto (em pregão) publica cotacoes.json no ramo 'cotacoes'.

Fonte principal: TradingView (scanner público, sem login), que aceita pedidos de servidores.
O Yahoo Finance recusa quase todos os pedidos vindos do GitHub, então só é usado para
completar o gráfico do dia no começo de cada ciclo, quando responde.

O arquivo sai no mesmo formato do Yahoo (meta + timestamp + close) para o painel ler igual.
O gráfico do dia é montado pelo próprio robô, um ponto a cada 5 minutos.
"""
import json, os, subprocess, sys, time, urllib.request, urllib.parse, datetime as dt

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIMB = [s.strip() for s in open(os.path.join(RAIZ, 'cotacoes', 'simbolos.txt')) if s.strip()]
DURACAO = int(os.environ.get('DURACAO_MIN', '40')) * 60
PASTA = os.environ.get('PASTA_PUBLICA', os.path.join(RAIZ, '_pub'))
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'}

# símbolo do Yahoo (usado no painel) -> símbolo no TradingView
TV = {
    '^BVSP': 'BMFBOVESPA:IBOV', '^GSPC': 'SP:SPX', '^IXIC': 'NASDAQ:IXIC', '^DJI': 'DJ:DJI',
    '^STOXX50E': 'TVC:SX5E', '^FTSE': 'TVC:UKX', '^N225': 'TVC:NI225', '^VIX': 'CBOE:VIX',
    'BRL=X': 'FX_IDC:USDBRL', 'EURBRL=X': 'FX_IDC:EURBRL', 'DX-Y.NYB': 'TVC:DXY',
    'BZ=F': 'ICEEUR:BRN1!', 'CL=F': 'NYMEX:CL1!', 'GC=F': 'COMEX:GC1!', 'BTC-USD': 'BITSTAMP:BTCUSD',
    'EWZ': 'AMEX:EWZ', '^TNX': 'TVC:US10Y', '^FVX': 'TVC:US05Y', '^IRX': 'TVC:US03MY', '^TYX': 'TVC:US30Y',
    'CLP=X': 'FX_IDC:USDCLP', 'COP=X': 'FX_IDC:USDCOP', 'IDR=X': 'FX_IDC:USDIDR', 'INR=X': 'FX_IDC:USDINR',
    'MXN=X': 'FX_IDC:USDMXN', 'TRY=X': 'FX_IDC:USDTRY', 'ZAR=X': 'FX_IDC:USDZAR',
}
for s in SIMB:
    if s.endswith('.SA'):
        TV[s] = 'BMFBOVESPA:' + s[:-3]
MERCADO = lambda t: ('brazil' if t.startswith('BMFBOVESPA') else 'forex' if t.startswith('FX_IDC') else
                     'crypto' if t.startswith('BITSTAMP') else 'cfd' if t.startswith('TVC') else
                     'futures' if t.split(':')[0] in ('ICEEUR', 'NYMEX', 'COMEX') else 'america')
COLS = ['close', 'change', 'change_abs', 'high', 'low', 'volume', 'update_mode', 'currency']
SERIE = lambda s: not s.endswith('.SA')   # gráfico do dia só para os cartões (ações da B3 só precisam do preço)


def post(url, corpo):
    req = urllib.request.Request(url, data=json.dumps(corpo).encode(), headers={**UA, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def tradingview():
    por_mercado = {}
    for s in SIMB:
        if s in TV:
            por_mercado.setdefault(MERCADO(TV[s]), []).append(TV[s])
    out, erros = {}, []
    for mk, tks in por_mercado.items():
        try:
            j = post(f'https://scanner.tradingview.com/{mk}/scan', {'symbols': {'tickers': tks}, 'columns': COLS})
            for row in j.get('data', []):
                out[row['s']] = dict(zip(COLS, row['d']))
        except Exception as e:
            erros.append(f'{mk}: {e!r}'[:120])
    falta = [t for tks in por_mercado.values() for t in tks if t not in out]
    for mk in ('bond', 'global'):   # juros americanos e outros que não estão no mercado esperado
        if not falta:
            break
        try:
            j = post(f'https://scanner.tradingview.com/{mk}/scan', {'symbols': {'tickers': falta}, 'columns': COLS})
            for row in j.get('data', []):
                out[row['s']] = dict(zip(COLS, row['d']))
        except Exception as e:
            erros.append(f'{mk}: {e!r}'[:120])
        falta = [t for t in falta if t not in out]
    return out, erros


# O fechamento anterior do dólar (FX_IDC:USDBRL) vem errado no TradingView (variação de +2% em dia de +0,3%).
# Para o dólar o robô publica só o preço; a variação do dia o painel pega direto da AwesomeAPI.
# (A AwesomeAPI recusa pedidos vindos do GitHub com erro 429, por isso não é usada aqui.)
SEM_VARIACAO = {'BRL=X'}


MESCOD = {'F': 1, 'G': 2, 'H': 3, 'J': 4, 'K': 5, 'M': 6, 'N': 7, 'Q': 8, 'U': 9, 'V': 10, 'X': 11, 'Z': 12}


def curva_di():
    """Curva de juros futuros (DI1 na B3) pelo TradingView: taxa atual, há 1 semana e há 1 mês."""
    y = dt.date.today().year
    tks = [f'BMFBOVESPA:DI1{c}{a}' for a in range(y, y + 12) for c in ('F', 'N')]
    for mk, cols in [(m, c) for m in ('futures', 'brazil', 'global') for c in (['close', 'Perf.W', 'Perf.1M', 'change'], ['close', 'change'])]:
        try:
            j = post(f'https://scanner.tradingview.com/{mk}/scan', {'symbols': {'tickers': tks}, 'columns': cols})
            out = []
            for r in j.get('data', []):
                d = dict(zip(cols, r['d']))
                cod = r['s'].split('DI1')[-1]
                if d.get('close') is None:
                    continue
                venc = f'{cod[1:]}-{MESCOD[cod[0]]:02d}'
                tx = float(d['close'])
                f = lambda p: round(tx / (1 + p / 100), 4) if p is not None else None
                out.append({'venc': venc, 'taxa': tx, 'semana': f(d.get('Perf.W')), 'mes': f(d.get('Perf.1M')),
                            'ontem': f(d.get('change'))})
            if out:
                return sorted(out, key=lambda x: x['venc'])
        except Exception:
            continue
    return None


def yahoo_dia(s):
    """Gráfico de 5 em 5 min do Yahoo (quando o Yahoo aceita)."""
    try:
        u = f'https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(s)}?range=1d&interval=5m&includePrePost=false'
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=10) as r:
            res = json.load(r)['chart']['result'][0]
        c = (res.get('indicators', {}).get('quote') or [{}])[0].get('close') or []
        return [[t, round(x, 6)] for t, x in zip(res.get('timestamp') or [], c) if x is not None]
    except Exception:
        return None


def pregao(agora):
    """Horário em que o painel costuma ser usado: dias úteis, 9h às 19h de Brasília."""
    brt = agora - dt.timedelta(hours=3)
    return brt.weekday() < 5 and 9 <= brt.hour < 19


def publica(dados, primeiro):
    with open(os.path.join(PASTA, 'cotacoes.json'), 'w') as f:
        json.dump(dados, f, separators=(',', ':'))
    g = lambda *a: subprocess.run(['git', '-C', PASTA, *a], check=True, capture_output=True)
    g('add', 'cotacoes.json')
    g('commit', '-q', '-m', 'cotações ' + dados['gerado_em'], *([] if primeiro else ['--amend']))
    g('push', '-q', '-f', 'origin', 'HEAD:cotacoes')


def main():
    os.makedirs(PASTA, exist_ok=True)
    try:  # continua o arquivo publicado: séries do dia e último valor de cada ativo
        Q = json.load(open(os.path.join(PASTA, 'cotacoes.json'))).get('q', {})
    except Exception:
        Q = {}
    ESTADO = {s: {'serie': [[t, c] for t, c in zip(v.get('t', []), v.get('c', [])) if c is not None],
                  'mudou': v.get('m', {}).get('regularMarketTime'), 'prev': v.get('m', {}).get('chartPreviousClose')}
              for s, v in Q.items()}
    tentou_yahoo = False
    di = None
    ini = time.time()
    primeiro = subprocess.run(['git', '-C', PASTA, 'rev-parse', '--verify', 'HEAD'], capture_output=True).returncode != 0
    while True:
        t0 = time.time()
        agora = int(t0)
        tv, erros = tradingview()
        aw = {}
        ok = 0
        for s in SIMB:
            d = aw.get(s) or tv.get(TV.get(s, ''))
            if not d or d.get('close') is None:
                continue
            ok += 1
            px = float(d['close'])
            prev = px - float(d['change_abs']) if d.get('change_abs') is not None and s not in SEM_VARIACAO else None
            atraso = 0
            um = str(d.get('update_mode') or '')
            if um.startswith('delayed_streaming_'):
                atraso = int(um.rsplit('_', 1)[-1] or 0)
            e = ESTADO.setdefault(s, {'serie': [], 'mudou': None, 'prev': None})
            tol = 3e-3 if s in aw else 1e-9   # na AwesomeAPI o fechamento anterior é recalculado pelo % (arredondado)
            novo_dia = prev is not None and e['prev'] is not None and abs(prev - e['prev']) > tol * max(1, abs(prev))
            parado = e['serie'] and agora - e['serie'][-1][0] > 6 * 3600 and (ult_px := e['serie'][-1][1]) != round(px, 6)
            if novo_dia or parado:
                e['serie'] = []          # novo pregão: recomeça o gráfico do dia
            ult = e['serie'][-1][1] if e['serie'] else None
            if d.get('ts'):
                e['mudou'] = d['ts']
            elif ult is None or abs(px - ult) > 1e-12 or not e['mudou']:
                e['mudou'] = agora - atraso   # hora (aproximada) do último negócio
            e['prev'] = prev
            if SERIE(s):
                if e['serie'] and agora - e['serie'][-1][0] < 300:
                    e['serie'][-1][1] = round(px, 6)
                else:
                    e['serie'].append([agora, round(px, 6)])
                e['serie'] = e['serie'][-200:]
            Q[s] = {'m': {'symbol': s, 'regularMarketPrice': px, 'chartPreviousClose': prev,
                          'regularMarketTime': e['mudou'], 'regularMarketDayHigh': d.get('high'),
                          'regularMarketDayLow': d.get('low'), 'regularMarketVolume': d.get('volume'),
                          'currency': d.get('currency'), 'atraso_s': atraso, 'fonte': 'AwesomeAPI' if s in aw else 'TradingView'},
                    't': [p[0] for p in e['serie']], 'c': [p[1] for p in e['serie']]}
        if not tentou_yahoo:   # uma vez por ciclo: completa o gráfico do dia com o Yahoo, se ele deixar
            tentou_yahoo = True
            for s in [x for x in SIMB if SERIE(x)]:
                pts = yahoo_dia(s)
                if pts and s in Q and len(pts) > len(Q[s]['t']):
                    ESTADO[s]['serie'] = pts[-199:] + ([[agora, Q[s]['m']['regularMarketPrice']]] if pts[-1][0] < agora - 300 else [])
                    Q[s]['t'] = [p[0] for p in ESTADO[s]['serie']]; Q[s]['c'] = [p[1] for p in ESTADO[s]['serie']]
        try:
            di = curva_di() or di
        except Exception:
            pass
        now = dt.datetime.now(dt.timezone.utc)
        dados = {'di': di, 'gerado_em': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'ok': ok, 'total': len(SIMB),
                 'falhas': sorted(s for s in SIMB if not (aw.get(s) or tv.get(TV.get(s, '')))), 'q': Q}
        try:
            publica(dados, primeiro)
            primeiro = False
            print(f'{now:%H:%M:%S} {ok}/{len(SIMB)} ok', erros[:3] or '', dados['falhas'][:8] or '', flush=True)
        except subprocess.CalledProcessError as e:
            print('aviso git', e.stderr.decode()[-300:], flush=True)
        if not pregao(now):
            break            # fora do horário: uma foto só por rodada (o agendamento é de hora em hora)
        passo = 60
        if time.time() - ini + passo > DURACAO:
            break
        time.sleep(max(5, passo - (time.time() - t0)))


if __name__ == '__main__':
    sys.exit(main())
