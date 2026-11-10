create extension if not exists unaccent;

drop schema if exists mart cascade;
create schema mart;

create function mart.mascarar_cpf(texto text) returns text
language sql immutable parallel safe as $$
    select regexp_replace(texto, '(?<![0-9])[0-9]{11}(?![0-9])', '***', 'g')
$$;

create table mart.emendas as
select
    codigo_emenda,
    ano_emenda as ano,
    tipo_emenda,
    nome_autor as autor,
    numero_emenda,
    localidade_aplicacao as localidade,
    localidade_tipo,
    municipio,
    codigo_municipio_ibge,
    nome_funcao as funcao,
    nome_subfuncao as subfuncao,
    nome_programa as programa,
    nome_acao as acao,
    nome_plano_orcamentario as plano_orcamentario,
    valor_empenhado,
    valor_liquidado,
    valor_pago,
    valor_restos_a_pagar_inscritos,
    valor_restos_a_pagar_cancelados,
    valor_restos_a_pagar_pagos
from staging.emendas
where uf_sigla = 'SC';

create table mart.convenios as
select
    c.codigo_emenda,
    staging.inteiro(left(c.codigo_emenda, 4))::smallint as ano_emenda,
    c.tipo_emenda,
    a.nome_autor as autor,
    c.nome_funcao as funcao,
    c.nome_subfuncao as subfuncao,
    c.localidade_gasto as localidade,
    c.localidade_tipo,
    c.municipio,
    c.data_publicacao,
    mart.mascarar_cpf(c.convenente) as convenente,
    mart.mascarar_cpf(c.objeto) as objeto,
    c.numero_convenio,
    c.valor_convenio
from staging.convenios c
left join (
    select distinct on (codigo_emenda) codigo_emenda, nome_autor
    from staging.emendas
    where codigo_emenda is not null
    order by codigo_emenda, nome_autor
) a on a.codigo_emenda = c.codigo_emenda
where c.uf_sigla = 'SC';

create table mart.pagamentos_favorecidos as
select
    p.codigo_emenda,
    staging.inteiro(left(p.codigo_emenda, 4))::smallint as ano_emenda,
    p.tipo_emenda,
    p.nome_autor as autor,
    p.competencia,
    extract(year from p.competencia)::smallint as ano_pagamento,
    case
        when p.tipo_favorecido = 'Pessoa Física' then 'Pessoa física (nome omitido)'
        else mart.mascarar_cpf(p.nome_favorecido)
    end as nome_favorecido,
    case when p.tipo_favorecido = 'Pessoa Física' then null else p.codigo_favorecido end
        as codigo_favorecido,
    p.tipo_favorecido,
    p.natureza_juridica,
    p.uf_favorecido,
    p.municipio_favorecido,
    p.valor_recebido
from staging.pagamentos_favorecido p
where p.codigo_emenda in (
    select codigo_emenda from staging.emendas where uf_sigla = 'SC' and codigo_emenda is not null
);

