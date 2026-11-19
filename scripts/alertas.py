#!/usr/bin/env python3
"""Avisos por e-mail: o robô abre uma "issue" no repositório marcando @dono; o GitHub manda e-mail.

Modo 'completo' (depois da atualização dos peers): fundo de referência mudou de quartil, resgate/captação
forte de peer, resgate forte no fundo de referência, concorrente novo no radar e, de manhã, o resumo diário.
Modo 'mercado' (durante o pregão): dólar acima/abaixo de um valor e Ibovespa com variação forte.
Configuração: alertas.json. Memória do que já foi avisado: data/alertas_estado.json.
"""
import json, os, sys, urllib.request, datetime as dt, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.environ.get('GITHUB_REPOSITORY', 'contadeinfo/painel-fundos')
DONO = REPO.split('/')[0]
TOKEN = os.environ.get('GITHUB_TOKEN')
CFG = json.load(open(os.path.join(RAIZ, 'alertas.json'), encoding='utf-8'))
REF = CFG.get('fundo_referencia')
EST_ARQ = os.path.join(RAIZ, 'data', 'alertas_estado.json')
COLS = {'dia': 1, 'mes': 3, 'ano': 5, 'm12': 7, 'm24': 9, 'm36': 11, 'm48': 13, 'm60': 15}
NOMEJ = {'dia': 'dia', 'mes': 'mês', 'ano': 'ano', 'm12': '12 meses', 'm24': '24 meses', 'm36': '36 meses'}
PAINEL = 'Detalhes no painel.'


import email_bonito as EB  # noqa: E402
from email_bonito import Msg, envia, grafico_barras, grafico_linhas, AZUL, OURO, VERDE, VERM, CINZA  # noqa: E402


def avisa(titulo, texto, fechar=True, rotulo='aviso'):
    """Aviso simples (só texto) — usado pelos avisos de mercado."""
    envia(Msg(titulo, tom='info', rotulo=rotulo).texto(texto.replace('**', '')))


