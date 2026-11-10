create schema if not exists raw;

create table if not exists raw.emendas_parlamentares (
    codigo_da_emenda text,
    ano_da_emenda text,
    tipo_de_emenda text,
    codigo_do_autor_da_emenda text,
    nome_do_autor_da_emenda text,
    numero_da_emenda text,
    localidade_de_aplicacao_do_recurso text,
    codigo_municipio_ibge text,
    municipio text,
    codigo_uf_ibge text,
    uf text,
    regiao text,
    codigo_funcao text,
    nome_funcao text,
    codigo_subfuncao text,
    nome_subfuncao text,
    codigo_programa text,
    nome_programa text,
    codigo_acao text,
    nome_acao text,
    codigo_plano_orcamentario text,
    nome_plano_orcamentario text,
    valor_empenhado text,
    valor_liquidado text,
    valor_pago text,
    valor_restos_a_pagar_inscritos text,
    valor_restos_a_pagar_cancelados text,
    valor_restos_a_pagar_pagos text,
    linha_arquivo bigint generated always as identity
);

create table if not exists raw.emendas_convenios (
    codigo_da_emenda text,
    codigo_funcao text,
    nome_funcao text,
    codigo_subfuncao text,
    nome_subfuncao text,
    localidade_do_gasto text,
    tipo_de_emenda text,
    data_publicacao_convenio text,
    convenente text,
    objeto_convenio text,
    numero_convenio text,
    valor_convenio text,
    linha_arquivo bigint generated always as identity
);

create table if not exists raw.emendas_por_favorecido (
    codigo_da_emenda text,
    codigo_do_autor_da_emenda text,
    nome_do_autor_da_emenda text,
    numero_da_emenda text,
    tipo_de_emenda text,
    ano_mes text,
    codigo_do_favorecido text,
    favorecido text,
    natureza_juridica text,
    tipo_favorecido text,
    uf_favorecido text,
    municipio_favorecido text,
    valor_recebido text,
    linha_arquivo bigint generated always as identity
);

create table if not exists raw.cargas (
    arquivo text primary key,
    sha256 text not null,
    linhas bigint not null,
    carregado_em timestamptz not null default now()
);

alter table raw.cargas add column if not exists atualizado_na_fonte date;

create table if not exists raw.transferegov_beneficiarios (
    id_beneficiario text,
    uf_beneficiario text,
    nome_beneficiario text,
    cnpj_beneficiario text,
    linha_carga bigint generated always as identity
);

create table if not exists raw.transferegov_planos_acao (
    id_plano_acao text,
    codigo_plano_acao text,
    ano_plano_acao text,
    situacao_plano_acao text,
    data_aceite_plano_acao text,
    motivo_impedimento_plano_acao text,
    nome_parlamentar_emenda_plano_acao text,
    ano_emenda_parlamentar_plano_acao text,
    numero_emenda_parlamentar_plano_acao text,
    valor_custeio_plano_acao text,
    valor_investimento_plano_acao text,
    categoria_despesa_plano_acao text,
    codigo_descricao_areas_politicas_publicas_plano_acao text,
    nome_objeto text,
    detalhamento_objeto text,
    id_beneficiario text,
    linha_carga bigint generated always as identity
);

create table if not exists raw.transferegov_executores (
    id_executor text,
    id_plano_acao text,
    cnpj_executor text,
    nome_executor text,
    objeto_executor text,
    linha_carga bigint generated always as identity
);

create table if not exists raw.transferegov_planos_trabalho (
    id_plano_trabalho text,
    id_plano_acao text,
    situacao_plano_trabalho text,
    data_inicio_execucao_plano_trabalho text,
    data_fim_execucao_plano_trabalho text,
    prazo_execucao_meses_plano_trabalho text,
    linha_carga bigint generated always as identity
);

create table if not exists raw.transferegov_empenhos (
    id_empenho text,
    id_plano_acao text,
    numero_empenho text,
    situacao_empenho text,
    descricao_situacao_empenho text,
    descricao_tipo_documento_empenho text,
    data_emissao_empenho text,
    categoria_despesa_empenho text,
    valor_empenho text,
    linha_carga bigint generated always as identity
);
