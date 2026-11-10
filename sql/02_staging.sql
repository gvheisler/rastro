drop schema if exists staging cascade;
create schema staging;

create function staging.nulo(valor text) returns text
language sql immutable parallel safe as $$
    select case
        when btrim(valor) in ('', 'S/I', 'Sem informação', 'SEM INFORMACAO') then null
        else btrim(valor)
    end
$$;

create function staging.inteiro(valor text) returns integer
language sql immutable parallel safe as $$
    select case when valor ~ '^[0-9]+$' then valor::integer end
$$;

create function staging.dinheiro(valor text) returns numeric(18, 2)
language sql immutable parallel safe as $$
    select replace(valor, ',', '.')::numeric(18, 2)
$$;

create function staging.localidade_tipo(localidade text) returns text
language sql immutable parallel safe as $$
    select case
        when localidade ~ ' - [A-Z]{2}$' then 'municipio'
        when localidade ~ '\(UF\)$' then 'estado'
        when localidade = 'MÚLTIPLO' then 'multiplo'
        when localidade = 'Nacional' then 'nacional'
        when localidade = 'Exterior' then 'exterior'
        when localidade in ('Norte', 'Nordeste', 'Centro-Oeste', 'Sudeste', 'Sul') then 'regiao'
        else 'outro'
    end
$$;

create table staging.uf (
    codigo_ibge smallint primary key,
    sigla char(2) not null unique,
    nome text not null unique
);

insert into staging.uf (codigo_ibge, sigla, nome) values
    (11, 'RO', 'RONDÔNIA'), (12, 'AC', 'ACRE'), (13, 'AM', 'AMAZONAS'), (14, 'RR', 'RORAIMA'),
    (15, 'PA', 'PARÁ'), (16, 'AP', 'AMAPÁ'), (17, 'TO', 'TOCANTINS'), (21, 'MA', 'MARANHÃO'),
    (22, 'PI', 'PIAUÍ'), (23, 'CE', 'CEARÁ'), (24, 'RN', 'RIO GRANDE DO NORTE'),
    (25, 'PB', 'PARAÍBA'), (26, 'PE', 'PERNAMBUCO'), (27, 'AL', 'ALAGOAS'), (28, 'SE', 'SERGIPE'),
    (29, 'BA', 'BAHIA'), (31, 'MG', 'MINAS GERAIS'), (32, 'ES', 'ESPÍRITO SANTO'),
    (33, 'RJ', 'RIO DE JANEIRO'), (35, 'SP', 'SÃO PAULO'), (41, 'PR', 'PARANÁ'),
    (42, 'SC', 'SANTA CATARINA'), (43, 'RS', 'RIO GRANDE DO SUL'), (50, 'MS', 'MATO GROSSO DO SUL'),
    (51, 'MT', 'MATO GROSSO'), (52, 'GO', 'GOIÁS'), (53, 'DF', 'DISTRITO FEDERAL');