def fmt(v, d=2):
    return '—' if v is None else f'{v:,.{d}f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


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
    nome_ref = next((f['nome'] for f in json.load(open(os.path.join(RAIZ, 'fundos.json'), encoding='utf-8')) if f['cnpj'] == REF), None)
    set_row = next((r for r in fundos if r[0] == nome_ref), None)
    # 1) quartil do fundo de referência
    if set_row and CFG.get('referencia_mudou_quartil'):
        for j in CFG['referencia_mudou_quartil']:
            i = COLS[j]
            de = sum(1 for r in fundos if r[i] is not None)
            q = quartil(set_row[i + 1], de)
            ant = E.setdefault('quartil', {}).get(j)
            if q and ant and q != ant:
                melhor = q < ant
                m = Msg(f"Fundo de referência {'subiu' if melhor else 'caiu'} para o {q}º quartil ({NOMEJ[j]})",
                        f'Peers de fundos de ações · dados da CVM de {ref}', tom='bom' if melhor else 'alerta', rotulo='aviso')
                m.kpis([('Quartil agora', f'{q}º', f'antes: {ant}º', VERDE if melhor else VERM),
                        ('Posição', f'{set_row[i + 1]}º de {de}', NOMEJ[j], None),
                        ('Retorno na janela', sg(set_row[i]), 'pela cota, líquido de taxas', VERDE if (set_row[i] or 0) >= 0 else VERM)])
                m.secao('Todas as janelas').tabela(['Janela', 'Retorno', 'Posição', 'Quartil'],
                        [[NOMEJ[x], sg(set_row[COLS[x]]), f"{set_row[COLS[x] + 1] or '—'}º", f"{quartil(set_row[COLS[x] + 1], sum(1 for r in fundos if r[COLS[x]] is not None)) or '—'}º"] for x in ('dia', 'mes', 'ano', 'm12', 'm24', 'm36')])
                envia(m)
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
        eh_set = F['cnpj'] == REF
        lim_r = CFG.get('referencia_resgate_pct_pl') if eh_set else CFG.get('resgate_peer_pct_pl')
        lim_c = None if eh_set else CFG.get('captacao_peer_pct_pl')
        if (lim_r and pct <= -lim_r) or (lim_c and pct >= lim_c):
            vistos[k] = 1
            saida = pct < 0
            dd = f'{d[8:]}/{d[5:7]}/{d[:4]}'
            m = Msg(f"{'Resgate' if saida else 'Captação'} de {abs(pct):.1f}% do patrimônio em {F['nome'][:60]}".replace('.', ','),
                    f'Movimento estimado em {dd}, pelo informe diário da CVM', tom='alerta' if saida else 'bom')
            m.kpis([('Saída líquida' if saida else 'Entrada líquida', mi(abs(fluxo)), f'em {dd}', VERM if saida else VERDE),
                    ('% do patrimônio', f'{abs(pct):.1f}%'.replace('.', ','), 'do dia anterior', VERM if saida else VERDE),
                    ('Patrimônio agora', mi(p1), f"CNPJ {F['cnpj'][:2]}.{F['cnpj'][2:5]}.{F['cnpj'][5:8]}/{F['cnpj'][8:12]}-{F['cnpj'][12:]}", None)])
            n = min(90, len(S['d']))
            g = grafico_linhas(f"pl_{F['cnpj']}", [x[8:] + '/' + x[5:7] for x in S['d'][-n:]],
                               [('Patrimônio (R$ mi)', [v / 1e6 if v else None for v in S['pl'][-n:]], OURO, '-')], 'Patrimônio nos últimos meses', unidade=' mi', area=True)
            m.grafico(g, 'Patrimônio líquido diário (R$ milhões), informe diário da CVM')
            m.lista(['Estimativa: variação do patrimônio que não se explica pela variação da cota.',
                     'Pode incluir come-cotas, amortização ou ajuste do administrador; confirme no painel antes de comentar com alguém.'])
            envia(m)
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
            m = Msg(f'{len(novos)} fundo(s) novo(s) no radar de concorrentes', f'Ações livres e valor/crescimento com patrimônio acima de {mi(lim)}', tom='info')
            m.tabela(['Fundo', 'PL', 'Mês', 'Ano', '12 meses'], [[f['nome'][:48], mi(f['pl']), sg(f.get('mes')), sg(f.get('ano')), sg(f.get('m12'))] for f in novos[:15]],
                     ['left', 'right', 'right', 'right', 'right'])
            m.texto('Para incluir algum nos peers, peça ou edite o arquivo fundos.json do repositório.')
            envia(m)
        E['radar'] = sorted(set(grandes) | conhecidos)
    # 4) resumo diário (só na rodada da manhã)
    agora_br = dt.datetime.utcnow() - dt.timedelta(hours=3)
    hoje = agora_br.date().isoformat()
    if CFG.get('resumo_diario') and agora_br.hour < 12 and agora_br.weekday() < 5 and E.get('resumo') != hoje:
        E['resumo'] = hoje
        resumo(P, set_row, fundos)


