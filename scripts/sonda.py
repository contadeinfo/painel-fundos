import asyncio, re
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(); pg=await b.new_page()
        reqs=[]
        def on(r):
            if r.resource_type in ('xhr','fetch'): reqs.append((r.method, r.url, r.post_data))
        pg.on('request', on)
        await pg.goto('https://arquivos.b3.com.br/bdi/', timeout=90000); await pg.wait_for_timeout(10000)
        for m,u,d in reqs: print('REQ', m, u[:200], (d or '')[:300])
        txt=await pg.inner_text('body'); print(txt[:2500].replace('\n',' | '))
        srcs=await pg.eval_on_selector_all('script[src]', 'e=>e.map(x=>x.src)')
        for s in srcs:
            if any(k in s for k in ('jquery','bootstrap','popper','picker')): continue
            r=await pg.request.get(s); t=await r.text(); print('JS', s, len(t))
            for m in sorted(set(re.findall(r'[A-Za-z]*(?:Lend|Empr|Loan)[A-Za-z]*', t)))[:40]: print('  ', m)
            for m in sorted(set(re.findall(r'["\'`][^"\'`]*(?:table|api|bdi)/[^"\'`]{0,100}', t)))[:30]: print('  path', m)
        # tenta clicar em algo com Empréstimo
        reqs.clear()
        for k in ['Empréstimo', 'Emprestimo', 'Clearing', 'Câmara']:
            try:
                await pg.get_by_text(k, exact=False).first.click(timeout=4000); await pg.wait_for_timeout(5000); print('clicou', k)
            except Exception as e: print('nao', k)
        for m,u,d in reqs: print('REQ2', m, u[:200], (d or '')[:300])
        txt=await pg.inner_text('body'); print(txt[:2500].replace('\n',' | '))
        await b.close()
asyncio.run(main())
