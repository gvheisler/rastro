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

- Pronto: Postgres local com Docker Compose, download dos dados federais, carga das transferências especiais do Transferegov, camadas `raw`, `staging` e `mart` (Santa Catarina), checks de qualidade, agente texto→SQL com modelo local e chat em Streamlit, com testes.
- Falta: reconciliação com o painel do TCE/SC, avaliação com perguntas e gabarito, e a comparação com a API do Claude.

## Como rodar

Requisitos: Docker, [uv](https://docs.astral.sh/uv/), Python 3.12 e [Ollama](https://ollama.com) com o modelo `qwen3:8b` (`ollama pull qwen3:8b`).

```
make setup    # sobe o Postgres (porta 5433) e instala as dependências
make ingest   # baixa os dados federais se necessário, consulta o Transferegov e monta raw, staging e mart
make check    # checks de qualidade sobre o mart
make model    # cria o modelo rastro-sql no Ollama (qwen3:8b com contexto de 8192 tokens)
make app      # abre o chat em http://localhost:8501
make test
```

`make ingest` pode ser repetido: cada execução recarrega as tabelas sem duplicar linhas. A consulta ao Transferegov leva alguns minutos; `uv run rastro ingest --skip-transferegov` reconstrói sem ela, com o que já está no banco. `make psql` abre um console no banco. Para perguntar pelo terminal: `uv run rastro ask "Quanto foi pago em emendas em 2024?"`.

Os dados passam por três camadas: `raw` guarda os CSVs do Portal da Transparência e as respostas da API do Transferegov (só Santa Catarina) como texto, exatamente como vieram; `staging` aplica tipos, trata valores ausentes e padroniza categorias; `mart` tem só Santa Catarina, com nomes em português e pessoas físicas sem nome. Detalhes em [`docs/data-dictionary.md`](docs/data-dictionary.md).

## Como o agente responde

1. Uma triagem simples recusa, antes do modelo, pedidos para alterar dados, pedir CPF ou acusar pessoas.
2. O modelo recebe o esquema do `mart` e escolhe entre quatro ferramentas: `run_sql`, `find_values` (como um nome está escrito nos dados), `ask_clarification` e `refuse`.
3. Todo SQL passa pelo `sql_guard`: uma única instrução `SELECT`, só tabelas do `mart`, sem funções de sistema (como `pg_sleep` ou `current_setting`), `AND` e `OR` com parênteses e `LIMIT` de no máximo 200 linhas. A consulta roda com um usuário Postgres somente leitura e limite de 10 s.
4. A resposta mostra o texto, o SQL, a tabela com o resultado e a fonte. Resultado vazio vira "não encontrei" e valores do texto que não aparecem no resultado são sinalizados.
5. Cada pergunta, SQL, tempo e modelo ficam em `logs/agent.jsonl`.

O cliente usa a API de chat compatível com OpenAI. Foi testado com o Ollama; outro servidor compatível, como o vLLM, deve funcionar ajustando `LLM_BASE_URL`, `LLM_MODEL` e `LLM_EXTRA_BODY` no `.env`.

## Fontes dos dados

- [Portal da Transparência (CGU): emendas parlamentares](https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares)
- [Transferegov: API de dados abertos das transferências especiais](https://api-publica.transferegov.gestao.gov.br/especiais/docs)
- Painel do TCE/SC (Farol TCE): usado apenas para reconciliação dos valores.

Detalhes de cada arquivo, data do download e checksums em [`data/README.md`](data/README.md).

## Aviso

Projeto independente, sem vínculo com o TCE/SC, a ALESC, a CGU ou qualquer outro órgão público. Os números exibidos vêm das fontes acima e não implicam juízo sobre pessoas, empresas ou parlamentares.

## Licença

[MIT](LICENSE)