create table staging.emendas as
select
    e.linha_arquivo,
    staging.nulo(e.codigo_da_emenda) as codigo_emenda,
    e.ano_da_emenda::smallint as ano_emenda,
    e.tipo_de_emenda as tipo_emenda,
    staging.nulo(e.codigo_do_autor_da_emenda) as codigo_autor,
    staging.nulo(e.nome_do_autor_da_emenda) as nome_autor,
    staging.nulo(e.numero_da_emenda) as numero_emenda,
    e.localidade_de_aplicacao_do_recurso as localidade_aplicacao,
    staging.localidade_tipo(e.localidade_de_aplicacao_do_recurso) as localidade_tipo,
    staging.inteiro(e.codigo_municipio_ibge) as codigo_municipio_ibge,
    case when e.codigo_municipio_ibge ~ '^[0-9]+$' then staging.nulo(e.municipio) end as municipio,
    staging.inteiro(e.codigo_uf_ibge) as codigo_uf_ibge,
    u.sigla as uf_sigla,
    staging.nulo(e.regiao) as regiao,
    staging.inteiro(e.codigo_funcao) as codigo_funcao,
    staging.nulo(e.nome_funcao) as nome_funcao,
    staging.inteiro(e.codigo_subfuncao) as codigo_subfuncao,
    staging.nulo(e.nome_subfuncao) as nome_subfuncao,
    staging.nulo(e.codigo_programa) as codigo_programa,
    staging.nulo(e.nome_programa) as nome_programa,
    staging.nulo(e.codigo_acao) as codigo_acao,
    staging.nulo(e.nome_acao) as nome_acao,
    staging.nulo(e.codigo_plano_orcamentario) as codigo_plano_orcamentario,
    staging.nulo(e.nome_plano_orcamentario) as nome_plano_orcamentario,
    staging.dinheiro(e.valor_empenhado) as valor_empenhado,
    staging.dinheiro(e.valor_liquidado) as valor_liquidado,
    staging.dinheiro(e.valor_pago) as valor_pago,
    staging.dinheiro(e.valor_restos_a_pagar_inscritos) as valor_restos_a_pagar_inscritos,
    staging.dinheiro(e.valor_restos_a_pagar_cancelados) as valor_restos_a_pagar_cancelados,
    staging.dinheiro(e.valor_restos_a_pagar_pagos) as valor_restos_a_pagar_pagos
from raw.emendas_parlamentares e
left join staging.uf u on u.codigo_ibge = staging.inteiro(e.codigo_uf_ibge) / 100000;

create table staging.convenios as
select
    c.linha_arquivo,
    staging.nulo(c.codigo_da_emenda) as codigo_emenda,
    staging.inteiro(c.codigo_funcao) as codigo_funcao,
    staging.nulo(c.nome_funcao) as nome_funcao,
    staging.inteiro(c.codigo_subfuncao) as codigo_subfuncao,
    staging.nulo(c.nome_subfuncao) as nome_subfuncao,
    c.localidade_do_gasto as localidade_gasto,
    staging.localidade_tipo(c.localidade_do_gasto) as localidade_tipo,
    case
        when staging.localidade_tipo(c.localidade_do_gasto) = 'municipio'
            then regexp_replace(c.localidade_do_gasto, ' - [A-Z]{2}$', '')
    end as municipio,
    coalesce(substring(c.localidade_do_gasto from ' - ([A-Z]{2})$'), u.sigla) as uf_sigla,
    c.tipo_de_emenda as tipo_emenda,
    to_date(c.data_publicacao_convenio, 'DD/MM/YYYY') as data_publicacao,
    staging.nulo(c.convenente) as convenente,
    staging.nulo(c.objeto_convenio) as objeto,
    staging.nulo(c.numero_convenio) as numero_convenio,
    staging.dinheiro(c.valor_convenio) as valor_convenio
from raw.emendas_convenios c
left join staging.uf u
    on staging.localidade_tipo(c.localidade_do_gasto) = 'estado'
    and u.nome = replace(c.localidade_do_gasto, ' (UF)', '');

create table staging.pagamentos_favorecido as
select
    p.linha_arquivo,
    staging.nulo(p.codigo_da_emenda) as codigo_emenda,
    staging.nulo(p.codigo_do_autor_da_emenda) as codigo_autor,
    staging.nulo(p.nome_do_autor_da_emenda) as nome_autor,
    staging.nulo(p.numero_da_emenda) as numero_emenda,
    p.tipo_de_emenda as tipo_emenda,
    to_date(p.ano_mes || '01', 'YYYYMMDD') as competencia,
    case when p.codigo_do_favorecido ~ '^-' then null else staging.nulo(p.codigo_do_favorecido) end
        as codigo_favorecido,
    staging.nulo(p.favorecido) as nome_favorecido,
    staging.nulo(p.natureza_juridica) as natureza_juridica,
    case staging.nulo(p.tipo_favorecido)
        when 'Pessoa Fisica' then 'Pessoa Física'
        when 'Inscrição Genéric' then 'Inscrição Genérica'
        else staging.nulo(p.tipo_favorecido)
    end as tipo_favorecido,
    staging.nulo(p.uf_favorecido) as uf_favorecido,
    staging.nulo(p.municipio_favorecido) as municipio_favorecido,
    staging.dinheiro(p.valor_recebido) as valor_recebido
