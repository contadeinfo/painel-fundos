#!/usr/bin/env python3
"""Avisos por e-mail: o robô abre uma "issue" no repositório marcando @dono; o GitHub manda e-mail.

Modo 'completo' (depois da atualização dos peers): Set mudou de quartil, resgate/captação forte de
peer, resgate forte no Set, concorrente novo no radar e, de manhã, o resumo diário.
Modo 'mercado' (durante o pregão): dólar acima/abaixo de um valor e Ibovespa com variação forte.
Configuração: alertas.json. Memória do que já foi avisado: data/alertas_estado.json.
"""
import json, os, sys, urllib.request, datetime as dt, glob
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.environ.get('GITHUB_REPOSITORY', 'contadeinfo/painel-fundos')
DONO = REPO.split('/')[0]
TOKEN = os.environ.get('GITHUB_TOKEN')
CFG = json.load(open(os.path.join(RAIZ, 'alertas.json'), encoding='utf-8'))
EST_ARQ = os.path.join(RAIZ, 'data', 'alertas_estado.json')
COLS = {'dia': 1, 'mes': 3, 'ano': 5, 'm12': 7, 'm24': 9, 'm36': 11, 'm48': 13, 'm60': 15}
NOMEJ = {'dia': 'dia', 'mes': 'mês', 'ano': 'ano', 'm12': '12 meses', 'm24': '24 meses', 'm36': '36 meses'}
PAINEL = 'Abra o Painel Comercial (aba Relatório Peers) para ver os detalhes.'


