import asyncio
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(); pg=await b.new_page()
        urls=[]
        pg.on('request', lambda r: urls.append((r.resource_type, r.url)))
        for u in ['https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/consultas/outros-servicos/emprestimo-de-ativos/',
                  'https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/consultas/outros-servicos/emprestimo-de-ativos/posicoes-em-aberto/']:
            urls.clear()
            try:
                await pg.goto(u, timeout=60000); await pg.wait_for_timeout(8000)
            except Exception as e: print('ERR', e)
            print('==', u, await pg.title())
            for t,x in urls:
                if t in ('xhr','fetch','document') or 'iframe' in t: print(t, x[:220])
            for f in pg.frames: print('frame', f.url[:200])
            txt=await pg.inner_text('body'); print(txt[:1500].replace('\n',' | '))
        await b.close()
asyncio.run(main())