create table mart.transferencias_especiais as
with municipios as (
    select distinct on (chave) chave, municipio, codigo_municipio_ibge
    from (
        select replace(unaccent(upper(municipio)), 'D''OESTE', 'DO OESTE') as chave,
            municipio, codigo_municipio_ibge, 1 as ordem
        from staging.emendas
        where uf_sigla = 'SC' and municipio is not null
        union all
        select replace(unaccent(upper(municipio)), 'D''OESTE', 'DO OESTE'), municipio, null, 2
        from staging.convenios
        where uf_sigla = 'SC' and municipio is not null
    ) nomes
    order by chave, ordem, municipio
),
beneficiarios as (
    select
        nome,
        id_beneficiario,
        nome_municipio,
        case nome_municipio
            when 'BALNEARIO DE PICARRAS' then 'BALNEARIO PICARRAS'
            else replace(unaccent(upper(nome_municipio)), 'D''OESTE', 'DO OESTE')
        end as chave
    from (
        select
            *,
            case
                when nome = 'ESTADO DE SANTA CATARINA' then null
                when nome like 'MUNICIPIO DE %' then substr(nome, 14)
                else nome
            end as nome_municipio
        from staging.transferegov_beneficiarios
        where uf_sigla = 'SC'
    ) b
),
executores as (
    select
        id_plano_acao,
        string_agg(distinct nome, '; ' order by nome) as executor,
        (array_agg(objeto order by id_executor) filter (where objeto is not null))[1] as objeto
    from staging.transferegov_executores
    group by id_plano_acao
),
empenhos as (
    select
        id_plano_acao,
        sum(valor) filter (where situacao = 'Enviado') as valor_empenhado,
        sum(valor) filter (where situacao = 'Minuta de Empenho') as valor_em_minuta
    from staging.transferegov_empenhos
    group by id_plano_acao
),
planos_trabalho as (
    select distinct on (id_plano_acao) *
    from staging.transferegov_planos_trabalho
    order by id_plano_acao, id_plano_trabalho desc
)
select
    p.id_plano_acao,
    p.situacao,
    p.situacao ilike 'impedido%' as impedido,
    p.codigo_emenda,
    p.ano_emenda,
    unaccent(upper(p.nome_parlamentar)) as autor,
    b.nome as beneficiario,
    coalesce(m.municipio, b.nome_municipio) as municipio,
    m.codigo_municipio_ibge,
    x.executor,
    mart.mascarar_cpf(coalesce(p.nome_objeto, x.objeto)) as objeto,
    mart.mascarar_cpf(p.detalhamento_objeto) as detalhamento_objeto,
    p.valor_custeio,
    p.valor_investimento,
    p.valor_custeio + p.valor_investimento as valor_planejado,
    coalesce(e.valor_empenhado, 0) as valor_empenhado,
    coalesce(e.valor_em_minuta, 0) as valor_em_minuta,
    t.situacao as situacao_plano_trabalho,
    t.data_inicio_execucao,
    t.data_fim_execucao,
    mart.mascarar_cpf(p.motivo_impedimento) as motivo_impedimento
from staging.transferegov_planos_acao p
join beneficiarios b on b.id_beneficiario = p.id_beneficiario
left join municipios m on m.chave = b.chave
left join executores x on x.id_plano_acao = p.id_plano_acao
left join empenhos e on e.id_plano_acao = p.id_plano_acao
left join planos_trabalho t on t.id_plano_acao = p.id_plano_acao;

create table mart.transferencias_especiais_empenhos as
select
    e.id_plano_acao,
    t.codigo_emenda,
    t.autor,
    t.beneficiario,
    t.municipio,
    e.numero_empenho,
    e.data_emissao,
    extract(year from e.data_emissao)::smallint as ano_emissao,
    e.situacao,
    e.valor
from staging.transferegov_empenhos e
join mart.transferencias_especiais t on t.id_plano_acao = e.id_plano_acao;

create table mart.fontes as
select
    'emendas'::text as tabela,
    'Portal da Transparência (CGU)'::text as fonte,
    'EmendasParlamentares.csv'::text as arquivo,
    (select min(ano) from mart.emendas)::smallint as ano_inicio,
    (select max(ano) from mart.emendas)::smallint as ano_fim,
    (select carregado_em from raw.cargas where arquivo = 'EmendasParlamentares.csv')
        as carregado_em
union all
select
    'convenios',
    'Portal da Transparência (CGU)',
    'EmendasParlamentares_Convenios.csv',
    (select min(extract(year from data_publicacao)) from mart.convenios)::smallint,
    (select max(extract(year from data_publicacao)) from mart.convenios)::smallint,
    (select carregado_em from raw.cargas where arquivo = 'EmendasParlamentares_Convenios.csv')
union all
select
    'pagamentos_favorecidos',
    'Portal da Transparência (CGU)',
    'EmendasParlamentares_PorFavorecido.csv',
    (select min(ano_pagamento) from mart.pagamentos_favorecidos),
    (select max(ano_pagamento) from mart.pagamentos_favorecidos),
    (select carregado_em from raw.cargas where arquivo = 'EmendasParlamentares_PorFavorecido.csv');

