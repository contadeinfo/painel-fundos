#!/usr/bin/env python3
"""Robô espelho: abre o próprio painel num navegador (Chromium), passa por todas as abas e guarda
as respostas das fontes externas (Banco Central, Tesouro, IBGE, ANBIMA, B3/TradingView, notícias,
GDELT etc.). Publica tudo no ramo 'espelho'. O painel, ao abrir, lê primeiro do espelho.

O navegador do robô busca as fontes pelo próprio servidor do GitHub (sem a trava de CORS e sem
intermediários), então cada fonte é buscada uma vez para todos os usuários do painel.
"""
import asyncio, hashlib, json, os, re, subprocess, sys, time, datetime as dt, threading, http.server, functools

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA = os.environ.get('PASTA_PUBLICA', os.path.join(RAIZ, '_esp'))
DURACAO = int(os.environ.get('DURACAO_MIN', '50')) * 60
CICLO = int(os.environ.get('CICLO_MIN', '10')) * 60
VIEWS = ['inicio', 'mercado', 'contas', 'b3', 'fii', 'noticias', 'osint']
PASSA = ('raw.githubusercontent.com', 'cdnjs.cloudflare.com', 'cdn.jsdelivr.net', 'unpkg.com', 'economia.awesomeapi.com.br')
NAO = ('fonts.googleapis.com', 'fonts.gstatic.com', 'arcgisonline.com', 'basemaps', 'tile.', 'r.jina.ai')
PROXIES = [('https://api.allorigins.win/raw?url=', True), ('https://corsproxy.io/?url=', True),
           ('https://api.codetabs.com/v1/proxy/?quest=', True)]
CACHE_PARAM = re.compile(r'([?&])(t|_|ts|cb|nocache|rnd)=[^&#]*')
MAX_BYTES = 15 * 1024 * 1024


def desembrulha(u):
    from urllib.parse import unquote
    for pre, enc in PROXIES:
        if u.startswith(pre):
            return unquote(u[len(pre):]), True
    return u, False


def normaliza(u):
    u = CACHE_PARAM.sub(lambda m: m.group(1), u)
    u = re.sub(r'\?&+', '?', u)
    u = re.sub(r'&&+', '&', u)
    return re.sub(r'[?&]+$', '', u)


def fnv(s):
    h = 0x811c9dc5
    for b in s.encode('utf-8'):
        h ^= b
        h = (h * 0x01000193) & 0xffffffff
    return format(h, '08x')


def chave(metodo, url, corpo):
    return f'{metodo} {normaliza(url)}' + (f'\n{corpo}' if corpo else '')


def validade(u):
    """Por quanto tempo (min) o painel aceita a cópia; depois volta à fonte direta."""
    if 'scanner.tradingview.com' in u or 'cotacao.b3.com.br' in u:
        return 30
    if any(x in u for x in ('rss', 'feed', 'news.google', 'gdelt', '.xml')):
        return 45
    if 'yahoo' in u:
        return 30
    return 6 * 60


def servidor():
    pasta = os.path.join(RAIZ, 'painel')
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=pasta)
    h.log_message = lambda *a: None
    s = http.server.ThreadingHTTPServer(('127.0.0.1', 8799), h)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


