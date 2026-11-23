#!/usr/bin/env python3
"""Boletim Focus (Banco Central): mediana das expectativas de mercado para IPCA, Selic, câmbio e PIB,
para este ano e os dois seguintes, nos últimos ~15 meses. Saída: data/focus.json."""
import json, os, sys, urllib.parse, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from atualiza import baixa, RAIZ  # noqa: E402

URL = 'https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/ExpectativasMercadoAnuais'
IND = ['IPCA', 'Selic', 'Câmbio', 'PIB Total']


def main():
    hoje = dt.date.today()
    ini = (hoje - dt.timedelta(days=460)).isoformat()
    anos = [str(hoje.year + i) for i in range(3)]
    out = {'gerado_em': dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'anos': anos, 'series': {}}
    for ind in IND:
        filtro = f"Indicador eq '{ind}' and baseCalculo eq 0 and Data ge '{ini}'"
        q = {'$top': '20000', '$format': 'json', '$select': 'Indicador,Data,DataReferencia,Mediana,numeroRespondentes', '$filter': filtro, '$orderby': 'Data asc'}
        j = json.loads(baixa(URL + '?' + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)))
        S = {}
        for r in j.get('value', []):
            if r['DataReferencia'] in anos:
                S.setdefault(r['DataReferencia'], {})[r['Data']] = r['Mediana']
        # uma observação por semana (sexta-feira de referência do boletim) para ficar leve
        sem = {}
        for a, d in S.items():
            pts = {}
            for data, v in d.items():
                x = dt.date.fromisoformat(data)
                sexta = x + dt.timedelta(days=(4 - x.weekday()) % 7)
                pts[sexta.isoformat()] = (data, v)
            sem[a] = [[k, v[1]] for k, v in sorted(pts.items())]
        out['series'][ind] = sem
        print(ind, {a: len(v) for a, v in sem.items()})
    json.dump(out, open(os.path.join(RAIZ, 'data', 'focus.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))


if __name__ == '__main__':
    sys.exit(main())
