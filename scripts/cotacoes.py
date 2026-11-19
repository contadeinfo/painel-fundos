#!/usr/bin/env python3
"""Robô de cotações: busca no Yahoo Finance, a cada minuto, as cotações do dia (gráfico de 5 em 5 min)
de todos os ativos do painel e publica cotacoes.json no ramo 'cotacoes' (um único commit, sempre
substituído, para o repositório não crescer).

Roda em ciclos de ~40 min (o agendamento do GitHub dispara a cada 30 min e o ciclo novo substitui o antigo).
Em horário de pregão (seg-sex, 7h às 21h de Brasília) busca a cada 60 s; fora dele, a cada 5 min.
"""
import json, os, subprocess, sys, time, urllib.request, urllib.parse, datetime as dt
from concurrent.futures import ThreadPoolExecutor

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIMB = [s.strip() for s in open(os.path.join(RAIZ, 'cotacoes', 'simbolos.txt')) if s.strip()]
DURACAO = int(os.environ.get('DURACAO_MIN', '40')) * 60
PASTA = os.environ.get('PASTA_PUBLICA', os.path.join(RAIZ, '_pub'))
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'}
META = ('symbol', 'currency', 'regularMarketPrice', 'chartPreviousClose', 'previousClose', 'regularMarketTime',
        'regularMarketDayHigh', 'regularMarketDayLow', 'regularMarketVolume', 'exchangeTimezoneName', 'gmtoffset')


def busca(s):
    q = urllib.parse.quote(s)
    for h in (1, 2):
        try:
            u = f'https://query{h}.finance.yahoo.com/v8/finance/chart/{q}?range=1d&interval=5m&includePrePost=false'
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=15) as r:
                res = json.load(r)['chart']['result'][0]
            m = {k: res['meta'].get(k) for k in META if res['meta'].get(k) is not None}
            c = (res.get('indicators', {}).get('quote') or [{}])[0].get('close') or []
            return s, {'m': m, 't': res.get('timestamp') or [], 'c': [round(x, 6) if x is not None else None for x in c]}
        except Exception as e:
            err = e
    return s, None


def pregao(agora):
    brt = agora - dt.timedelta(hours=3)
    return brt.weekday() < 5 and 7 <= brt.hour < 21


def publica(dados, primeiro):
    with open(os.path.join(PASTA, 'cotacoes.json'), 'w') as f:
        json.dump(dados, f, separators=(',', ':'))
    g = lambda *a: subprocess.run(['git', '-C', PASTA, *a], check=True, capture_output=True)
    g('add', 'cotacoes.json')
    g('commit', '-q', '-m', 'cotações ' + dados['gerado_em'], *([] if primeiro else ['--amend']))
    g('push', '-q', '-f', 'origin', 'HEAD:cotacoes')


def main():
    os.makedirs(PASTA, exist_ok=True)
    ultimo = {}
    try:  # parte do último arquivo publicado, para nenhum ativo sumir se a fonte falhar
        ultimo = json.load(open(os.path.join(PASTA, 'cotacoes.json'))).get('q', {})
    except Exception:
        pass
    ini, primeiro = time.time(), True
    while True:
        t0 = time.time()
        with ThreadPoolExecutor(12) as ex:
            res = dict(ex.map(busca, SIMB))
        ok = {s: v for s, v in res.items() if v}
        ultimo.update(ok)
        agora = dt.datetime.now(dt.timezone.utc)
        dados = {'gerado_em': agora.strftime('%Y-%m-%dT%H:%M:%SZ'), 'ok': len(ok), 'total': len(SIMB),
                 'falhas': sorted(set(SIMB) - set(ok)), 'q': ultimo}
        try:
            publica(dados, primeiro)
            primeiro = False
            print(f'{agora:%H:%M:%S} {len(ok)}/{len(SIMB)} ok', flush=True)
        except subprocess.CalledProcessError as e:
            print('aviso git', e.stderr.decode()[-300:], flush=True)
        passo = 60 if pregao(agora) else 300
        if time.time() - ini + passo > DURACAO:
            break
        time.sleep(max(5, passo - (time.time() - t0)))


if __name__ == '__main__':
    sys.exit(main())