def resumo(P, set_row, fundos):
    hoje = dt.date.today()
    m = Msg(f'Resumo de {hoje:%d/%m/%Y}', f"Fundos de ações (CVM) até {P['data']} · mercado pelo robô de cotações", tom='resumo', rotulo='resumo')
    bench = {r[0]: r for r in P['rows'] if r[0] in ('IBOV', 'CDI')}
    jan = ('dia', 'mes', 'ano', 'm12', 'm24', 'm36')
    med = lambda i: (lambda v: v[len(v) // 2] if v else None)(sorted(r[i] for r in fundos if r[i] is not None))
    if set_row:
        q12 = quartil(set_row[8], sum(1 for r in fundos if r[7] is not None))
        m.kpis([('Fundo de referência no mês', sg(set_row[3]), f"{set_row[4]}º de {sum(1 for r in fundos if r[3] is not None)} peers", VERDE if (set_row[3] or 0) >= 0 else VERM),
                ('No ano', sg(set_row[5]), f"Ibovespa {sg(bench.get('IBOV', [None]*20)[5])} · CDI {sg(bench.get('CDI', [None]*20)[5])}", VERDE if (set_row[5] or 0) >= 0 else VERM),
                ('12 meses', sg(set_row[7]), f'{q12 or "—"}º quartil entre os peers', VERDE if (q12 or 4) <= 2 else VERM),
                ('Patrimônio', mi(set_row[17]), f'captação no ano {mi(set_row[19])}', None)])
        g = grafico_barras('resumo_janelas', [NOMEJ[j] for j in jan],
                           [('Fundo de referência', [set_row[COLS[j]] for j in jan], OURO), ('Mediana dos peers', [med(COLS[j]) for j in jan], '#94a3b8'),
                            ('Ibovespa', [bench.get('IBOV', [None]*20)[COLS[j]] for j in jan], AZUL), ('CDI', [bench.get('CDI', [None]*20)[COLS[j]] for j in jan], VERDE)])
        m.secao('Fundo de referência contra os pares').grafico(g, 'Retorno por janela (%), pela cota, líquido de taxas')
        m.tabela(['Janela', 'Fundo', 'Posição', 'Quartil', 'Ibovespa', 'CDI'],
                 [[NOMEJ[j], sg(set_row[COLS[j]]), f"{set_row[COLS[j] + 1] or '—'}º de {sum(1 for r in fundos if r[COLS[j]] is not None)}",
                   f"{quartil(set_row[COLS[j] + 1], sum(1 for r in fundos if r[COLS[j]] is not None)) or '—'}º", sg(bench.get('IBOV', [None]*20)[COLS[j]]), sg(bench.get('CDI', [None]*20)[COLS[j]])] for j in jan])
    mes = sorted((r for r in fundos if r[3] is not None), key=lambda r: -r[3])
    if mes:
        m.secao('Destaques do mês entre os peers')
        m.lista([f'▲ {r[0][:46]}: {sg(r[3])}' for r in mes[:3]] + [f'▼ {r[0][:46]}: {sg(r[3])}' for r in mes[-3:][::-1]])
    Q = cotacoes()
    if Q and Q.get('q'):
        m.secao('Mercado')
        it = []
        for s_, n in [('^BVSP', 'Ibovespa'), ('BRL=X', 'Dólar'), ('^GSPC', 'S&P 500'), ('BZ=F', 'Petróleo Brent'), ('GC=F', 'Ouro'), ('BTC-USD', 'Bitcoin')]:
            q = Q['q'].get(s_)
            if q:
                mm = q['m']
                v = (mm['regularMarketPrice'] / mm['chartPreviousClose'] - 1) * 100 if mm.get('chartPreviousClose') else None
                d = 4 if s_ == 'BRL=X' else 0 if s_ in ('^BVSP', 'BTC-USD') else 2
                it.append((n, ('R$ ' if s_ == 'BRL=X' else 'US$ ' if s_ in ('BZ=F', 'GC=F', 'BTC-USD') else '') + fmt(mm['regularMarketPrice'], d),
                           sg(v) + ' no dia' if v is not None else 'variação: ver painel', VERDE if (v or 0) > 0 else VERM if (v or 0) < 0 else None))
        m.kpis(it)
        D = [x for x in (Q.get('di') or []) if x.get('taxa') is not None]
        if D:
            lab = [x['venc'][5:] + '/' + x['venc'][2:4] for x in D]
            g = grafico_linhas('resumo_di', lab, [('Hoje', [x['taxa'] for x in D], OURO, '-'), ('Há 1 semana', [x.get('semana') for x in D], AZUL, '--'),
                                                  ('Há 1 mês', [x.get('mes') for x in D], VERDE, ':')], 'Curva de juros futuros (DI1)')
            m.grafico(g, 'Taxa de cada vencimento, % ao ano (TradingView, atraso de até 15 min)')
    fo = os.path.join(RAIZ, 'data', 'focus.json')
    if os.path.exists(fo):
        F = json.load(open(fo, encoding='utf-8'))
        a = F['anos'][0]
        def ult(ind, k=-1):
            s_ = F['series'].get(ind, {}).get(a) or []
            return s_[k][1] if len(s_) >= abs(k) else None
        m.secao(f'Boletim Focus · expectativas para {a}')
        m.kpis([(n, fmt(ult(ind)) + u, (lambda x: f"{'+' if x > 0 else ''}{fmt(x)} em 4 semanas" if x is not None else '')(None if ult(ind) is None or ult(ind, -5) is None else ult(ind) - ult(ind, -5)), None)
                for ind, n, u in [('IPCA', 'IPCA', '%'), ('Selic', 'Selic', '%'), ('Câmbio', 'Câmbio', ''), ('PIB Total', 'PIB', '%')]])
    envia(m)


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
