# Dicionário de dados

Fontes: Portal da Transparência (CGU), arquivos de emendas parlamentares, baixados em 06/11/2026, e API do Transferegov (transferências especiais), consultada em 10/11/2026. Os nomes de coluna seguem os da origem; o significado de cada campo está no dicionário oficial de cada fonte. Este documento registra o que foi verificado nos dados.

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

## Transferegov: transferências especiais

API de dados abertos do módulo de Transferências Especiais do Transferegov: `https://api-publica.transferegov.gestao.gov.br/especiais` ([documentação](https://api-publica.transferegov.gestao.gov.br/especiais/docs)). Cada endpoint devolve JSON paginado (`pagina` e `tamanho_da_pagina`, no máximo 200, com `total_items`). A API informou atualização em 10/11/2026 em `/data-atualizacao`. Os valores vêm como número decimal com ponto.

| Endpoint | Conteúdo | Linhas de SC |
| --- | --- | --- |
| `beneficiarios-especiais` | Entes beneficiários: UF, nome e CNPJ | 296 |
| `planos-acao-especiais` | Planos de ação: emenda, valores, objeto e situação | 3.654 |
| `executores-especiais` | Quem executa cada plano e o objeto que declarou | 3.616 |
| `planos-trabalho-especiais` | Situação e datas de execução | 3.608 |
| `empenhos-especiais` | Empenhos de cada plano | 3.693 |

Os demais endpoints (documentos hábeis, ordens bancárias, gestão financeira, metas, devoluções, relatórios de gestão) não são carregados. De cada endpoint ficam só os campos usados: e-mail do órgão, banco, agência e conta, classificação orçamentária e justificativas em texto livre nunca chegam ao banco.

### Como identificar Santa Catarina

Os planos não têm filtro de UF na API. O Rastro pede os beneficiários com `uf_beneficiario=SC` (e confere a UF ao receber), baixa todos os planos e fica com os desses beneficiários; executores, planos de trabalho e empenhos são filtrados pelos planos de SC. Por isso o `raw` do Transferegov guarda só Santa Catarina, ao contrário dos CSVs, que ficam inteiros.

### O que foi verificado

- A paginação é completa: os 58.990 planos do Brasil chegaram com ids únicos e em número igual a `total_items`. Em um teste isolado a API respondeu HTTP 500 uma vez em uma página que logo depois respondeu normalmente; o cliente repete a requisição até cinco vezes e falha se o total recebido diferir de `total_items`.
- A chave com o Portal é `numero_emenda_parlamentar_plano_acao`, com 12 dígitos, igual ao `codigo_emenda`. Das 195 emendas de transferências especiais de SC do Portal, todas estão na API. A API tem 213 códigos para SC, 18 deles ausentes do Portal (emendas de 2020 a 2026).
- Uma emenda tem vários planos: 213 códigos para 3.654 planos, um por beneficiário e objeto. Os planos são de 2020 a 2026 e `ano_plano` é igual a `ano_emenda` em todos.
- A soma dos valores dos planos (`valor_custeio` mais `valor_investimento`) é R$ 1.518.029.517,40, igual à soma dos empenhos.
- Situação do plano: 3.394 `CIENTE`, 207 `IMPEDIDO`, 11 `Impedido por Rejeição do Plano de Trabalho` e 42 `Plano de Trabalho em Elaboração/Aguardando Envio para Análise`.
- Empenhos: um ou dois por plano, todos `Empenho Original`, sem valores negativos. 3.423 estão `Enviado` (R$ 1.391.396.093,48) e 270 são `Minuta de Empenho` (R$ 126.633.423,92), ainda não enviados.
- Executores: de zero a dois por plano (48 planos não têm). Em 327 casos o nome do executor é diferente do beneficiário. Planos de trabalho: zero ou um por plano (46 planos não têm).
- Objeto: `nome_objeto` e `detalhamento_objeto` vêm vazios em 2.339 planos; em 2.332 deles o executor declarou um objeto (`objeto_executor`), em texto livre que chega a 3 mil caracteres. Sete planos ficam sem objeto.
- `objeto_executor` tem uma sequência de 11 dígitos; o `mart` mascara essas sequências em todo texto livre.
- A API não traz código IBGE. O município está no nome do beneficiário (`MUNICIPIO DE ITA`, `NAVEGANTES`), sem acento, e o `mart` o casa com os nomes do Portal.

### Diferenças em relação ao Portal

Observações da comparação por `codigo_emenda`; a reconciliação completa fica para a etapa com o painel do TCE/SC.

- Para as 195 emendas em comum, o empenhado do Portal é igual ao empenhado enviado da API em 166 e diferente em 29. A soma do Portal é R$ 1.243.538.036,50 e a da API, R$ 1.241.341.952,18. A causa não foi investigada.
- O autor tem a mesma pessoa nos dois lados, mas o Portal escreve em maiúsculas e sem acento (`JOAO DA SILVA`, para `João da Silva`) e a API não. Em uma emenda (`202529250007`) os nomes diferem: o Portal registra a parlamentar que sucedeu a autora original, e a API, a autora original.
- No Portal, a maior parte do que foi pago em transferências especiais não tem município: em 2024, R$ 245.450.997,00 dos R$ 255.750.997,00 pagos estão com localidade `multiplo`. A API diz para qual município cada plano foi, mas só com valores planejados e empenhados, não pagos.

## Camadas no banco

Para os arquivos do Portal, `raw` e `staging` guardam o Brasil inteiro e o filtro de Santa Catarina entra na camada de consulta. O Transferegov entra já filtrado por Santa Catarina.

### `raw`

Uma tabela por arquivo (`emendas_parlamentares`, `emendas_convenios`, `emendas_por_favorecido`) com todas as colunas em texto, com os nomes do cabeçalho sem acento e em minúsculas (`Código da Emenda` vira `codigo_da_emenda`). Os arquivos são carregados por `COPY` na codificação original. `linha_arquivo` guarda a posição da linha no CSV, e `raw.cargas` registra arquivo, SHA-256, número de linhas e data de cada carga. Se o cabeçalho de um CSV mudar, a carga falha em vez de gravar colunas deslocadas.

O Transferegov entra em cinco tabelas `transferegov_*`, com os mesmos nomes de campo da API e os valores como texto, só de Santa Catarina. Se a API deixar de enviar um dos campos usados, a carga falha sem alterar nada; campos novos são ignorados. Cada carga registra em `raw.cargas` o endpoint, o número de linhas, o SHA-256 do conteúdo e a data de atualização informada pela API (`atualizado_na_fonte`). A API é baixada antes de qualquer escrita, e as cinco tabelas são trocadas numa única transação.

### `staging`

Tabelas `emendas`, `convenios` e `pagamentos_favorecido`, com as mesmas linhas de `raw` e as regras abaixo, e as cinco tabelas `transferegov_*`, com ids inteiros, valores `numeric(18,2)` e datas em `date`.

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

O nome do favorecido pessoa física é mantido no `staging`; o `mart` não o expõe. O `staging` do Transferegov mantém todos os campos carregados, inclusive os que o `mart` deixa de fora.

### `mart`

Só Santa Catarina, com nomes em português sem acento. É a única camada que o agente enxerga, por um usuário Postgres somente leitura (`rastro_ro`, com `statement_timeout` de 10 s). Cada tabela e coluna tem comentário no banco (`sql/03_mart.sql`), e o prompt do agente é montado a partir deles.

| Tabela | Linhas | Conteúdo |
| --- | --- | --- |
| `emendas` | 3.122 | Emendas com destino a SC, no mesmo grão do arquivo original. |
| `convenios` | 4.429 | Convênios com gasto em SC, com `autor` e `ano_emenda` trazidos da emenda. |
| `pagamentos_favorecidos` | 16.520 | Pagamentos das emendas de SC por favorecido e mês, com `autor`, `ano_emenda` e `ano_pagamento`. |
| `transferencias_especiais` | 3.654 | Um plano de ação das transferências especiais por linha: beneficiário, município, objeto, situação, valor planejado e empenhado. |
| `transferencias_especiais_empenhos` | 3.693 | Um empenho por linha, com data de emissão. |
| `fontes` | 5 | Fonte, endpoint ou arquivo de origem, período coberto e data da carga de cada tabela. |

Regras do `mart`:

- Pessoa física: `nome_favorecido` vira `Pessoa física (nome omitido)` e `codigo_favorecido` fica nulo. Sequências de 11 dígitos isoladas em nomes e objetos viram `***`.
- `valor_pago` e os demais valores de `emendas` são acumulados por ano da emenda; o pagamento mês a mês está em `pagamentos_favorecidos`.
- Em `emendas`, `localidade_tipo` separa `municipio`, `estado` e `multiplo`. Os valores por município não somam o total do estado: em 2024, por exemplo, a maior parte do valor pago está em `multiplo`.
- `emendas` tem várias linhas por emenda. Contar emendas exige `count(distinct codigo_emenda)`, e unir `emendas` com `pagamentos_favorecidos` pelo código duplica valores.
- `transferencias_especiais` liga a `emendas` por `codigo_emenda`, mas uma emenda tem várias linhas em `emendas` e vários planos; a união duplica valores nos dois lados.
- `transferencias_especiais` não tem valor pago. `valor_planejado` é custeio mais investimento do plano; `valor_empenhado` soma só os empenhos `Enviado`, e `valor_em_minuta`, as minutas. `impedido` é verdadeiro para as situações `IMPEDIDO` e `Impedido por Rejeição do Plano de Trabalho`.
- `autor` segue o formato do Portal (maiúsculas e sem acento). `municipio` usa a grafia do Portal quando o município aparece nas emendas ou nos convênios, com dois ajustes de grafia (`D'OESTE` e `DO OESTE` tratados como iguais, e `BALNEARIO DE PICARRAS`). Quatro municípios (28 planos) não têm emenda no Portal: ficam sem acento e sem código IBGE. Nos planos do estado, `municipio` é nulo.
- `objeto` é o objeto classificado no plano e, quando não há, o que o executor declarou. Sequências de 11 dígitos em textos livres viram `***`.

### Checks de qualidade

`make check` roda `rastro check` sobre o `mart` e sai com erro se algum check do tipo `error` falhar. Os checks `error` cobrem ano fora de 2014 até o ano atual, valores nulos ou negativos, linhas duplicadas, município sem nome, competência fora do período, pessoa física exposta, texto com formato de CPF e diferença de linhas entre `staging` e `mart`, incluindo planos duplicados e valores nulos ou negativos nas transferências especiais. Os checks `info` só informam particularidades da fonte: emendas e convênios sem código, estornos negativos em pagamentos, restos a pagar negativos, valor pago acima do empenhado, planos com minutas de empenho e municípios do Transferegov sem emenda no Portal.
