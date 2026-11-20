import asyncio, re, json
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(); pg=await b.new_page()
        reqs=[]
        pg.on('request', lambda r: reqs.append((r.method, r.url, r.post_data)) if r.resource_type in ('xhr','fetch') else None)
        await pg.goto('https://arquivos.b3.com.br/bdi/', timeout=90000); await pg.wait_for_timeout(6000)
        r=await pg.request.get('https://arquivos.b3.com.br/bdi/table/classifications'); t=await r.text()
        print('CLASS', len(t)); 
        for m in re.finditer(r'.{0,200}(?:Lend|Empr|Loan|Aluguel).{0,300}', t, re.I): print('  ', m.group(0)[:500])
        print(t[:1500])
        reqs.clear()
        for k in ['Outros dados', 'Other data']:
            try: await pg.get_by_text(k, exact=True).first.click(timeout=4000); await pg.wait_for_timeout(4000); print('clicou', k); break
            except Exception: pass
        txt=await pg.inner_text('body'); print(txt[:2000].replace('\n',' | '))
        for k in ['Empréstimo', 'Lending', 'Securities Lending']:
            try: await pg.get_by_text(k, exact=False).first.click(timeout=4000); await pg.wait_for_timeout(8000); print('clicou', k); break
            except Exception: pass
        for m,u,d in reqs: print('REQ', m, u[:220], (d or '')[:400])
        txt=await pg.inner_text('body'); print(txt[:2000].replace('\n',' | '))
        await b.close()
asyncio.run(main())
