"""Mensagens dos robôs com visual caprichado.

Uma mensagem é montada em blocos (números em destaque, tabela, tópicos, gráfico, texto) e sai de dois jeitos:
  1) e-mail em HTML pelo Gmail (tema escuro e dourado, fontes, gráficos embutidos), se os segredos
     GMAIL_USER e GMAIL_APP_PASSWORD estiverem configurados no repositório (Settings > Secrets > Actions);
  2) senão, como "issue" do GitHub (o GitHub manda o e-mail), em Markdown com tabelas, tópicos e gráficos.
O jeito 1 é o recomendado: fica mais bonito e nada aparece publicamente no repositório.
"""
import html, json, os, smtplib, ssl, urllib.request, datetime as dt
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.environ.get('GITHUB_REPOSITORY', 'contadeinfo/painel-fundos')
DONO = REPO.split('/')[0]
TOKEN = os.environ.get('GITHUB_TOKEN')
GMAIL = os.environ.get('GMAIL_USER')
SENHA = os.environ.get('GMAIL_APP_PASSWORD')
PARA = os.environ.get('EMAIL_TO') or GMAIL
GRAF = os.path.join(RAIZ, 'data', 'graficos')

AZUL, OURO, VERDE, VERM, CINZA, FUNDO = '#0f1b2d', '#b08a3e', '#0e7f57', '#c4362c', '#6b7280', '#f4f1ea'
TONS = {'alerta': VERM, 'bom': VERDE, 'info': OURO, 'resumo': OURO}


class Msg:
    def __init__(self, titulo, subtitulo='', tom='info', rotulo='aviso'):
        self.titulo, self.subtitulo, self.tom, self.rotulo, self.blocos = titulo, subtitulo, tom, rotulo, []

    def kpis(self, itens):          # [(rótulo, valor, detalhe, cor ou None)]
        self.blocos.append(('kpis', itens)); return self

    def secao(self, t):
        self.blocos.append(('secao', t)); return self

    def tabela(self, cab, linhas, alinhar=None):
        self.blocos.append(('tabela', cab, linhas, alinhar)); return self

    def lista(self, itens):
        self.blocos.append(('lista', itens)); return self

    def texto(self, t):
        self.blocos.append(('texto', t)); return self

    def grafico(self, caminho, legenda=''):
        if caminho and os.path.exists(caminho):
            self.blocos.append(('grafico', caminho, legenda))
        return self


# ---------------- gráficos (matplotlib, no tema do painel) ----------------
def _plt():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'axes.edgecolor': '#d6d0c4', 'axes.labelcolor': '#374151',
                         'xtick.color': '#4b5563', 'ytick.color': '#4b5563', 'axes.spines.top': False, 'axes.spines.right': False,
                         'axes.grid': True, 'grid.color': '#ebe6dc', 'grid.linewidth': .8, 'figure.facecolor': 'white', 'axes.facecolor': 'white'})
    return plt


def grafico_barras(nome, categorias, series, titulo='', unidade='%'):
    """series: [(rótulo, [valores], cor)] — barras agrupadas horizontais."""
    try:
        plt = _plt()
        import numpy as np
        n, k = len(categorias), len(series)
        fig, ax = plt.subplots(figsize=(7.2, 0.55 * n + 1.2), dpi=150)
        y = np.arange(n)
        h = 0.8 / k
        for i, (rot, vals, cor) in enumerate(series):
            vv = [v if v is not None else 0 for v in vals]
            bars = ax.barh(y + (k - 1 - i) * h - 0.4 + h / 2, vv, height=h * 0.92, color=cor, label=rot)
            for b, v in zip(bars, vals):
                if v is not None:
                    ax.text(b.get_width() + (0.3 if v >= 0 else -0.3), b.get_y() + b.get_height() / 2, f'{v:+.1f}'.replace('.', ','),
                            va='center', ha='left' if v >= 0 else 'right', fontsize=7.5, color='#374151')
        ax.set_yticks(y)
        ax.set_yticklabels(categorias)
        ax.invert_yaxis()
        ax.axvline(0, color='#9ca3af', lw=.8)
        ax.xaxis.set_major_formatter(lambda v, p: f'{v:.0f}{unidade}')
        ax.grid(axis='y', visible=False)
        if titulo:
            ax.set_title(titulo, loc='left', fontsize=11, color=AZUL, fontweight='bold')
        ax.legend(loc='lower center', bbox_to_anchor=(.5, 1.0 if not titulo else 1.06), ncol=k, frameon=False, fontsize=8.5)
        fig.tight_layout()
        os.makedirs(GRAF, exist_ok=True)
        p = os.path.join(GRAF, nome + '.png')
        fig.savefig(p, bbox_inches='tight')
        plt.close(fig)
        return p
    except Exception as e:
        print('aviso gráfico', nome, e)
        return None


