import asyncio, re, json
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(); pg=await b.new_page()
        reqs=[]
        pg.on('request', lambda r: reqs.append((r.method, r.url, r.post_data, dict(r.headers))) if r.resource_type in ('xhr','fetch') else None)
        await pg.goto('https://arquivos.b3.com.br/bdi/', timeout=90000); await pg.wait_for_timeout(5000)
        await pg.get_by_text('Other data', exact=True).first.click(); await pg.wait_for_timeout(2000)
        await pg.get_by_text('Securities lending', exact=True).first.click(); await pg.wait_for_timeout(3000)
        reqs.clear()
        sel=await pg.query_selector_all('select')
        print('selects', len(sel))
        done=False
        for s in sel:
            opts=await s.eval_on_selector_all('option', 'o=>o.map(x=>[x.value,x.textContent])'); print(opts)
            for v,t in opts:
                if 'Open' in t: await s.select_option(v); done=True; break
        if not done:
            try: await pg.get_by_text('Select a table').first.click(timeout=3000); await pg.wait_for_timeout(1000); await pg.get_by_text('Open positions', exact=True).first.click(timeout=3000)
            except Exception as e: print('erro select', e)
        await pg.wait_for_timeout(8000)
        for m,u,d,h in reqs: print('REQ', m, u[:250], (d or '')[:600], {k:v for k,v in h.items() if k.lower() in ('content-type','authorization','x-token','token')})
        txt=await pg.inner_text('body'); print(txt[:3000].replace('\n',' | '))
        await b.close()
asyncio.run(main())
