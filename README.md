# painel-fundos

Robôs que mantêm o painel atualizado sozinho, só com **dados públicos**. Tudo roda no GitHub Actions (grátis para repositório público); o painel lê os resultados ao abrir.

| Robô (aba Actions) | Quando roda | O que faz | Onde publica |
|---|---|---|---|
| **Atualiza peers (CVM)** | seg-sáb 7h17 e seg-sex 19h47 | informe diário da CVM: retornos, PL e captação dos peers; ficha de cada fundo (cadastro, lâmina, risco); panorama da indústria; radar de concorrentes; Focus; histórico próprio; avisos por e-mail | `data/` |
| **Cotações (a cada minuto)** | dias úteis 9h-19h a cada minuto; fora disso, de hora em hora | bolsas, câmbio, commodities, juros, ações do Ibovespa e curva DI (TradingView) | ramo `cotacoes` |
| **Espelho das fontes do painel** | dias úteis 7h-22h a cada 10 min; fim de semana, 2 vezes por dia | abre o próprio painel (`painel/painel.html`) num navegador e guarda as respostas de Banco Central, Tesouro, IBGE, ANBIMA, B3, notícias, GDELT etc. | ramo `espelho` |
| **Carteira dos peers (CDA da CVM)** | toda segunda | composição das carteiras (olhando através dos fundos master), mudanças e consolidado | `data/carteiras.json` |
| **Avisos de mercado** | a cada 30 min, 10h-18h30 | dólar e Ibovespa contra os limites de `alertas.json` | issues (e-mail) |

## Arquivos que você pode editar

- `fundos.json`: lista de peers (nome e CNPJ).
- `alertas.json`: limites dos avisos por e-mail (troque por `null` para desligar).

## Avisos por e-mail

Os robôs abrem uma *issue* marcando o dono da conta; o GitHub manda e-mail. O resumo diário sai de manhã em dias úteis.

## Fontes

CVM (dados abertos: informe diário, cadastro, lâmina, CDA), Banco Central (SGS, Focus), TradingView (cotações e DI), Yahoo Finance e demais fontes que o painel já usa.
Retornos dos fundos calculados pela cota (líquidos de taxas). Mesma convenção do Comdinheiro para as janelas (conferido em 19/11/2026).

## Custo

Repositório **público**: o GitHub Actions não consome os minutos do plano grátis (eles só valem para repositórios privados). Não torne este repositório privado, ou os robôs passam a gastar a cota de 2.000 minutos por mês. Os horários foram limitados ao período de uso do painel para não sobrecarregar os servidores do GitHub.
