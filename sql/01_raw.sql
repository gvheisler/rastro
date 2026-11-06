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
