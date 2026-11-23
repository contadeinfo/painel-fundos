"""Vigia do repositório: confere todo dia se algo protegido ficou público, quem mexeu nos robôs,
quem apareceu no repositório e se os robôs e os segredos estão em ordem.

Roda depois de `privado.py abrir`; o resultado (data/seguranca.json) é cifrado pelo `privado.py fechar`.
Lista de termos extras e de contas conhecidas: data/vigia.json (também cifrado).
"""
import datetime as dt, hashlib, json, os, re, subprocess, sys, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import privado  # noqa: E402

RAIZ = privado.RAIZ
REPO = os.environ.get('GITHUB_REPOSITORY', '')
TOKEN = os.environ.get('GITHUB_TOKEN', '')
TOKEN_ADM = os.environ.get('SEGURANCA_TOKEN', '')
SAIDA = os.path.join(RAIZ, 'data', 'seguranca.json')
VIGIA = os.path.join(RAIZ, 'data', 'vigia.json')
HOJE = dt.datetime.now(dt.timezone.utc)

vig = json.load(open(VIGIA, encoding='utf-8')) if os.path.exists(VIGIA) else {}
EXTRA = [t for t in vig.get('termos', []) if t]
RX = re.compile('|'.join(x for x in [privado.RX.pattern] + [re.escape(t) for t in EXTRA] if x), re.I)


def api(caminho, token=None):
    req = urllib.request.Request('https://api.github.com/' + caminho, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'vigia'})
    if token or TOKEN:
        req.add_header('Authorization', 'Bearer ' + (token or TOKEN))
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def git(*a):
    return subprocess.run(['git', *a], cwd=RAIZ, capture_output=True, text=True).stdout


def item(i, titulo, status, resumo, detalhes=None):
    return {'id': i, 'titulo': titulo, 'status': status, 'resumo': resumo, 'detalhes': detalhes or []}


def vazamento():
    """Procura os termos protegidos em tudo o que está publicado (último registro de cada ramo), fora a pasta cifrada."""
    achados, n = [], 0
    for ramo in ['HEAD', 'origin/espelho', 'origin/cotacoes']:
        if not git('rev-parse', '--verify', '-q', ramo).strip():
            continue
        for linha in git('ls-tree', '-r', '--format=%(objectname) %(objecttype) %(path)', ramo).splitlines():
            obj, tipo, caminho = linha.split(' ', 2)
            if tipo != 'blob' or caminho.startswith('data/p/'):
                continue
            n += 1
            if RX.search(caminho):
                achados.append(f'{ramo.replace("origin/", "")}: {caminho} (nome do arquivo)'); continue
            dados = subprocess.run(['git', 'cat-file', '-p', obj], cwd=RAIZ, capture_output=True).stdout
            if len(dados) > 30_000_000:
                continue
            if RX.search(dados.decode('utf-8', 'replace')):
                achados.append(f'{ramo.replace("origin/", "")}: {caminho}')
    if achados:
        return item('vazamento', 'Vazamento de dados protegidos', 'alerta', f'{len(achados)} arquivo(s) públicos com termo protegido', achados[:40])
    return item('vazamento', 'Vazamento de dados protegidos', 'ok', f'nada encontrado em {n:,} arquivos públicos'.replace(',', '.'))


def segredos():
    det, st = [], 'ok'
    idx = os.path.join(RAIZ, 'data', 'p', 'i.bin')
    try:
        lista = json.loads(privado.decifra('i', open(idx, 'rb').read()))
        det.append(f'chave abre os dados cifrados ({len(lista)} arquivos guardados)')
    except Exception:
        return item('segredos', 'Chave e segredos', 'alerta', 'a chave não abre os dados cifrados')
    fp = hashlib.sha256(privado.SENHA.encode()).hexdigest()[:12]
    if vig.get('chave_fp') != fp:
        vig['chave_fp'], vig['chave_desde'] = fp, HOJE.date().isoformat()
        det.append('chave nova detectada hoje')
    dias = (HOJE.date() - dt.date.fromisoformat(vig.get('chave_desde', HOJE.date().isoformat()))).days
    det.append(f'chave em uso desde {vig.get("chave_desde")} ({dias} dias)')
    if dias > 180:
        st = 'atencao'; det.append('troca recomendada a cada 6 meses')
    return item('segredos', 'Chave e segredos', st, f'segredos presentes · chave com {dias} dias', det)


