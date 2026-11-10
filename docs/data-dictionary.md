# Dicionário de dados

Fonte: Portal da Transparência (CGU), arquivos de emendas parlamentares, baixados em 06/11/2026. Os nomes de coluna seguem os arquivos originais; o significado de cada campo está no dicionário oficial da CGU. Este documento registra o que foi verificado nos arquivos.

## Formato

- Codificação ISO-8859-1, separador `;`, valores entre aspas, linhas terminadas em CRLF. Nenhum campo contém quebra de linha.
- Decimal com vírgula e sem separador de milhar (`1450000,00`). Datas em `dd/mm/aaaa`. `Ano/Mês` em `aaaamm`.
- Ausência de informação aparece como texto, não como campo vazio: `Sem informação`, `S/I`, `-99` (código de autor), `-8` e `-3` (código de favorecido).

## Arquivos

### `EmendasParlamentares.csv`

94.827 linhas, 28 colunas. Cada linha é uma combinação de emenda, localidade de aplicação, função, subfunção, programa, ação e plano orçamentário, com os valores de execução: empenhado, liquidado, pago e restos a pagar (inscritos, cancelados e pagos).

- Anos de 2014 a 2026 (2026 parcial). Cinco tipos de emenda: individual com finalidade definida, individual de transferências especiais, de bancada, de comissão e de relator.
- Sem linhas duplicadas. Entre as 77.017 linhas com código de emenda informado, a combinação das sete colunas acima é única.
- 17.810 linhas têm `Código da Emenda` igual a `Sem informação` (11.155 delas de 2014). Elas entram nos totais, mas não se ligam aos outros arquivos.
- O código da emenda tem 12 dígitos: ano, código do autor e número da emenda.
- `Código do Autor da Emenda` vale `-99` em 1.848 emendas de comissão do autor `RELATOR GERAL`, e `S/I` quando o autor não foi informado.
- `Valor Restos A Pagar Inscritos` tem 9 valores negativos; os demais valores monetários não têm.

### `EmendasParlamentares_Convenios.csv`

85.416 linhas, 12 colunas. Convênios firmados com recursos de emendas: convenente, objeto, data de publicação e valor.

- Não tem coluna de UF. A UF está embutida em `Localidade do gasto` (`FLORIANÓPOLIS - SC`, `SANTA CATARINA (UF)`).
- Não inclui emendas de transferências especiais, que não usam convênio.
- Todos os códigos de emenda informados existem no arquivo principal.
- Datas de publicação de 1999 a 2026. O arquivo cobre convênios, não o ano da emenda.
- `Valor Convênio` inclui, quando houver, rendimento de aplicação financeira.

### `EmendasParlamentares_PorFavorecido.csv`

828.756 linhas, 13 colunas. Pagamentos por favorecido e mês de lançamento (`Ano/Mês`, de 2014-06 a 2026-11).

- `Valor Recebido` tem 1.011 valores negativos. Somar o campo dá o valor líquido.
- Não há chave natural: o mesmo favorecido recebe mais de um lançamento no mesmo mês.
- `Código do Favorecido` é o CNPJ completo para pessoa jurídica. Para pessoa física, a própria fonte já mascara o CPF (`***.548.092-**`), mas o nome do favorecido vem completo.
- `Tipo Favorecido` tem valores truncados na origem (`Inscrição Genéric` ao lado de `Inscrição Genérica`) e `Pessoa Fisica` sem acento.
- 67.048 linhas têm `Código da Emenda` igual a `Sem informação`. Dos demais códigos, todos menos dois existem no arquivo principal.
- `UF Favorecido` é a UF de quem recebe, não do destino da emenda. O Banco do Brasil, por exemplo, tem 50.172 linhas, quase todas com UF `DF`, ligadas a emendas de vários estados.

## Como identificar Santa Catarina

| Arquivo | Critério | Linhas |
| --- | --- | --- |
| Emendas | `UF = 'SANTA CATARINA'` (`Código UF IBGE = 4200000`) | 3.122 |
| Convênios | `Localidade do gasto` termina em ` - SC` ou é `SANTA CATARINA (UF)` | 4.429 |
| Por favorecido | `Código da Emenda` presente nas emendas de SC | 16.520 |

Detalhes sobre as 3.122 linhas de emendas de SC:

- 1.386 têm município (`Localidade de aplicação do recurso` no formato `CIDADE - SC`).
- 722 são de aplicação no estado inteiro (`SANTA CATARINA (UF)`, sem município).
- 1.014 têm localidade `MÚLTIPLO` e UF preenchida como SC. Entram no total do estado, mas não têm detalhamento por município.
- Não entram: localidade `Nacional` (5.383 linhas), `Exterior` e UF `Múltiplo`. Não há como atribuí-las a SC.