def grafico_linhas(nome, rotulos_x, series, titulo='', unidade='%', area=False):
    """series: [(rótulo, [valores], cor, estilo)]"""
    try:
        plt = _plt()
        fig, ax = plt.subplots(figsize=(7.2, 3.0), dpi=150)
        x = list(range(len(rotulos_x)))
        for rot, vals, cor, est in series:
            pts = [(i, v) for i, v in zip(x, vals) if v is not None]
            if not pts:
                continue
            ax.plot([p[0] for p in pts], [p[1] for p in pts], color=cor, lw=2.2 if est == '-' else 1.4, ls=est, label=rot,
                    marker='o' if len(pts) < 25 and est == '-' else None, ms=3)
            if area and est == '-':
                ax.fill_between([p[0] for p in pts], [p[1] for p in pts], min(p[1] for p in pts), color=cor, alpha=.08)
        passo = max(1, len(x) // 8)
        ax.set_xticks(x[::passo])
        ax.set_xticklabels(rotulos_x[::passo], fontsize=8)
        ax.yaxis.set_major_formatter(lambda v, p: f'{v:.1f}{unidade}'.replace('.', ','))
        if titulo:
            ax.set_title(titulo, loc='left', fontsize=11, color=AZUL, fontweight='bold')
        if len(series) > 1:
            ax.legend(frameon=False, fontsize=8.5, loc='best')
        fig.tight_layout()
        os.makedirs(GRAF, exist_ok=True)
        p = os.path.join(GRAF, nome + '.png')
        fig.savefig(p, bbox_inches='tight')
        plt.close(fig)
        return p
    except Exception as e:
        print('aviso gráfico', nome, e)
        return None


# ---------------- HTML ----------------
def _esc(t):
    return html.escape(str(t if t is not None else '—'))


def para_html(m):
    cor = TONS.get(m.tom, OURO)
    cids, partes = [], []
    for b in m.blocos:
        if b[0] == 'kpis':
            por = 2 if len(b[1]) in (2, 4) else 3
            cel = ''.join(f'''<td style="padding:6px;width:{100 // min(por, len(b[1]))}%;vertical-align:top">
<div style="background:#ffffff;border:1px solid #e7e1d5;border-top:3px solid {c or OURO};border-radius:10px;padding:12px 14px">
<div style="font:600 10.5px/1.3 Helvetica,Arial,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:{CINZA}">{_esc(r)}</div>
<div style="font:600 20px/1.25 'Courier New',Menlo,monospace;white-space:nowrap;color:{c or AZUL};margin-top:4px">{_esc(v)}</div>
<div style="font:12px/1.4 Helvetica,Arial,sans-serif;color:{CINZA};margin-top:3px">{_esc(s) if s else ''}</div></div></td>''' for r, v, s, c in b[1])
            linhas = []
            itens = cel.split('</td>')[:-1]
            for i in range(0, len(itens), por):
                linhas.append('<tr>' + '</td>'.join(itens[i:i + por]) + '</td></tr>')
            partes.append(f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:4px 0 8px">{"".join(linhas)}</table>')
        elif b[0] == 'secao':
            partes.append(f'<h2 style="font:600 17px/1.3 Georgia,\'Times New Roman\',serif;color:{AZUL};margin:22px 0 8px;padding-left:10px;border-left:3px solid {OURO}">{_esc(b[1])}</h2>')
        elif b[0] == 'tabela':
            _, cab, linhas, al = b
            al = al or ['left'] + ['right'] * (len(cab) - 1)
            th = ''.join(f'<th style="text-align:{a};padding:8px 10px;font:600 10.5px Helvetica,Arial,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:{CINZA};border-bottom:1px solid #e7e1d5">{_esc(c)}</th>' for c, a in zip(cab, al))
            trs = ''
            for i, l in enumerate(linhas):
                tds = ''
                for v, a in zip(l, al):
                    cv = AZUL
                    sv = str(v)
                    if a == 'right' and sv.startswith('+'):
                        cv = VERDE
                    elif a == 'right' and (sv.startswith('−') or sv.startswith('-')):
                        cv = VERM
                    tds += f'<td style="text-align:{a};padding:8px 10px;font:13px/1.35 {"\'Courier New\',Menlo,monospace" if a == "right" else "Helvetica,Arial,sans-serif"};color:{cv};border-bottom:1px solid #f0ebe1">{_esc(v)}</td>'
                trs += f'<tr style="background:{"#fbf9f4" if i % 2 else "#ffffff"}">{tds}</tr>'
            partes.append(f'<table width="100%" cellspacing="0" cellpadding="0" style="border:1px solid #e7e1d5;border-radius:10px;border-collapse:separate;overflow:hidden;background:#fff"><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>')
        elif b[0] == 'lista':
            lis = ''.join(f'<li style="margin:0 0 6px;padding-left:4px">{_esc(x)}</li>' for x in b[1])
            partes.append(f'<ul style="margin:6px 0 4px 18px;padding:0;font:14px/1.5 Helvetica,Arial,sans-serif;color:#1f2937">{lis}</ul>')
        elif b[0] == 'texto':
            partes.append(f'<p style="font:14px/1.6 Helvetica,Arial,sans-serif;color:#1f2937;margin:8px 0">{_esc(b[1])}</p>')
        elif b[0] == 'grafico':
            cid = f'g{len(cids)}'
            cids.append((cid, b[1]))
            partes.append(f'<div style="background:#fff;border:1px solid #e7e1d5;border-radius:10px;padding:10px;margin:8px 0"><img src="cid:{cid}" width="560" style="width:100%;max-width:560px;display:block;margin:0 auto" alt="{_esc(b[2])}">{f"<div style=\'font:12px Helvetica,Arial,sans-serif;color:{CINZA};margin-top:6px\'>{_esc(b[2])}</div>" if b[2] else ""}</div>')
    agora = (dt.datetime.utcnow() - dt.timedelta(hours=3)).strftime('%d/%m/%Y às %H:%M')
    corpo = f'''<!doctype html><html><body style="margin:0;padding:0;background:{FUNDO}">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:{FUNDO}"><tr><td align="center" style="padding:24px 10px">
<table role="presentation" width="640" cellspacing="0" cellpadding="0" style="max-width:640px;width:100%">
<tr><td style="background:{AZUL};border-radius:14px 14px 0 0;padding:22px 26px;border-bottom:4px solid {cor}">
<div style="font:600 11px Helvetica,Arial,sans-serif;letter-spacing:.14em;text-transform:uppercase;color:{OURO}">Painel · robô de dados</div>
<div style="font:600 24px/1.25 Georgia,'Times New Roman',serif;color:#ffffff;margin-top:6px">{_esc(m.titulo)}</div>
{f'<div style="font:14px/1.5 Helvetica,Arial,sans-serif;color:#cbd5e1;margin-top:6px">{_esc(m.subtitulo)}</div>' if m.subtitulo else ''}
</td></tr>
<tr><td style="background:#faf8f3;padding:16px 20px 22px;border:1px solid #e7e1d5;border-top:0;border-radius:0 0 14px 14px">{''.join(partes)}
<p style="font:11.5px/1.5 Helvetica,Arial,sans-serif;color:{CINZA};margin:22px 0 0;border-top:1px solid #e7e1d5;padding-top:12px">Enviado automaticamente em {agora} (Brasília). Dados públicos (CVM, Banco Central, TradingView) — conteúdo informativo, não é recomendação de investimento. Limites dos avisos: arquivo alertas.json do repositório.</p>
</td></tr></table></td></tr></table></body></html>'''
    return corpo, cids


# ---------------- Markdown (issue do GitHub) ----------------
def para_markdown(m, sha_img=None):
    L = [f'@{DONO}', '', f'## {m.titulo}']
    if m.subtitulo:
        L += ['', f'_{m.subtitulo}_']
    for b in m.blocos:
        L.append('')
        if b[0] == 'kpis':
            L.append('| ' + ' | '.join(f'**{r}**' for r, *_ in b[1]) + ' |')
            L.append('|' + '---|' * len(b[1]))
            L.append('| ' + ' | '.join(f'{v}<br><sub>{s or ""}</sub>' for _, v, s, _c in b[1]) + ' |')
        elif b[0] == 'secao':
            L.append(f'### {b[1]}')
        elif b[0] == 'tabela':
            _, cab, linhas, al = b
            al = al or ['left'] + ['right'] * (len(cab) - 1)
            L.append('| ' + ' | '.join(cab) + ' |')
            L.append('|' + ''.join(':---|' if a == 'left' else '---:|' for a in al))
            L += ['| ' + ' | '.join(str(v) for v in l) + ' |' for l in linhas]
        elif b[0] == 'lista':
            L += [f'- {x}' for x in b[1]]
        elif b[0] == 'texto':
            L.append(b[1])
        elif b[0] == 'grafico':
            url = f'https://raw.githubusercontent.com/{REPO}/main/data/graficos/{os.path.basename(b[1])}?v={sha_img or dt.datetime.utcnow():%Y%m%d%H%M}'
            L.append(f'![{b[2]}]({url})')
            if b[2]:
                L.append(f'<sub>{b[2]}</sub>')
    L += ['', '---', f'<sub>Robô de dados · {(dt.datetime.utcnow() - dt.timedelta(hours=3)):%d/%m/%Y %H:%M} (Brasília) · dados públicos, não é recomendação · limites em <code>alertas.json</code></sub>']
    return '\n'.join(L)


def _gh(metodo, caminho, corpo=None):
    if not TOKEN:
        print('(sem token)', metodo, caminho, (corpo or {}).get('title'))
        return {}
    req = urllib.request.Request(f'https://api.github.com/repos/{REPO}{caminho}', method=metodo,
                                 data=json.dumps(corpo).encode() if corpo else None,
                                 headers={'Authorization': f'Bearer {TOKEN}', 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def envia(m):
    if GMAIL and SENHA:
        try:
            corpo, cids = para_html(m)
            msg = MIMEMultipart('related')
            msg['Subject'] = m.titulo
            msg['From'] = f'Painel de dados <{GMAIL}>'
            msg['To'] = PARA
            alt = MIMEMultipart('alternative')
            alt.attach(MIMEText(para_markdown(m).replace(f'@{DONO}', ''), 'plain', 'utf-8'))
            alt.attach(MIMEText(corpo, 'html', 'utf-8'))
            msg.attach(alt)
            for cid, p in cids:
                img = MIMEImage(open(p, 'rb').read(), 'png')
                img.add_header('Content-ID', f'<{cid}>')
                img.add_header('Content-Disposition', 'inline', filename=os.path.basename(p))
                msg.attach(img)
            with smtplib.SMTP_SSL('smtp.gmail.com', 465, context=ssl.create_default_context(), timeout=30) as s:
                s.login(GMAIL, SENHA)
                s.sendmail(GMAIL, [x.strip() for x in PARA.split(',')], msg.as_string())
            print('e-mail enviado:', m.titulo)
            return
        except Exception as e:
            print('falha no Gmail, indo pelo GitHub:', e)
    try:
        try:
            _gh('POST', '/labels', {'name': m.rotulo, 'color': 'b08a3e'})
        except Exception:
            pass
        i = _gh('POST', '/issues', {'title': m.titulo, 'body': para_markdown(m), 'labels': [m.rotulo]})
        if i.get('number'):
            _gh('PATCH', f"/issues/{i['number']}", {'state': 'closed', 'state_reason': 'completed'})
        print('aviso (issue):', m.titulo)
    except Exception as e:
        print('falha ao avisar', m.titulo, e)