from raw.emendas_por_favorecido p;

create table staging.transferegov_beneficiarios as
select
    id_beneficiario::integer as id_beneficiario,
    upper(staging.nulo(uf_beneficiario)) as uf_sigla,
    staging.nulo(nome_beneficiario) as nome,
    staging.nulo(cnpj_beneficiario) as cnpj
from raw.transferegov_beneficiarios;

create table staging.transferegov_planos_acao as
select
    id_plano_acao::integer as id_plano_acao,
    staging.nulo(codigo_plano_acao) as codigo_plano,
    ano_plano_acao::smallint as ano_plano,
    staging.nulo(situacao_plano_acao) as situacao,
    data_aceite_plano_acao::date as data_aceite,
    staging.nulo(motivo_impedimento_plano_acao) as motivo_impedimento,
    staging.nulo(nome_parlamentar_emenda_plano_acao) as nome_parlamentar,
    ano_emenda_parlamentar_plano_acao::smallint as ano_emenda,
    staging.nulo(numero_emenda_parlamentar_plano_acao) as codigo_emenda,
    staging.dinheiro(valor_custeio_plano_acao) as valor_custeio,
    staging.dinheiro(valor_investimento_plano_acao) as valor_investimento,
    staging.nulo(categoria_despesa_plano_acao) as categoria_despesa,
    staging.nulo(codigo_descricao_areas_politicas_publicas_plano_acao) as areas_politicas,
    staging.nulo(nome_objeto) as nome_objeto,
    staging.nulo(detalhamento_objeto) as detalhamento_objeto,
    id_beneficiario::integer as id_beneficiario
from raw.transferegov_planos_acao;

create table staging.transferegov_executores as
select
    id_executor::integer as id_executor,
    id_plano_acao::integer as id_plano_acao,
    staging.nulo(cnpj_executor) as cnpj,
    staging.nulo(nome_executor) as nome,
    staging.nulo(objeto_executor) as objeto
from raw.transferegov_executores;

create table staging.transferegov_planos_trabalho as
select
    id_plano_trabalho::integer as id_plano_trabalho,
    id_plano_acao::integer as id_plano_acao,
    staging.nulo(situacao_plano_trabalho) as situacao,
    data_inicio_execucao_plano_trabalho::date as data_inicio_execucao,
    data_fim_execucao_plano_trabalho::date as data_fim_execucao,
    prazo_execucao_meses_plano_trabalho::smallint as prazo_meses
from raw.transferegov_planos_trabalho;

create table staging.transferegov_empenhos as
select
    id_empenho::integer as id_empenho,
    id_plano_acao::integer as id_plano_acao,
    staging.nulo(numero_empenho) as numero_empenho,
    situacao_empenho::smallint as situacao_codigo,
    staging.nulo(descricao_situacao_empenho) as situacao,
    staging.nulo(descricao_tipo_documento_empenho) as tipo_documento,
    data_emissao_empenho::date as data_emissao,
    staging.nulo(categoria_despesa_empenho) as categoria_despesa,
    staging.dinheiro(valor_empenho) as valor
from raw.transferegov_empenhos;

create index on staging.emendas (codigo_emenda);
create index on staging.emendas (uf_sigla);
create index on staging.convenios (codigo_emenda);
create index on staging.pagamentos_favorecido (codigo_emenda);

analyze staging.emendas;
analyze staging.convenios;
analyze staging.pagamentos_favorecido;

create index on staging.transferegov_planos_acao (id_plano_acao);
create index on staging.transferegov_planos_acao (codigo_emenda);
create index on staging.transferegov_planos_acao (id_beneficiario);
create index on staging.transferegov_executores (id_plano_acao);
create index on staging.transferegov_planos_trabalho (id_plano_acao);
create index on staging.transferegov_empenhos (id_plano_acao);

analyze staging.transferegov_planos_acao;
analyze staging.transferegov_beneficiarios;
analyze staging.transferegov_executores;
analyze staging.transferegov_planos_trabalho;
analyze staging.transferegov_empenhos;
