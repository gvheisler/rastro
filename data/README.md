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