insert into mart.fontes
select
    'transferencias_especiais',
    'Transferegov.br (API de dados abertos das Transferências Especiais)',
    'especiais/planos-acao-especiais',
    (select min(ano_emenda) from mart.transferencias_especiais),
    (select max(ano_emenda) from mart.transferencias_especiais),
    (select carregado_em from raw.cargas where arquivo = 'especiais/planos-acao-especiais')
where exists (select 1 from mart.transferencias_especiais)
union all
select
    'transferencias_especiais_empenhos',
    'Transferegov.br (API de dados abertos das Transferências Especiais)',
    'especiais/empenhos-especiais',
    (select min(ano_emissao) from mart.transferencias_especiais_empenhos),
    (select max(ano_emissao) from mart.transferencias_especiais_empenhos),
    (select carregado_em from raw.cargas where arquivo = 'especiais/empenhos-especiais')
where exists (select 1 from mart.transferencias_especiais_empenhos);

create index on mart.emendas (ano);
create index on mart.emendas (municipio);
create index on mart.emendas (codigo_emenda);
create index on mart.convenios (codigo_emenda);
create index on mart.pagamentos_favorecidos (codigo_emenda);
create index on mart.pagamentos_favorecidos (nome_favorecido);
create index on mart.transferencias_especiais (codigo_emenda);
create index on mart.transferencias_especiais (municipio);
create index on mart.transferencias_especiais (autor);
create index on mart.transferencias_especiais_empenhos (id_plano_acao);
create index on mart.transferencias_especiais_empenhos (ano_emissao);

comment on table mart.emendas is
    'Emendas parlamentares federais com destino a Santa Catarina. Cada linha é uma emenda '
    'detalhada por localidade, função, subfunção, programa, ação e plano orçamentário; uma emenda '
    '(codigo_emenda) ocupa várias linhas, então use count(distinct codigo_emenda) para contá-las. '
    'Os valores são acumulados por ano da emenda e não trazem a data do pagamento: para pagamentos '
    'por mês use pagamentos_favorecidos. Os totais por município não somam o total do estado, '
    'porque parte do dinheiro é registrada com localidade_tipo ''estado'' ou ''multiplo''.';
comment on column mart.emendas.codigo_emenda is
    'Código de 12 dígitos da emenda (ano, autor e número). Nulo quando a fonte não informa.';
comment on column mart.emendas.ano is 'Ano da emenda no orçamento (2014 a 2026; 2026 é parcial).';
comment on column mart.emendas.tipo_emenda is
    'Valores: ''Emenda Individual - Transferências com Finalidade Definida'', '
    '''Emenda Individual - Transferências Especiais'', ''Emenda de Bancada'', '
    '''Emenda de Comissão'', ''Emenda de Relator''. As emendas individuais são as duas primeiras: '
    'tipo_emenda like ''Emenda Individual%''.';
comment on column mart.emendas.autor is
    'Nome do parlamentar, da bancada ou da comissão autora, em maiúsculas. Nulo quando não informado.';
comment on column mart.emendas.numero_emenda is 'Número da emenda dentro do ano e do autor.';
comment on column mart.emendas.localidade is
    'Localidade de aplicação como na fonte: ''CIDADE - SC'', ''SANTA CATARINA (UF)'' ou ''MÚLTIPLO''.';
