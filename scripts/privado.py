"""Guarda cifrados os dados que não podem ficar públicos.

  python scripts/privado.py abrir   -> decifra data/p/*.bin e devolve as versões completas dos arquivos
  python scripts/privado.py fechar  -> cifra as versões completas em data/p/ e deixa no repositório só a versão limpa;
                                       falha (e nada é publicado) se sobrar qualquer termo protegido

Segredos usados (Settings > Secrets do repositório): PAINEL_CHAVE (senha) e PRIVADO_JSON
({"termos": [...], "regex": [...], "inteiros": [...], "fundos": [...], "alertas": {...}}).
Cifra: AES-256-GCM, chave PBKDF2-SHA256 (200 mil voltas); conteúdo comprimido com gzip.
"""
import glob, gzip, hashlib, hmac, json, os, re, sys

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA = os.path.join(RAIZ, 'data', 'p')
SAL = b'painel-fundos/p1'
SENHA = os.environ.get('PAINEL_CHAVE', '')
CFG = json.loads(os.environ.get('PRIVADO_JSON') or '{}')
if not SENHA or not CFG:
    print('sem segredos: nada a fazer'); sys.exit(0)

CHAVE = hashlib.pbkdf2_hmac('sha256', SENHA.encode(), SAL, 200_000, 32)
AES = AESGCM(CHAVE)
TERMOS = [t for t in CFG.get('termos', []) if t]
RX = re.compile('|'.join([re.escape(t) for t in TERMOS] + CFG.get('regex', [])), re.I)
INTEIROS = [os.path.normpath(p) for p in CFG.get('inteiros', [])]   # arquivos/pastas 100% privados (glob)


def nome_bin(rel):
    return hmac.new(CHAVE, rel.encode(), hashlib.sha256).hexdigest()[:24] + '.bin'


def cifra(rel, dados):
    z = gzip.compress(dados, mtime=0)
    nonce = hmac.new(CHAVE, rel.encode() + b'\0' + z, hashlib.sha256).digest()[:12]   # determinístico: mesmo conteúdo, mesmo arquivo
    return nonce + AES.encrypt(nonce, z, rel.encode())


def decifra(rel, blob):
    return gzip.decompress(AES.decrypt(blob[:12], blob[12:], rel.encode()))


def arquivos():
    for p in glob.glob(os.path.join(RAIZ, '**', '*'), recursive=True):
        rel = os.path.relpath(p, RAIZ)
        if os.path.isdir(p) or rel.startswith(('.git' + os.sep, 'data' + os.sep + 'p' + os.sep, 'painel' + os.sep)):
            continue
        if rel.endswith(('.json', '.csv', '.txt', '.md', '.yml', '.py', '.html')):
            yield rel


def inteiro(rel):
    return RX.search(rel) or any(rel == g or rel.startswith(g + os.sep) or glob.fnmatch.fnmatch(rel, g) for g in INTEIROS)


def limpa(v):
    """Tira de um JSON tudo o que menciona os termos protegidos."""
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            if RX.search(str(k)) or k in CFG.get('chaves', []):
                continue
            y = limpa(x)
            if isinstance(x, (str, int, float)) and RX.search(json.dumps(x, ensure_ascii=False)):
                y = None
            out[k] = y
        return out
    if isinstance(v, list):
        out = []
        for x in v:
            if isinstance(x, (str, int, float)) and RX.search(str(x)):
                continue                                  # item que é o próprio fundo
            if isinstance(x, dict) and any(isinstance(y, (str, int, float)) and RX.search(str(y)) for y in x.values()):
                continue                                  # registro do fundo (cnpj/nome no próprio registro)
            if isinstance(x, list) and any(isinstance(y, (str, int, float)) and RX.search(str(y)) for y in x):
                continue                                  # linha de tabela do fundo
            out.append(limpa(x))
        return out
    return v


def abrir():
    idx = os.path.join(PASTA, 'i.bin')
    if not os.path.exists(idx):
        print('sem dados privados ainda'); return
    for t in TERMOS:
        print('::add-mask::' + t)
    lista = json.loads(decifra('i', open(idx, 'rb').read()))
    for rel in lista:
        p = os.path.join(RAIZ, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, 'wb').write(decifra(rel, open(os.path.join(PASTA, nome_bin(rel)), 'rb').read()))
    print('abertos:', len(lista))


def fechar():
    os.makedirs(PASTA, exist_ok=True)
    novos, lista = {}, []
    for rel in sorted(arquivos()):
        p = os.path.join(RAIZ, rel)
        bruto = open(p, 'rb').read()
        txt = bruto.decode('utf-8', 'replace')
        if inteiro(rel):
            lista.append(rel); novos[nome_bin(rel)] = cifra(rel, bruto); os.remove(p); continue
        if not RX.search(txt) or rel.startswith(('scripts' + os.sep, '.github' + os.sep)):
            continue
        lista.append(rel); novos[nome_bin(rel)] = cifra(rel, bruto)
        if rel.endswith('.json'):
            limpo = json.dumps(limpa(json.loads(txt)), ensure_ascii=False, separators=(',', ':'))
        else:
            limpo = '\n'.join(l for l in txt.split('\n') if not RX.search(l))
        open(p, 'w', encoding='utf-8').write(limpo)
    novos['i.bin'] = cifra('i', json.dumps(lista).encode())
    for f in os.listdir(PASTA):
        if f not in novos:
            os.remove(os.path.join(PASTA, f))
    for f, b in novos.items():
        q = os.path.join(PASTA, f)
        if not os.path.exists(q) or open(q, 'rb').read() != b:
            open(q, 'wb').write(b)
    for d in sorted(glob.glob(os.path.join(RAIZ, 'data', '**'), recursive=True), reverse=True):   # pastas que ficaram vazias
        if os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)
    # conferência final: nada protegido pode sobrar fora de data/p
    sobra = [rel for rel in arquivos() if not rel.startswith(('scripts' + os.sep, '.github' + os.sep))
             and (inteiro(rel) or RX.search(open(os.path.join(RAIZ, rel), encoding='utf-8', errors='replace').read()))]
    if sobra:
        print('ERRO: ainda há conteúdo protegido em', len(sobra), 'arquivo(s); nada será publicado'); sys.exit(1)
    print('fechados:', len(lista))


if __name__ == '__main__':
    {'abrir': abrir, 'fechar': fechar}[sys.argv[1]]()
