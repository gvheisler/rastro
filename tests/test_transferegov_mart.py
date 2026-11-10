from decimal import Decimal

from rastro.db import apply_sql
from support import scalar

PLANS = "mart.transferencias_especiais"
COMMITMENTS = "mart.transferencias_especiais_empenhos"


def sc_plans(conn):
    return scalar(
        conn,
        "select count(*) from staging.transferegov_planos_acao p "
        "join staging.transferegov_beneficiarios b using (id_beneficiario) "
        "where b.uf_sigla = 'SC'",
    )


def add_plan(conn, plan_id, *, beneficiary="MUNICIPIO DE TESTE", **overrides):
    """Insert a synthetic Santa Catarina plan into staging, with its beneficiary."""
    conn.execute(
        "insert into staging.transferegov_beneficiarios (id_beneficiario, uf_sigla, nome) "
        "values (%s, 'SC', %s)",
        (plan_id, beneficiary),
    )
    values = {
        "id_plano_acao": plan_id,
        "ano_plano": 2025,
        "situacao": "CIENTE",
        "nome_parlamentar": "Fulano Útil",
        "ano_emenda": 2025,
        "codigo_emenda": "202599990001",
        "valor_custeio": Decimal("10.00"),
        "valor_investimento": Decimal("5.50"),
        "id_beneficiario": plan_id,
    } | overrides
    columns = ", ".join(values)
    conn.execute(
        f"insert into staging.transferegov_planos_acao ({columns}) "
        f"values ({', '.join(['%s'] * len(values))})",
        list(values.values()),
    )


def rebuild(conn):
    apply_sql(conn, "03_mart.sql")


def test_one_row_per_plan_of_a_santa_catarina_beneficiary(mart_db):
    assert scalar(mart_db, f"select count(*) from {PLANS}") == sc_plans(mart_db)
    assert scalar(mart_db, f"select count(distinct id_plano_acao) from {PLANS}") == sc_plans(
        mart_db
    )


def test_other_states_stay_out_of_the_mart(mart_db):
    assert (
        scalar(
            mart_db,
            f"select count(*) from {PLANS} t "
            "join staging.transferegov_beneficiarios b on b.id_beneficiario = ("
            "select id_beneficiario from staging.transferegov_planos_acao "
            "where id_plano_acao = t.id_plano_acao) where b.uf_sigla <> 'SC'",
        )
        == 0
    )


def test_total_value_is_custeio_plus_investimento(mart_db):
    assert scalar(mart_db, f"select count(*) from {PLANS} where valor_planejado is null") == 0
    assert (
        scalar(
            mart_db,
            f"select count(*) from {PLANS} "
            "where valor_planejado <> valor_custeio + valor_investimento",
        )
        == 0
    )
    typed = scalar(
        mart_db,
        "select sum(p.valor_custeio + p.valor_investimento) "
        "from staging.transferegov_planos_acao p "
        "join staging.transferegov_beneficiarios b using (id_beneficiario) where b.uf_sigla = 'SC'",
    )
    assert scalar(mart_db, f"select sum(valor_planejado) from {PLANS}") == typed


def test_sent_commitments_and_drafts_are_kept_apart(mart_db):
    drafts = scalar(mart_db, f"select sum(valor_em_minuta) from {PLANS}")
    sent = scalar(mart_db, f"select sum(valor_empenhado) from {PLANS}")
    by_status = dict(
        mart_db.execute(
            f"select situacao, sum(valor) from {COMMITMENTS} group by 1",
        ).fetchall()
    )
    assert drafts == by_status["Minuta de Empenho"] > 0
    assert sent == by_status["Enviado"] > 0


def test_a_plan_without_commitments_has_zero_not_null(mart_db):
    add_plan(mart_db, 990001)
    rebuild(mart_db)
    row = mart_db.execute(
        f"select valor_empenhado, valor_em_minuta from {PLANS} where id_plano_acao = 990001"
    ).fetchone()
    assert row == (0, 0)


def test_authors_are_upper_case_without_accents_like_the_portal(mart_db):
    assert scalar(mart_db, f"select count(*) from {PLANS} where autor ~ '[a-zà-ú]'") == 0
    add_plan(mart_db, 990002, nome_parlamentar="Esperidião Amin")
    rebuild(mart_db)
    assert (
        scalar(mart_db, f"select autor from {PLANS} where id_plano_acao = 990002")
        == "ESPERIDIAO AMIN"
    )