comment on column mart.emendas.localidade_tipo is
    '''municipio'' (aplicada em um município; municipio preenchido), ''estado'' (aplicada no estado '
    'todo, sem município) ou ''multiplo'' (vários municípios, sem detalhamento).';
comment on column mart.emendas.municipio is
    'Município de aplicação, em maiúsculas e com acento (ex.: FLORIANÓPOLIS). Nulo quando '
    'localidade_tipo não é ''municipio''.';
comment on column mart.emendas.codigo_municipio_ibge is 'Código IBGE do município de aplicação.';
comment on column mart.emendas.funcao is 'Função orçamentária (ex.: Saúde, Educação, Urbanismo).';
comment on column mart.emendas.subfuncao is 'Subfunção orçamentária.';
comment on column mart.emendas.programa is 'Programa do orçamento federal, em maiúsculas.';
comment on column mart.emendas.acao is 'Ação do orçamento federal, em maiúsculas.';
comment on column mart.emendas.plano_orcamentario is 'Plano orçamentário, em maiúsculas.';
comment on column mart.emendas.valor_empenhado is 'Valor empenhado, em reais.';
comment on column mart.emendas.valor_liquidado is 'Valor liquidado, em reais.';
comment on column mart.emendas.valor_pago is 'Valor pago, em reais.';
comment on column mart.emendas.valor_restos_a_pagar_inscritos is
    'Restos a pagar inscritos, em reais (raros valores negativos na fonte).';
comment on column mart.emendas.valor_restos_a_pagar_cancelados is
    'Restos a pagar cancelados, em reais.';
comment on column mart.emendas.valor_restos_a_pagar_pagos is 'Restos a pagar pagos, em reais.';

comment on table mart.convenios is
    'Convênios firmados com recursos de emendas parlamentares, com gasto em Santa Catarina. '
    'Não inclui transferências especiais, que não usam convênio. O ano de publicação do convênio '
    'pode ser diferente do ano da emenda.';
comment on column mart.convenios.codigo_emenda is 'Código da emenda; liga a emendas.codigo_emenda.';
comment on column mart.convenios.ano_emenda is 'Ano da emenda, extraído do código da emenda.';
comment on column mart.convenios.tipo_emenda is 'Mesmos valores de emendas.tipo_emenda.';
comment on column mart.convenios.autor is 'Autor da emenda, em maiúsculas. Nulo quando não informado.';
comment on column mart.convenios.funcao is 'Função orçamentária.';
comment on column mart.convenios.subfuncao is 'Subfunção orçamentária.';
comment on column mart.convenios.localidade is
    'Localidade do gasto como na fonte: ''CIDADE - SC'' ou ''SANTA CATARINA (UF)''.';
comment on column mart.convenios.localidade_tipo is '''municipio'' ou ''estado''.';
comment on column mart.convenios.municipio is 'Município do gasto, em maiúsculas e com acento.';
comment on column mart.convenios.data_publicacao is 'Data de publicação do convênio.';
comment on column mart.convenios.convenente is
    'Quem firmou o convênio, em maiúsculas (ex.: MUNICIPIO DE CAIBI).';
comment on column mart.convenios.objeto is 'Descrição do objeto do convênio.';
comment on column mart.convenios.numero_convenio is 'Número do convênio.';
comment on column mart.convenios.valor_convenio is
    'Valor do convênio em reais, incluindo rendimento de aplicação financeira quando houver.';

comment on table mart.pagamentos_favorecidos is
    'Pagamentos de emendas com destino a Santa Catarina, por favorecido e mês de lançamento. '
    'Os favorecidos podem estar em qualquer estado (uf_favorecido). Não una com emendas por '
    'codigo_emenda para somar valores: emendas tem várias linhas por emenda e duplicaria os '
    'totais; use autor, tipo_emenda e ano_emenda, que já estão nesta tabela. Os valores são '
    'líquidos: estornos aparecem como negativos. Pessoas físicas aparecem sem nome e sem código.';
comment on column mart.pagamentos_favorecidos.codigo_emenda is 'Código da emenda.';
comment on column mart.pagamentos_favorecidos.ano_emenda is
    'Ano da emenda, extraído do código da emenda.';
comment on column mart.pagamentos_favorecidos.tipo_emenda is 'Mesmos valores de emendas.tipo_emenda.';
comment on column mart.pagamentos_favorecidos.autor is
    'Autor da emenda, em maiúsculas. Nulo quando não informado.';
comment on column mart.pagamentos_favorecidos.competencia is
    'Primeiro dia do mês do lançamento do pagamento.';
