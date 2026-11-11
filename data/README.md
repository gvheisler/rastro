# Dados

`data/raw/` e `data/processed/` não são versionados. Este arquivo registra a origem dos dados.

## Emendas parlamentares federais

Portal da Transparência (CGU): https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares

Baixado em 06/11/2026. Para baixar de novo (sobrescreve `data/raw/` e imprime a tabela abaixo):

```
uv run python scripts/download_federal.py
```

O script usa o link direto `https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares/UNICO`, que redireciona para o zip em `dadosabertos-download.cgu.gov.br`.

| Arquivo | Linhas | Tamanho | SHA-256 |
| --- | --- | --- | --- |
| `EmendasParlamentares.csv` | 94.827 | 47,5 MB | `f999db9e0ac7e6ccb704fecc86af9e125ae06fd3fc6fe11c3002afabb97ff953` |
| `EmendasParlamentares_Convenios.csv` | 85.416 | 26,0 MB | `de3f439d69786e402226ff1783f5b2047fc0aec020fc935006286644469cb454` |
| `EmendasParlamentares_PorFavorecido.csv` | 828.756 | 182,9 MB | `5b159ba159e53c6e66357079243b3533ab74e8a58c90051d89ded8cf860f51ed` |

Formato: ISO-8859-1, separador `;`, aspas duplas, linhas terminadas em CRLF, decimal com vírgula e datas em dd/mm/aaaa. Colunas e regras de filtro de SC em [`docs/data-dictionary.md`](../docs/data-dictionary.md).

## Transferências especiais (Transferegov)

API de dados abertos do módulo de Transferências Especiais do Transferegov: https://api-publica.transferegov.gestao.gov.br/especiais (documentação em `/especiais/docs`). Não há arquivo para baixar: `make ingest` consulta a API e carrega só Santa Catarina em `raw.transferegov_*`. Para pular o Transferegov e reconstruir com o que já está no banco: `uv run rastro ingest --skip-transferegov`. A URL base pode ser trocada em `TRANSFEREGOV_BASE_URL` no `.env`.

Consultada em 10/11/2026; a API informou atualização em 10/11/2026.

| Endpoint | Linhas de SC |
| --- | --- |
| `beneficiarios-especiais` | 296 |
| `planos-acao-especiais` | 3.654 |
| `executores-especiais` | 3.616 |
| `planos-trabalho-especiais` | 3.608 |
| `empenhos-especiais` | 3.693 |

Como não há arquivo, o SHA-256 de cada carga (do conteúdo recebido, ordenado pelo id) fica em `raw.cargas`, junto com o número de linhas e a data de atualização da API. Os campos carregados e as verificações estão em [`docs/data-dictionary.md`](../docs/data-dictionary.md).

## Painel do TCE/SC (reconciliação)

Painel Emendas Parlamentares do Farol TCE/SC: https://paineistransparencia.tce.sc.gov.br/extensions/appEmendasParlamentares/index.html

Exportado em 10/11/2026; o painel informava última atualização em 10/11/2026 às 10:30. Para exportar de novo: na aba "Detalhamento", use o botão de download da tabela "Detalhamento das Emendas Parlamentares", sem filtros. O painel gera um `.xlsx` em um link temporário do mesmo domínio. Salve em `data/raw/` com a data no nome.

| Arquivo | Linhas | Tamanho | SHA-256 |
| --- | --- | --- | --- |
| `tce_painel_emendas_detalhamento_2026-11-10.xlsx` | 37.776 | 2,7 MB | `9e68999caff4362d70e26e03abf103c44d81cfb699a19b8134ecedb20625d6b0` |

Uma aba, 13 colunas: Ente Autor, Localidade do Beneficiário, Código do Autor, Autor, Ano, Emenda, Razão Social do Beneficiário, CNPJ Beneficiário, Custeio, Investimento, Descrição Objeto, Data Aprovação e Data Atualização Cadastral. O valor de cada linha é Custeio mais Investimento.

O painel cobre emendas federais, estaduais e municipais com impacto em Santa Catarina, e os valores são pagos. Emendas federais e estaduais só aparecem quando chegam à fase de pagamento. As federais são as linhas com Ente Autor `UNIAO`. O arquivo não é carregado no banco; serve só para conferir os valores do Portal.

## Amostra de teste

`tests/fixtures/` tem uma amostra dos três arquivos, no mesmo formato: cerca de 260 linhas de SC e 40 de outros estados, mais as linhas relacionadas nos outros dois arquivos. Pessoas físicas são mascaradas e linhas com sequência de 11 dígitos no nome são descartadas. Para gerar de novo: `uv run python scripts/make_fixture.py`.

`tests/fixtures/transferegov/` tem uma amostra das respostas da API: 79 planos (a maioria de SC e dois de outro estado) com os executores, planos de trabalho e empenhos deles, incluindo os planos das emendas de transferência especial presentes na amostra do Portal. Planos com sequência de 11 dígitos em algum texto são descartados. Para gerar de novo, com acesso à API: `uv run python scripts/make_fixture_transferegov.py`.