def test_authors_match_the_portal_for_the_same_amendment(mart_db):
    pairs = mart_db.execute(
        f"select count(*), count(*) filter (where t.autor = e.autor) from {PLANS} t "
        "join (select distinct codigo_emenda, autor from mart.emendas) e using (codigo_emenda)"
    ).fetchone()
    assert pairs[0] > 0
    assert pairs[1] >= pairs[0] - 1


def test_plans_link_to_portal_amendments_by_code(mart_db):
    linked = scalar(
        mart_db,
        f"select count(*) from {PLANS} t where exists "
        "(select 1 from mart.emendas e where e.codigo_emenda = t.codigo_emenda)",
    )
    assert linked > 0


def test_the_state_plans_have_no_municipality(mart_db):
    add_plan(mart_db, 990003, beneficiary="ESTADO DE SANTA CATARINA")
    rebuild(mart_db)
    row = mart_db.execute(
        f"select beneficiario, municipio, codigo_municipio_ibge from {PLANS} "
        "where id_plano_acao = 990003"
    ).fetchone()
    assert row == ("ESTADO DE SANTA CATARINA", None, None)


def test_municipality_takes_the_portal_spelling_and_ibge_code(mart_db):
    mart_db.execute(
        "insert into staging.emendas (uf_sigla, municipio, codigo_municipio_ibge) "
        "values ('SC', 'SÃO LOURENÇO DO OESTE', 4216909), ('SC', 'BALNEÁRIO PIÇARRAS', 4212809)"
    )
    add_plan(mart_db, 990004, beneficiary="MUNICIPIO DE SAO LOURENCO D'OESTE")
    add_plan(mart_db, 990005, beneficiary="MUNICIPIO DE BALNEARIO DE PICARRAS")
    add_plan(mart_db, 990006, beneficiary="NAVEGANTES")
    mart_db.execute(
        "insert into staging.emendas (uf_sigla, municipio, codigo_municipio_ibge) "
        "values ('SC', 'HERVAL D''OESTE', 4207304)"
    )
    add_plan(mart_db, 990024, beneficiary="MUNICIPIO DE HERVAL D'OESTE")
    rebuild(mart_db)
    rows = dict(
        (r[0], r[1:])
        for r in mart_db.execute(
            f"select id_plano_acao, municipio, codigo_municipio_ibge from {PLANS} "
            "where id_plano_acao in (990004, 990005, 990006, 990024)"
        )
    )
    assert rows[990004] == ("SÃO LOURENÇO DO OESTE", 4216909)
    assert rows[990005] == ("BALNEÁRIO PIÇARRAS", 4212809)
    assert rows[990006][0] == "NAVEGANTES"
    assert rows[990024] == ("HERVAL D'OESTE", 4207304)


def test_an_unknown_municipality_keeps_the_name_from_the_beneficiary(mart_db):
    add_plan(mart_db, 990007, beneficiary="MUNICIPIO DE LUGAR NENHUM")
    rebuild(mart_db)
    row = mart_db.execute(
        f"select municipio, codigo_municipio_ibge from {PLANS} where id_plano_acao = 990007"
    ).fetchone()
    assert row == ("LUGAR NENHUM", None)


def test_the_object_falls_back_to_what_the_executor_declared(mart_db):
    add_plan(mart_db, 990008, nome_objeto=None)
    mart_db.execute(
        "insert into staging.transferegov_executores (id_executor, id_plano_acao, nome, objeto) "
        "values (990008, 990008, 'MUNICIPIO DE TESTE', 'Pavimentação de ruas')"
    )
    add_plan(mart_db, 990009, nome_objeto="Aquisição de veículo")
    mart_db.execute(
        "insert into staging.transferegov_executores (id_executor, id_plano_acao, nome, objeto) "
        "values (990009, 990009, 'MUNICIPIO DE TESTE', 'Outro texto')"
    )
    rebuild(mart_db)
    objects = dict(
        mart_db.execute(
            f"select id_plano_acao, objeto from {PLANS} where id_plano_acao in (990008, 990009)"
        ).fetchall()
    )
    assert objects == {990008: "Pavimentação de ruas", 990009: "Aquisição de veículo"}