comment on column mart.pagamentos_favorecidos.ano_pagamento is 'Ano da competência do pagamento.';
comment on column mart.pagamentos_favorecidos.nome_favorecido is
    'Nome do favorecido, em maiúsculas. ''Pessoa física (nome omitido)'' para pessoas físicas.';
comment on column mart.pagamentos_favorecidos.codigo_favorecido is
    'CNPJ do favorecido pessoa jurídica. Nulo para pessoas físicas.';
comment on column mart.pagamentos_favorecidos.tipo_favorecido is
    'Valores: ''Pessoa Jurídica'', ''Pessoa Física'', ''Unidade Gestora'', ''Inscrição Genérica'', '
    '''Inválido''. Nulo quando não informado.';
comment on column mart.pagamentos_favorecidos.natureza_juridica is
    'Natureza jurídica do favorecido (ex.: Município, Associação Privada).';
comment on column mart.pagamentos_favorecidos.uf_favorecido is 'UF do favorecido (sigla).';
comment on column mart.pagamentos_favorecidos.municipio_favorecido is
    'Município do favorecido, em maiúsculas e com acento.';
comment on column mart.pagamentos_favorecidos.valor_recebido is
    'Valor recebido no lançamento, em reais; negativo em estornos.';

comment on table mart.transferencias_especiais is
    'Planos de ação das transferências especiais (emendas ''Emenda Individual - Transferências '
    'Especiais'') com destino a Santa Catarina, vindos do Transferegov. Uma linha por plano de '
    'ação (id_plano_acao); uma emenda (codigo_emenda) tem vários planos, um para cada ente '
    'beneficiário. Diz para quem o dinheiro foi (beneficiario, municipio) e para quê (objeto), '
    'com o valor planejado e o que foi empenhado. Pagamentos por favorecido estão em '
    'pagamentos_favorecidos. Liga a emendas por codigo_emenda, mas emendas tem várias linhas por '
    'emenda: não una as duas tabelas para somar valores.';
comment on column mart.transferencias_especiais.id_plano_acao is 'Identificador do plano de ação.';
comment on column mart.transferencias_especiais.situacao is
    'Situação do plano de ação, como na fonte. Valores: ''CIENTE'', ''IMPEDIDO'', '
    '''Impedido por Rejeição do Plano de Trabalho'', '
    '''Plano de Trabalho em Elaboração/Aguardando Envio para Análise'' (ainda não impedido).';
comment on column mart.transferencias_especiais.impedido is
    'Verdadeiro quando o plano está impedido (situacao ''IMPEDIDO'' ou ''Impedido por Rejeição '
    'do Plano de Trabalho''). Para contar ou filtrar impedidos, use esta coluna.';
comment on column mart.transferencias_especiais.codigo_emenda is
    'Código de 12 dígitos da emenda; liga a emendas.codigo_emenda.';
comment on column mart.transferencias_especiais.ano_emenda is 'Ano da emenda.';
comment on column mart.transferencias_especiais.autor is
    'Parlamentar autor da emenda, em maiúsculas e sem acento, como em emendas.autor.';
comment on column mart.transferencias_especiais.beneficiario is
    'Ente que recebe o recurso, como na fonte (ex.: MUNICIPIO DE ITAJAI, ESTADO DE SANTA CATARINA).';
comment on column mart.transferencias_especiais.municipio is
    'Município do beneficiário, no mesmo formato de emendas.municipio (maiúsculas, com acento). '
    'Sem acento quando o município não aparece nas emendas do Portal. Nulo nos planos do estado.';
comment on column mart.transferencias_especiais.codigo_municipio_ibge is
    'Código IBGE do município, quando ele aparece nas emendas do Portal.';
comment on column mart.transferencias_especiais.executor is
    'Quem executa o plano, como na fonte; vários executores separados por ponto e vírgula.';
comment on column mart.transferencias_especiais.objeto is
    'O que o recurso financia (ex.: Pavimentação de estradas vicinais). Quando a fonte não '
    'classifica o objeto, vem do que o executor declarou. Nulo quando nenhum dos dois existe.';
comment on column mart.transferencias_especiais.detalhamento_objeto is
    'Detalhamento do objeto, quando a fonte informa.';
comment on column mart.transferencias_especiais.valor_custeio is
    'Valor do plano destinado a custeio, em reais.';
comment on column mart.transferencias_especiais.valor_investimento is
    'Valor do plano destinado a investimento, em reais.';
comment on column mart.transferencias_especiais.valor_planejado is
    'valor_custeio + valor_investimento: valor previsto no plano, em reais. Não é valor pago.';
comment on column mart.transferencias_especiais.valor_empenhado is
    'Soma dos empenhos enviados do plano, em reais. Não inclui as minutas.';
comment on column mart.transferencias_especiais.valor_em_minuta is
    'Soma das minutas de empenho do plano, em reais: empenhos preparados e ainda não enviados.';
comment on column mart.transferencias_especiais.situacao_plano_trabalho is
    'Situação do plano de trabalho (ex.: Aprovado, Em Complementação, Legado ADPF 854 STF / NT - '
    'TCU). Nulo quando o plano não tem plano de trabalho.';
comment on column mart.transferencias_especiais.data_inicio_execucao is
    'Data de início da execução prevista no plano de trabalho.';
comment on column mart.transferencias_especiais.data_fim_execucao is
    'Data de fim da execução prevista no plano de trabalho.';
comment on column mart.transferencias_especiais.motivo_impedimento is
    'Motivo do impedimento, quando o plano foi impedido.';

comment on table mart.transferencias_especiais_empenhos is
    'Empenhos dos planos de ação das transferências especiais de Santa Catarina, um por linha, '
    'com a data de emissão. Use para empenhos por ano ou mês; o total por plano está em '
    'transferencias_especiais.valor_empenhado. Inclui minutas de empenho (situacao), que ainda '
    'não foram enviadas.';
comment on column mart.transferencias_especiais_empenhos.id_plano_acao is
    'Plano de ação; liga a transferencias_especiais.id_plano_acao.';
comment on column mart.transferencias_especiais_empenhos.codigo_emenda is
    'Código da emenda; liga a emendas.codigo_emenda.';
comment on column mart.transferencias_especiais_empenhos.autor is
    'Autor da emenda, em maiúsculas e sem acento.';
comment on column mart.transferencias_especiais_empenhos.beneficiario is
    'Ente que recebe o recurso.';
comment on column mart.transferencias_especiais_empenhos.municipio is
    'Município do beneficiário, como em transferencias_especiais.municipio.';
comment on column mart.transferencias_especiais_empenhos.numero_empenho is 'Número do empenho.';
comment on column mart.transferencias_especiais_empenhos.data_emissao is
    'Data de emissão do empenho.';
comment on column mart.transferencias_especiais_empenhos.ano_emissao is
    'Ano de emissão do empenho.';
comment on column mart.transferencias_especiais_empenhos.situacao is
    'Valores: ''Enviado'' (empenho efetivado) e ''Minuta de Empenho'' (ainda não enviado).';
comment on column mart.transferencias_especiais_empenhos.valor is 'Valor do empenho, em reais.';

comment on table mart.fontes is 'Origem e cobertura de cada tabela do mart.';
comment on column mart.fontes.tabela is 'Nome da tabela do mart.';
comment on column mart.fontes.fonte is 'Órgão responsável pelos dados.';
comment on column mart.fontes.arquivo is 'Arquivo de origem.';
comment on column mart.fontes.ano_inicio is 'Primeiro ano com dados.';
comment on column mart.fontes.ano_fim is 'Último ano com dados.';
comment on column mart.fontes.carregado_em is 'Data e hora da carga do arquivo no banco.';

analyze mart.emendas;
analyze mart.convenios;
analyze mart.pagamentos_favorecidos;
analyze mart.transferencias_especiais;
analyze mart.transferencias_especiais_empenhos;
