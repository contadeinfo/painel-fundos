#!/usr/bin/env python3
"""Histórico próprio: guarda uma foto por dia útil do que as fontes gratuitas só mostram no dia
(fechamento de todos os ativos do robô de cotações e a curva de juros futuros).
Saída: data/historico/fechamentos.json e data/historico/curva_di.json (um registro por dia)."""
import json, os, sys, urllib.request, datetime as dt
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.environ.get('GITHUB_REPOSITORY', 'contadeinfo/painel-fundos')
PASTA = os.path.join(RAIZ, 'data', 'historico')


def main():
    os.makedirs(PASTA, exist_ok=True)
    with urllib.request.urlopen(f'https://raw.githubusercontent.com/{REPO}/cotacoes/cotacoes.json', timeout=30) as r:
        Q = json.load(r)
    dia = (dt.datetime.fromisoformat(Q['gerado_em'].replace('Z', '+00:00')) - dt.timedelta(hours=3)).date().isoformat()
    for nome, valor in (('fechamentos', {s: v['m'].get('regularMarketPrice') for s, v in Q['q'].items()}),
                        ('curva_di', {d['venc']: d['taxa'] for d in (Q.get('di') or [])})):
        if not valor:
            continue
        arq = os.path.join(PASTA, nome + '.json')
        try:
            H = json.load(open(arq, encoding='utf-8'))
        except Exception:
            H = {}
        H[dia] = valor
        json.dump(dict(sorted(H.items())[-800:]), open(arq, 'w', encoding='utf-8'), separators=(',', ':'))
        print(nome, dia, len(valor))


if __name__ == '__main__':
    sys.exit(main())
