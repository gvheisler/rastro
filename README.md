# Rastro

Pergunte em português para onde foi o dinheiro das emendas parlamentares destinadas a Santa Catarina.

[![CI](https://github.com/gvheisler/rastro/actions/workflows/ci.yml/badge.svg)](https://github.com/gvheisler/rastro/actions/workflows/ci.yml)
[![Licença: MIT](https://img.shields.io/badge/licen%C3%A7a-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](pyproject.toml)

## O problema

Os dados de emendas parlamentares são públicos, mas chegam em arquivos grandes, com várias tabelas ligadas por código, formatos antigos e campos sem padrão. Responder uma pergunta simples, como "quanto foi pago em emendas para Santa Catarina em 2025?", exige conhecer a estrutura dos dados e escrever consultas.

## A solução

O Rastro carrega os dados públicos em um banco Postgres e usa um agente de IA para transformar perguntas em português em consultas SQL somente leitura. A resposta mostra o SQL executado, os números e a fonte, para que qualquer resultado possa ser conferido. O agente é avaliado com um conjunto de perguntas com gabarito, e os dados são reconciliados com o painel do TCE/SC.

## Status

Em desenvolvimento.

- Pronto: Postgres local com Docker Compose, download dos dados federais e carga nas camadas `raw` e `staging`, com testes.
- Falta: transferências especiais (Transferegov), camada de consulta e checks de qualidade, reconciliação com o painel do TCE/SC, agente, avaliação e interface de chat.

## Como rodar

Requisitos: Docker, [uv](https://docs.astral.sh/uv/) e Python 3.12.

```
make setup    # sobe o Postgres (porta 5433) e instala as dependências
make ingest   # baixa os dados se necessário, carrega no banco e monta o staging
make test
```

`make ingest` pode ser repetido: cada execução recarrega as tabelas sem duplicar linhas. `make psql` abre um console no banco.

Os dados passam por duas camadas: `raw` guarda os CSVs como texto, exatamente como vieram do Portal da Transparência, e `staging` aplica tipos, trata valores ausentes e padroniza categorias. Detalhes em [`docs/data-dictionary.md`](docs/data-dictionary.md).

## Fontes dos dados

- [Portal da Transparência (CGU): emendas parlamentares](https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares)
- [Transferegov: transferências especiais](https://www.gov.br/transferegov)
- Painel do TCE/SC (Farol TCE): usado apenas para reconciliação dos valores.

Detalhes de cada arquivo, data do download e checksums em [`data/README.md`](data/README.md).

## Aviso

Projeto independente, sem vínculo com o TCE/SC, a ALESC, a CGU ou qualquer outro órgão público. Os números exibidos vêm das fontes acima e não implicam juízo sobre pessoas, empresas ou parlamentares.

## Licença

[MIT](LICENSE)
