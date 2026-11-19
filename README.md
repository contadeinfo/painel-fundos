# painel-fundos

Robô que atualiza, todo dia útil, o comparativo de fundos de ações (Relatório Peers) a partir de **dados públicos**:

- **CVM**: informe diário de fundos (cota, patrimônio, captação e resgate) — https://dados.cvm.gov.br/dataset/fi-doc-inf_diario
- **Banco Central**: CDI (SGS 12)
- **Yahoo Finance**: Ibovespa

Arquivos:

- `fundos.json`: lista de fundos (nome e CNPJ). Para incluir ou tirar um fundo, edite este arquivo.
- `scripts/atualiza.py`: baixa e calcula.
- `data/peers.json`: resultado (lido pelo painel).
- `data/cvm/`: cópia enxuta do informe da CVM, só com os fundos da lista.

Para rodar na hora: aba **Actions** → *Atualiza peers (CVM)* → **Run workflow**.

Retornos calculados pela cota (líquidos de taxas), na última data com cota da maioria dos fundos. Captação = captação − resgates desde 1º de janeiro. Pode diferir ligeiramente de provedores pagos por convenções de data.