def test_executors_are_listed_once_each_in_alphabetical_order(mart_db):
    add_plan(mart_db, 990010)
    mart_db.execute(
        "insert into staging.transferegov_executores (id_executor, id_plano_acao, nome) "
        "values (990010, 990010, 'B FUNDO'), (990011, 990010, 'A FUNDO'), "
        "(990012, 990010, 'B FUNDO')"
    )
    rebuild(mart_db)
    assert (
        scalar(mart_db, f"select executor from {PLANS} where id_plano_acao = 990010")
        == "A FUNDO; B FUNDO"
    )


def test_eleven_digit_sequences_in_free_text_are_masked(mart_db):
    add_plan(
        mart_db,
        990013,
        detalhamento_objeto="Obra de 12345678901 para a rua",
        motivo_impedimento="Processo 98765432100 devolvido",
    )
    mart_db.execute(
        "insert into staging.transferegov_executores (id_executor, id_plano_acao, nome, objeto) "
        "values (990013, 990013, 'MUNICIPIO', 'Contrato 11122233344')"
    )
    rebuild(mart_db)
    row = mart_db.execute(
        f"select detalhamento_objeto, motivo_impedimento, objeto from {PLANS} "
        "where id_plano_acao = 990013"
    ).fetchone()
    assert row == ("Obra de *** para a rua", "Processo *** devolvido", "Contrato ***")


def test_work_plan_dates_and_status_come_with_the_plan(mart_db):
    assert (
        scalar(
            mart_db,
            f"select count(*) from {PLANS} where situacao_plano_trabalho is not null "
            "and data_inicio_execucao is not null",
        )
        > 0
    )
    add_plan(mart_db, 990014)
    rebuild(mart_db)
    assert (
        scalar(
            mart_db,
            f"select situacao_plano_trabalho from {PLANS} where id_plano_acao = 990014",
        )
        is None
    )


def test_commitments_carry_the_plan_context_and_the_year(mart_db):
    assert scalar(mart_db, f"select count(*) from {COMMITMENTS}") == scalar(
        mart_db,
        "select count(*) from staging.transferegov_empenhos e "
        "join staging.transferegov_planos_acao p using (id_plano_acao) "
        "join staging.transferegov_beneficiarios b using (id_beneficiario) where b.uf_sigla = 'SC'",
    )
    assert (
        scalar(
            mart_db,
            f"select count(*) from {COMMITMENTS} where autor is null or beneficiario is null "
            "or ano_emissao <> extract(year from data_emissao)",
        )
        == 0
    )


def test_fontes_describe_both_transferegov_tables(mart_db):
    rows = {
        r[0]: r[1:]
        for r in mart_db.execute(
            "select tabela, fonte, arquivo, ano_inicio, ano_fim, carregado_em from mart.fontes "
            "where tabela like 'transferencias_especiais%'"
        )
    }
    assert set(rows) == {"transferencias_especiais", "transferencias_especiais_empenhos"}
    plans = rows["transferencias_especiais"]
    assert plans[1] == "especiais/planos-acao-especiais"
    assert plans[2] <= plans[3] and plans[4] is not None
    assert rows["transferencias_especiais_empenhos"][1] == "especiais/empenhos-especiais"


def test_the_read_only_role_can_query_the_new_tables(readonly):
    for table in ("transferencias_especiais", "transferencias_especiais_empenhos"):
        assert readonly.execute(f"select count(*) from mart.{table}").fetchone()[0] > 0


def test_blocked_plans_are_flagged_from_their_status(mart_db):
    statuses = {
        990020: "IMPEDIDO",
        990021: "Impedido por Rejeição do Plano de Trabalho",
        990022: "CIENTE",
        990023: "Plano de Trabalho em Elaboração/Aguardando Envio para Análise",
    }
    for plan_id, status in statuses.items():
        add_plan(mart_db, plan_id, situacao=status)
    rebuild(mart_db)
    flags = dict(
        mart_db.execute(
            f"select id_plano_acao, impedido from {PLANS} where id_plano_acao >= 990020"
        ).fetchall()
    )
    assert flags == {990020: True, 990021: True, 990022: False, 990023: False}