Para o arquivo por favorecido, `UF Favorecido = 'SC'` (30.996 linhas) não é o critério correto. Ele descreve quem recebe, não o destino da emenda: das 16.520 linhas ligadas a emendas de SC, só 12.033 têm favorecido em SC, e as outras incluem favorecidos no DF (2.416), SP (674) e PR (450). Cada código de emenda aparece com uma única UF no arquivo principal, então a ligação pelo código é inequívoca.

## Camadas no banco

`raw` e `staging` guardam o Brasil inteiro; o filtro de Santa Catarina entra na camada de consulta.

### `raw`

Uma tabela por arquivo (`emendas_parlamentares`, `emendas_convenios`, `emendas_por_favorecido`) com todas as colunas em texto, com os nomes do cabeçalho sem acento e em minúsculas (`Código da Emenda` vira `codigo_da_emenda`). Os arquivos são carregados por `COPY` na codificação original. `linha_arquivo` guarda a posição da linha no CSV, e `raw.cargas` registra arquivo, SHA-256, número de linhas e data de cada carga. Se o cabeçalho de um CSV mudar, a carga falha em vez de gravar colunas deslocadas.

### `staging`

Tabelas `emendas`, `convenios` e `pagamentos_favorecido`, com as mesmas linhas de `raw` e as regras abaixo.

| Regra | Efeito |
| --- | --- |
| Valores ausentes | `Sem informação`, `S/I` e vazio viram `NULL`. Código de favorecido negativo (`-8`, `-3`) também. |
| Valores monetários | `numeric(18,2)`, convertidos de `1450000,00`. |
| Datas | `data_publicacao` em `date`; `competencia` é o primeiro dia do mês de `Ano/Mês`. |
| UF | `uf_sigla` vem do código IBGE da UF (`staging.uf`). Nos convênios vem do sufixo da localidade ou do nome `(UF)`. |
| Município | Só quando há código IBGE. `Múltiplo` e `Sem informação` viram `NULL`. |
| `localidade_tipo` | `municipio`, `estado`, `multiplo`, `nacional`, `exterior` ou `regiao`, conforme o formato da localidade. |
| Códigos numéricos | `codigo_funcao` e `codigo_subfuncao` são inteiros; o marcador `MU` (múltiplo) vira `NULL`. |
| `tipo_favorecido` | `Pessoa Fisica` vira `Pessoa Física`, `Inscrição Genéric` vira `Inscrição Genérica` e `Sem informação` vira `NULL`. |

O nome do favorecido pessoa física é mantido no `staging`; o `mart` não o expõe.

### `mart`

Só Santa Catarina, com nomes em português sem acento. É a única camada que o agente enxerga, por um usuário Postgres somente leitura (`rastro_ro`, com `statement_timeout` de 10 s). Cada tabela e coluna tem comentário no banco (`sql/03_mart.sql`), e o prompt do agente é montado a partir deles.

| Tabela | Linhas | Conteúdo |
| --- | --- | --- |
| `emendas` | 3.122 | Emendas com destino a SC, no mesmo grão do arquivo original. |
| `convenios` | 4.429 | Convênios com gasto em SC, com `autor` e `ano_emenda` trazidos da emenda. |
| `pagamentos_favorecidos` | 16.520 | Pagamentos das emendas de SC por favorecido e mês, com `autor`, `ano_emenda` e `ano_pagamento`. |
| `fontes` | 3 | Arquivo de origem, período coberto e data da carga de cada tabela. |

Regras do `mart`:

- Pessoa física: `nome_favorecido` vira `Pessoa física (nome omitido)` e `codigo_favorecido` fica nulo. Sequências de 11 dígitos isoladas em nomes e objetos viram `***`.
- `valor_pago` e os demais valores de `emendas` são acumulados por ano da emenda; o pagamento mês a mês está em `pagamentos_favorecidos`.
- Em `emendas`, `localidade_tipo` separa `municipio`, `estado` e `multiplo`. Os valores por município não somam o total do estado: em 2024, por exemplo, a maior parte do valor pago está em `multiplo`.
- `emendas` tem várias linhas por emenda. Contar emendas exige `count(distinct codigo_emenda)`, e unir `emendas` com `pagamentos_favorecidos` pelo código duplica valores.

### Checks de qualidade

`make check` roda `rastro check` sobre o `mart` e sai com erro se algum check do tipo `error` falhar. Os checks `error` cobrem ano fora de 2014 até o ano atual, valores nulos ou negativos, linhas duplicadas, município sem nome, competência fora do período, pessoa física exposta, texto com formato de CPF e diferença de linhas entre `staging` e `mart`. Os checks `info` só informam particularidades da fonte: emendas e convênios sem código, estornos negativos em pagamentos, restos a pagar negativos e valor pago acima do empenhado.