def gh(metodo, caminho, corpo=None):
    if not TOKEN:
        print('(sem token) ', metodo, caminho, (corpo or {}).get('title'))
        return {}
    req = urllib.request.Request(f'https://api.github.com/repos/{REPO}{caminho}', method=metodo,
                                 data=json.dumps(corpo).encode() if corpo else None,
                                 headers={'Authorization': f'Bearer {TOKEN}', 'Accept': 'application/vnd.github+json',
                                          'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def avisa(titulo, texto, fechar=True, rotulo='aviso'):
    corpo = f'@{DONO}\n\n{texto}\n\n---\n_Aviso automático do robô ({dt.datetime.utcnow():%d/%m/%Y %H:%M} UTC). Configuração em `alertas.json`._'
    try:
        gh('POST', '/labels', {'name': rotulo, 'color': 'b08a3e'})
    except Exception:
        pass
    try:
        i = gh('POST', '/issues', {'title': titulo, 'body': corpo, 'labels': [rotulo]})
        if fechar and i.get('number'):
            gh('PATCH', f"/issues/{i['number']}", {'state': 'closed', 'state_reason': 'completed'})
        print('aviso:', titulo)
    except Exception as e:
        print('falha ao abrir aviso', titulo, e)


def quartil(pos, de):
    if not pos or not de:
        return None
    return 1 if pos <= de / 4 else 2 if pos <= de / 2 else 3 if pos <= 3 * de / 4 else 4


def sg(v, d=2):
    return '—' if v is None else f"{'+' if v > 0 else ''}{v:.{d}f}%".replace('.', ',')


def mi(v):
    return '—' if v is None else ('−' if v < 0 else '') + f'R$ {abs(v) / 1e6:,.1f} mi'.replace(',', 'X').replace('.', ',').replace('X', '.')


def cotacoes():
    try:
        with urllib.request.urlopen(f'https://raw.githubusercontent.com/{REPO}/cotacoes/cotacoes.json', timeout=20) as r:
            return json.load(r)
    except Exception:
        return None


def completo(E):
    P = json.load(open(os.path.join(RAIZ, 'data', 'peers.json'), encoding='utf-8'))
    ref = P['data']
    fundos = [r for r in P['rows'] if r[0] not in ('IBOV', 'CDI')]
    set_row = next((r for r in fundos if r[0].lower().startswith('set')), None)
    # 1) quartil do Set
    if set_row and CFG.get('set_mudou_quartil'):
        for j in CFG['set_mudou_quartil']:
            i = COLS[j]
            de = sum(1 for r in fundos if r[i] is not None)
            q = quartil(set_row[i + 1], de)
            ant = E.setdefault('quartil', {}).get(j)
            if q and ant and q != ant:
                avisa(f'Set FIF mudou do {ant}º para o {q}º quartil ({NOMEJ[j]})',
                      f'Na janela de **{NOMEJ[j]}**, o Set FIF passou do **{ant}º** para o **{q}º quartil** entre os {de} peers '
                      f'(posição {set_row[i + 1]}º, retorno {sg(set_row[i])}), com dados da CVM de {ref}.\n\n{PAINEL}')
            if q:
                E['quartil'][j] = q
    # 2) captação e resgate do dia (fichas)
    vistos = E.setdefault('fluxo', {})
    for arq in glob.glob(os.path.join(RAIZ, 'data', 'fundos', '*.json')):
        F = json.load(open(arq, encoding='utf-8'))
        S = F.get('serie') or {}
        if not S.get('d') or len(S['d']) < 2:
            continue
        d, pl_ant = S['d'][-1], S['pl'][-2]
        mensal = F.get('mensal') or []
        # captação líquida do último dia = diferença de PL não explicada pela cota
        c0, c1, p1 = S['cota'][-2], S['cota'][-1], S['pl'][-1]
        if not (pl_ant and c0 and c1 and p1):
            continue
        fluxo = p1 - pl_ant * c1 / c0
        pct = fluxo / pl_ant * 100
        k = f"{F['cnpj']}:{d}"
        if k in vistos:
            continue
        eh_set = F['cnpj'] == '02444266000159'
        lim_r = CFG.get('set_resgate_pct_pl') if eh_set else CFG.get('resgate_peer_pct_pl')
        lim_c = None if eh_set else CFG.get('captacao_peer_pct_pl')
        if lim_r and pct <= -lim_r:
            vistos[k] = 1
            avisa(f"Resgate de {abs(pct):.1f}% do patrimônio em {F['nome'][:60]}",
                  f"Em {d[8:]}/{d[5:7]}/{d[:4]}, **{F['nome']}** teve saída líquida estimada de **{mi(-fluxo)}** "
                  f"({abs(pct):.1f}% do patrimônio). Patrimônio agora: {mi(p1)}.\n\n{PAINEL}")
        elif lim_c and pct >= lim_c:
            vistos[k] = 1
            avisa(f"Captação de {pct:.1f}% do patrimônio em {F['nome'][:60]}",
                  f"Em {d[8:]}/{d[5:7]}/{d[:4]}, **{F['nome']}** teve entrada líquida estimada de **{mi(fluxo)}** "
                  f"({pct:.1f}% do patrimônio). Patrimônio agora: {mi(p1)}.\n\n{PAINEL}")
    E['fluxo'] = {k: v for k, v in vistos.items() if k.split(':')[1] >= (dt.date.today() - dt.timedelta(days=30)).isoformat()}
    # 3) concorrentes novos no radar
    lim = CFG.get('novo_concorrente_pl_min')
    rad = os.path.join(RAIZ, 'data', 'radar.json')
    if lim and os.path.exists(rad):
        R = json.load(open(rad, encoding='utf-8'))
        grandes = {f['cnpj']: f for f in R['fundos'] if f['pl'] >= lim}
        conhecidos = set(E.get('radar', []))
        novos = [f for c, f in grandes.items() if c not in conhecidos]
        if conhecidos and novos:
            linhas = '\n'.join(f"- **{f['nome']}** ({f['anbima']}): PL {mi(f['pl'])}, 12 meses {sg(f.get('m12'))}" for f in novos[:15])
            avisa(f'{len(novos)} fundo(s) novo(s) no radar de concorrentes',
                  f'Fundos de ações livres com patrimônio acima de {mi(lim)} que entraram no radar:\n\n{linhas}\n\nSe quiser incluir algum nos peers, peça ou edite `fundos.json`.')
        E['radar'] = sorted(set(grandes) | conhecidos)
    # 4) resumo diário (só na rodada da manhã)
    agora_br = dt.datetime.utcnow() - dt.timedelta(hours=3)
    hoje = agora_br.date().isoformat()
    if CFG.get('resumo_diario') and agora_br.hour < 12 and agora_br.weekday() < 5 and E.get('resumo') != hoje:
        E['resumo'] = hoje
        resumo(P, set_row, fundos)


def resumo(P, set_row, fundos):
    L = [f"**Dados de fundos (CVM) de {P['data']}**", '']
    if set_row:
        L.append('| Janela | Set FIF | Posição | Ibovespa | CDI |')
        L.append('|---|---|---|---|---|')
        bench = {r[0]: r for r in P['rows'] if r[0] in ('IBOV', 'CDI')}
        for j in ('dia', 'mes', 'ano', 'm12', 'm24', 'm36'):
            i = COLS[j]
            de = sum(1 for r in fundos if r[i] is not None)
            L.append(f"| {NOMEJ[j]} | {sg(set_row[i])} | {set_row[i + 1] or '—'}º de {de} ({quartil(set_row[i + 1], de) or '—'}º quartil) | "
                     f"{sg(bench.get('IBOV', [None] * 20)[i])} | {sg(bench.get('CDI', [None] * 20)[i])} |")
        L += ['', f"Patrimônio do Set: {mi(set_row[17])} · captação líquida no ano: {mi(set_row[19])}", '']
    mes = sorted((r for r in fundos if r[3] is not None), key=lambda r: -r[3])
    if mes:
        L.append('**Melhores do mês:** ' + '; '.join(f'{r[0][:40]} {sg(r[3])}' for r in mes[:3]))
        L.append('**Piores do mês:** ' + '; '.join(f'{r[0][:40]} {sg(r[3])}' for r in mes[-3:]))
        L.append('')
    Q = cotacoes()
    if Q and Q.get('q'):
        L.append('**Mercado (último dado do robô de cotações)**')
        L.append('')
        nomes = [('^BVSP', 'Ibovespa'), ('BRL=X', 'Dólar'), ('^GSPC', 'S&P 500'), ('BZ=F', 'Brent'), ('GC=F', 'Ouro'), ('BTC-USD', 'Bitcoin')]
        for s, n in nomes:
            q = Q['q'].get(s)
            if q:
                m = q['m']
                v = (m['regularMarketPrice'] / m['chartPreviousClose'] - 1) * 100 if m.get('chartPreviousClose') else None
                L.append(f"- {n}: {m['regularMarketPrice']:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.') + (f' ({sg(v)})' if v is not None else ''))
        if Q.get('di'):
            L.append('- Juros futuros (DI): ' + ' · '.join(f"{d['venc'][5:]}/{d['venc'][2:4]} {d['taxa']:.2f}%".replace('.', ',') for d in Q['di'][::3][:6]))
        L.append('')
    fo = os.path.join(RAIZ, 'data', 'focus.json')
    if os.path.exists(fo):
        F = json.load(open(fo, encoding='utf-8'))
        a = F['anos'][0]
        ult = lambda ind: (F['series'].get(ind, {}).get(a) or [[None, None]])[-1][1]
        f2 = lambda v: '—' if v is None else f'{v:.2f}'.replace('.', ',')
        L.append(f"**Focus ({a}):** IPCA {f2(ult('IPCA'))}% · Selic {f2(ult('Selic'))}% · câmbio R$ {f2(ult('Câmbio'))} · PIB {f2(ult('PIB Total'))}%")
    avisa(f"Resumo do dia {dt.date.today():%d/%m/%Y}", '\n'.join(L), rotulo='resumo')


def mercado(E):
    Q = cotacoes()
    if not Q:
        return
    hoje = (dt.datetime.utcnow() - dt.timedelta(hours=3)).date().isoformat()
    feitos = E.setdefault('mercado', {})
    feitos = {k: v for k, v in feitos.items() if v == hoje}
    q = Q['q']
    usd = q.get('BRL=X', {}).get('m', {}).get('regularMarketPrice')
    if usd and CFG.get('dolar_acima') and usd >= CFG['dolar_acima'] and 'usd_acima' not in feitos:
        feitos['usd_acima'] = hoje
        avisa(f"Dólar acima de R$ {CFG['dolar_acima']}", f'O dólar está em **R$ {usd:.4f}**.'.replace('.', ','))
    if usd and CFG.get('dolar_abaixo') and usd <= CFG['dolar_abaixo'] and 'usd_abaixo' not in feitos:
        feitos['usd_abaixo'] = hoje
        avisa(f"Dólar abaixo de R$ {CFG['dolar_abaixo']}", f'O dólar está em **R$ {usd:.4f}**.'.replace('.', ','))
    ib = q.get('^BVSP', {}).get('m', {})
    lim = CFG.get('ibov_variacao_dia_pct')
    if lim and ib.get('chartPreviousClose'):
        v = (ib['regularMarketPrice'] / ib['chartPreviousClose'] - 1) * 100
        if abs(v) >= lim and 'ibov' not in feitos:
            feitos['ibov'] = hoje
            avisa(f"Ibovespa {'sobe' if v > 0 else 'cai'} {abs(v):.1f}% hoje".replace('.', ','),
                  f"O Ibovespa está em **{ib['regularMarketPrice']:,.0f} pontos** ({sg(v)}), com atraso de até 15 minutos.".replace(',', '.'))
    E['mercado'] = feitos


def main():
    modo = sys.argv[1] if len(sys.argv) > 1 else 'completo'
    try:
        E = json.load(open(EST_ARQ, encoding='utf-8'))
    except Exception:
        E = {}
    (completo if modo == 'completo' else mercado)(E)
    json.dump(E, open(EST_ARQ, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)


if __name__ == '__main__':
    sys.exit(main())
