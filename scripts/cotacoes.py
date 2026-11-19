#!/usr/bin/env python3
"""Robô de cotações: busca no Yahoo Finance, a cada minuto, as cotações do dia (gráfico de 5 em 5 min)
de todos os ativos do painel e publica cotacoes.json no ramo 'cotacoes' (um único commit, sempre
substituído, para o repositório não crescer).

Roda em ciclos de ~40 min (o agendamento do GitHub dispara a cada 30 min e o ciclo novo substitui o antigo).
Em horário de pregão (seg-sex, 7h às 21h de Brasília) busca a cada 60 s; fora dele, a cada 5 min.
"""
import json, os, subprocess, sys, time, urllib.request, urllib.parse, http.cookiejar, threading, datetime as dt
from concurrent.futures import ThreadPoolExecutor

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIMB = [s.strip() for s in open(os.path.join(RAIZ, 'cotacoes', 'simbolos.txt')) if s.strip()]
DURACAO = int(os.environ.get('DURACAO_MIN', '40')) * 60
PASTA = os.environ.get('PASTA_PUBLICA', os.path.join(RAIZ, '_pub'))
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'}
META = ('symbol', 'currency', 'regularMarketPrice', 'chartPreviousClose', 'previousClose', 'regularMarketTime',
        'regularMarketDayHigh', 'regularMarketDayLow', 'regularMarketVolume', 'exchangeTimezoneName', 'gmtoffset')


# O Yahoo recusa (429) pedidos de servidores sem cookie de sessão; pegamos cookie + "crumb" como um navegador.
JAR = http.cookiejar.CookieJar()
OP = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(JAR))
SESS = {'crumb': None, 'at': 0}
LOCK = threading.Lock()
ERROS = {}


def abre(u, timeout=15):
    return OP.open(urllib.request.Request(u, headers=UA), timeout=timeout)


def sessao(forca=False):
    with LOCK:
        if SESS['crumb'] and not forca and time.time() - SESS['at'] < 3600:
            return SESS['crumb']
        for u in ('https://fc.yahoo.com', 'https://finance.yahoo.com/quote/%5EBVSP/'):
            try:
                abre(u, 10).read(1000)
            except Exception:
                pass  # fc.yahoo.com responde 404, mas entrega o cookie
        try:
            SESS['crumb'] = abre('https://query2.finance.yahoo.com/v1/test/getcrumb', 10).read().decode().strip() or None
        except Exception as e:
            SESS['crumb'] = None
            ERROS['crumb'] = repr(e)[:120]
        SESS['at'] = time.time()
        return SESS['crumb']


def busca(s):
    q = urllib.parse.quote(s)
    for tent in range(3):
        crumb = sessao(forca=tent == 2)
        h = 1 + tent % 2
        try:
            u = f'https://query{h}.finance.yahoo.com/v8/finance/chart/{q}?range=1d&interval=5m&includePrePost=false'
            if crumb:
                u += '&crumb=' + urllib.parse.quote(crumb)
            with abre(u) as r:
                res = json.load(r)['chart']['result'][0]
            m = {k: res['meta'].get(k) for k in META if res['meta'].get(k) is not None}
            c = (res.get('indicators', {}).get('quote') or [{}])[0].get('close') or []
            return s, {'m': m, 't': res.get('timestamp') or [], 'c': [round(x, 6) if x is not None else None for x in c]}
        except Exception as e:
            ERROS[s] = repr(e)[:120]
            time.sleep(0.5 + tent)
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
    ini = time.time()
    primeiro = subprocess.run(['git', '-C', PASTA, 'rev-parse', '--verify', 'HEAD'], capture_output=True).returncode != 0
    while True:
        t0 = time.time()
        with ThreadPoolExecutor(6) as ex:
            res = dict(ex.map(busca, SIMB))
        ok = {s: v for s, v in res.items() if v}
        ultimo.update(ok)
        agora = dt.datetime.now(dt.timezone.utc)
        dados = {'gerado_em': agora.strftime('%Y-%m-%dT%H:%M:%SZ'), 'ok': len(ok), 'total': len(SIMB),
                 'falhas': sorted(set(SIMB) - set(ok)), 'q': ultimo}
        try:
            publica(dados, primeiro)
            primeiro = False
            print(f'{agora:%H:%M:%S} {len(ok)}/{len(SIMB)} ok', ('erros: ' + str(list(ERROS.items())[:3])) if len(ok) < len(SIMB) else '', flush=True)
            ERROS.clear()
        except subprocess.CalledProcessError as e:
            print('aviso git', e.stderr.decode()[-300:], flush=True)
        passo = 60 if pregao(agora) else 300
        if time.time() - ini + passo > DURACAO:
            break
        time.sleep(max(5, passo - (time.time() - t0)))


if __name__ == '__main__':
    sys.exit(main())