async def ciclo(pw, indice):
    b = await pw.chromium.launch()
    ctx = await b.new_context(viewport={'width': 1400, 'height': 1000}, locale='pt-BR', timezone_id='America/Sao_Paulo')
    await ctx.add_init_script('window.__ESPELHO_OFF = true; window.__ROBO_OFF = true;')
    salvos, erros = 0, 0

    async def rota(route):
        nonlocal salvos, erros
        r = route.request
        u = r.url
        if u.startswith('http://127.0.0.1') or any(x in u for x in PASSA):
            return await route.continue_()
        if any(x in u for x in NAO):
            return await route.abort()
        if r.method not in ('GET', 'POST'):
            return await route.continue_()
        orig, via = desembrulha(u)
        try:
            resp = await route.fetch(timeout=40000)
            corpo = await resp.body()
            hd = {k: v for k, v in resp.headers.items() if k.lower() not in ('content-encoding', 'content-length', 'transfer-encoding')}
            hd['access-control-allow-origin'] = '*'
            await route.fulfill(status=resp.status, headers=hd, body=corpo)
            if resp.status == 200 and corpo and len(corpo) < MAX_BYTES and not (via and 'jina' in u):
                k = chave(r.method, orig, r.post_data or '')
                h = fnv(k)
                ct = resp.headers.get('content-type', 'application/octet-stream')
                if h not in indice or indice[h].get('sha') != hashlib.sha1(corpo).hexdigest():
                    with open(os.path.join(PASTA, 'f', h), 'wb') as f:
                        f.write(corpo)
                indice[h] = {'k': k[:300], 'ct': ct.split(';')[0], 'at': int(time.time()), 'max': validade(orig),
                             'sha': hashlib.sha1(corpo).hexdigest(), 'n': len(corpo)}
                salvos += 1
        except Exception:
            erros += 1
            try:
                await route.abort()
            except Exception:
                pass

    await ctx.route('**/*', rota)
    pg = await ctx.new_page()
    for v in VIEWS:
        try:
            await pg.goto(f'http://127.0.0.1:8799/painel.html#{v}', timeout=60000)
            await pg.wait_for_timeout(18000)
            if v == 'osint':
                for sel in ('[data-os="ua"]', '#osTabs button:nth-child(2)'):
                    try:
                        await pg.click(sel, timeout=2000)
                        await pg.wait_for_timeout(15000)
                        break
                    except Exception:
                        pass
        except Exception as e:
            print('aviso aba', v, repr(e)[:120], flush=True)
    await b.close()
    return salvos, erros


def publica(indice, primeiro):
    agora = int(time.time())
    for h in [h for h, v in indice.items() if agora - v['at'] > 3 * 86400]:   # some o que não aparece há 3 dias
        indice.pop(h)
        try:
            os.remove(os.path.join(PASTA, 'f', h))
        except FileNotFoundError:
            pass
    with open(os.path.join(PASTA, 'indice.json'), 'w') as f:
        json.dump({'gerado_em': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                   'i': {h: {x: v[x] for x in ('ct', 'at', 'max', 'sha')} for h, v in indice.items()}}, f, separators=(',', ':'))
    with open(os.path.join(PASTA, 'chaves.json'), 'w') as f:   # para conferência humana
        json.dump({h: [v['k'], v['n']] for h, v in indice.items()}, f, ensure_ascii=False, indent=0)
    g = lambda *a: subprocess.run(['git', '-C', PASTA, *a], check=True, capture_output=True)
    g('add', '-A')
    g('commit', '-q', '-m', 'espelho', *([] if primeiro else ['--amend']))
    g('push', '-q', '-f', 'origin', 'HEAD:espelho')


async def main():
    from playwright.async_api import async_playwright
    os.makedirs(os.path.join(PASTA, 'f'), exist_ok=True)
    indice = {}
    try:
        old = json.load(open(os.path.join(PASTA, 'indice.json')))['i']
        ch = json.load(open(os.path.join(PASTA, 'chaves.json')))
        indice = {h: {**v, 'k': ch.get(h, [''])[0], 'n': ch.get(h, ['', 0])[1]} for h, v in old.items()}
    except Exception:
        pass
    servidor()
    primeiro = subprocess.run(['git', '-C', PASTA, 'rev-parse', '--verify', 'HEAD'], capture_output=True).returncode != 0
    ini = time.time()
    async with async_playwright() as pw:
        while True:
            t0 = time.time()
            s, e = await ciclo(pw, indice)
            try:
                publica(indice, primeiro)
                primeiro = False
            except subprocess.CalledProcessError as x:
                print('aviso git', x.stderr.decode()[-300:], flush=True)
            print(f'{dt.datetime.now():%H:%M:%S} {s} respostas salvas, {e} falhas, {len(indice)} no índice ({time.time()-t0:.0f}s)', flush=True)
            if time.time() - ini + CICLO > DURACAO:
                break
            await asyncio.sleep(max(10, CICLO - (time.time() - t0)))


if __name__ == '__main__':
    asyncio.run(main())