AUTORES_OK = re.compile(r'(^noreply@anthropic\.com$)|(^robo-[a-z-]+@users\.noreply\.github\.com$)|(^\d*\+?github-actions\[bot\]@users\.noreply\.github\.com$)|(^noreply@github\.com$)')


def alteracoes():
    """Quem mexeu nos robôs (workflows e scripts) nos últimos 60 dias."""
    log = git('log', '--since=60 days ago', '--format=@@%H|%ad|%an|%ae|%ce|%s', '--date=short', '--name-only', '--', '.github', 'scripts', 'fundos.json', 'alertas.json')
    mud, estranhos = [], []
    for bloco in log.split('@@')[1:]:
        cab, *arqs = [x for x in bloco.strip().split('\n') if x]
        h, data, nome, mail, cmail, msg = cab.split('|', 5)
        ok = AUTORES_OK.match(mail) and AUTORES_OK.match(cmail)
        linha = f'{data} · {nome} · {msg[:70]} ({len(arqs)} arquivo(s))'
        mud.append(('' if ok else '⚠ ') + linha)
        if not ok:
            estranhos.append(linha)
    if estranhos:
        return item('alteracoes', 'Mudanças nos robôs', 'alerta', f'{len(estranhos)} alteração(ões) feita(s) por autor desconhecido', mud[:30])
    return item('alteracoes', 'Mudanças nos robôs', 'ok', f'{len(mud)} alteração(ões) em 60 dias, todas pelos robôs ou pelo Claude', mud[:30])


def atividade():
    det, st = [], 'ok'
    ok = set(vig.get('atores_ok', [])) | {'github-actions[bot]'}
    dono = REPO.split('/')[0]
    ok.add(dono)
    try:
        ev = api(f'repos/{REPO}/events?per_page=100')
        estranhos = sorted({(e['actor']['login'], e['type']) for e in ev if e['actor']['login'] not in ok})
        if estranhos:
            st = 'alerta'; det += [f'conta desconhecida: {a} ({t})' for a, t in estranhos]
        det.append(f'{len(ev)} eventos recentes · contas: ' + ', '.join(sorted({e["actor"]["login"] for e in ev})))
    except Exception as e:
        st = 'atencao'; det.append(f'não consegui ler os eventos: {e}')
    try:
        r = api(f'repos/{REPO}')
        det.append(f'visibilidade: {r["visibility"]} · cópias (forks): {r["forks_count"]} · favoritos: {r["stargazers_count"]} · seguidores: {r.get("subscribers_count", 0)}')
        if r['forks_count'] or r['stargazers_count']:
            st = 'alerta' if r['forks_count'] else max(st, 'atencao', key=['ok', 'atencao', 'alerta'].index)
        if r.get('has_issues'):
            det.append('avisos (Issues) ligados: qualquer pessoa pode abrir um aviso')
        pr = api(f'repos/{REPO}/pulls?state=all&per_page=50')
        prs = [p for p in pr if p['user']['login'] not in ok]
        if prs:
            st = 'alerta'; det += [f'proposta de alteração de {p["user"]["login"]}: #{p["number"]} {p["title"][:60]} ({p["state"]})' for p in prs]
        iss = api(f'repos/{REPO}/issues?state=all&per_page=100')
        estr = [i for i in iss if i['user']['login'] not in ok and 'pull_request' not in i]
        if estr:
            st = max(st, 'atencao', key=['ok', 'atencao', 'alerta'].index)
            det += [f'aviso aberto por {i["user"]["login"]}: #{i["number"]} {i["title"][:60]}' for i in estr]
    except Exception as e:
        st = max(st, 'atencao', key=['ok', 'atencao', 'alerta'].index); det.append(f'não consegui ler o repositório: {e}')
    resumo = {'ok': 'só você e os robôs aparecem', 'atencao': 'há algo para conferir', 'alerta': 'apareceu alguém de fora'}[st]
    return item('atividade', 'Quem mexeu no repositório', st, resumo, det)


def robos():
    try:
        runs = api(f'repos/{REPO}/actions/runs?per_page=100')['workflow_runs']
    except Exception as e:
        return item('robos', 'Robôs', 'atencao', 'não consegui ler as execuções', [str(e)])
    ult = {}
    for r in runs:
        if r['status'] == 'completed' and r['name'] not in ult:
            ult[r['name']] = r
    falhas = [n for n, r in ult.items() if r['conclusion'] not in ('success', 'skipped', 'cancelled')]
    det = [f'{"⚠ " if n in falhas else ""}{n}: {r["conclusion"]} em {r["updated_at"][:16].replace("T", " ")} UTC' for n, r in sorted(ult.items())]
    st = 'atencao' if falhas else 'ok'
    return item('robos', 'Robôs', st, f'{len(falhas)} com falha na última execução' if falhas else f'{len(ult)} robôs rodando normalmente', det)


def trafego():
    if not TOKEN_ADM:
        return item('trafego', 'Visitas e downloads', 'info', 'não monitorado (precisa de um token de leitura opcional)')
    try:
        v = api(f'repos/{REPO}/traffic/views', TOKEN_ADM); c = api(f'repos/{REPO}/traffic/clones', TOKEN_ADM)
        ref = api(f'repos/{REPO}/traffic/popular/referrers', TOKEN_ADM)
        det = [f'{x["timestamp"][:10]}: {x["count"]} visitas ({x["uniques"]} pessoas)' for x in v['views'] if x['count']]
        det += ['vindas de: ' + ', '.join(f'{r["referrer"]} ({r["count"]})' for r in ref)] if ref else []
        st = 'atencao' if any(r['referrer'] not in ('github.com',) for r in ref) or v['uniques'] > 3 else 'ok'
        return item('trafego', 'Visitas e downloads', st, f'{v["count"]} visitas de {v["uniques"]} pessoa(s) em 14 dias · {c["count"]} downloads (a maior parte são os robôs)', det)
    except Exception as e:
        return item('trafego', 'Visitas e downloads', 'atencao', 'não consegui ler as visitas', [str(e)])


def avisa(itens, antes):
    alertas = sorted(i['id'] for i in itens if i['status'] == 'alerta')
    if not alertas or alertas == sorted(antes.get('alertas', [])) or not TOKEN:
        return
    try:   # aviso sem detalhes: o conteúdo fica só no painel
        req = urllib.request.Request(f'https://api.github.com/repos/{REPO}/issues', method='POST',
                                     data=json.dumps({'title': 'Verificação diária: abra a aba Segurança do painel', 'body': f'@{REPO.split("/")[0]} há um ponto em vermelho na aba Segurança.'}).encode(),
                                     headers={'Authorization': 'Bearer ' + TOKEN, 'Accept': 'application/vnd.github+json', 'User-Agent': 'vigia'})
        n = json.load(urllib.request.urlopen(req, timeout=30))['number']
        req = urllib.request.Request(f'https://api.github.com/repos/{REPO}/issues/{n}', method='PATCH', data=b'{"state":"closed"}',
                                     headers={'Authorization': 'Bearer ' + TOKEN, 'Accept': 'application/vnd.github+json', 'User-Agent': 'vigia'})
        urllib.request.urlopen(req, timeout=30)
    except Exception:
        pass


def main():
    antes = json.load(open(SAIDA, encoding='utf-8')) if os.path.exists(SAIDA) else {}
    itens = [vazamento(), segredos(), alteracoes(), atividade(), robos(), trafego()]
    ordem = ['ok', 'info', 'atencao', 'alerta']
    geral = max((i['status'] for i in itens if i['status'] != 'info'), key=ordem.index, default='ok')
    hist = [h for h in antes.get('historico', []) if h['data'] != HOJE.date().isoformat()][-89:]
    hist.append({'data': HOJE.date().isoformat(), 'geral': geral, 'alertas': sum(i['status'] == 'alerta' for i in itens)})
    out = {'gerado_em': HOJE.strftime('%Y-%m-%dT%H:%MZ'), 'geral': geral, 'itens': itens, 'historico': hist,
           'alertas': [i['id'] for i in itens if i['status'] == 'alerta']}
    avisa(itens, antes)
    json.dump(out, open(SAIDA, 'w', encoding='utf-8'), ensure_ascii=False)
    json.dump(vig, open(VIGIA, 'w', encoding='utf-8'), ensure_ascii=False)
    print('verificação:', geral, '|', ' · '.join(f'{i["id"]}={i["status"]}' for i in itens))


if __name__ == '__main__':
    main()
