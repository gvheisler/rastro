from dataclasses import dataclass
from typing import Literal

from psycopg import Connection

FIRST_YEAR = 2014
CPF_PATTERN = (
    r"(\*\*\*\.[0-9]{3}\.[0-9]{3}-\*\*|[0-9]{3}\.[0-9]{3}\.[0-9]{3}-[0-9]{2}"
    r"|(?<![0-9])[0-9]{11}(?![0-9]))"
)
TEXT_COLUMNS = {
    "emendas": ["autor", "localidade", "municipio", "funcao", "programa", "acao"],
    "convenios": ["autor", "localidade", "convenente", "objeto"],
    "pagamentos_favorecidos": [
        "autor",
        "nome_favorecido",
        "codigo_favorecido",
        "natureza_juridica",
        "municipio_favorecido",
    ],
    "transferencias_especiais": [
        "autor",
        "beneficiario",
        "municipio",
        "executor",
        "objeto",
        "detalhamento_objeto",
        "motivo_impedimento",
    ],
    "transferencias_especiais_empenhos": ["autor", "beneficiario", "municipio"],
}
EMENDA_KEY = "codigo_emenda, localidade, funcao, subfuncao, programa, acao, plano_orcamentario"
SC_EMENDA_CODES = (
    "select codigo_emenda from staging.emendas where uf_sigla = 'SC' and codigo_emenda is not null"
)


@dataclass(frozen=True)
class Check:
    name: str
    severity: Literal["error", "info"]
    description: str
    query: str


@dataclass(frozen=True)
class Result:
    check: Check
    count: int

    @property
    def failed(self) -> bool:
        return self.check.severity == "error" and self.count > 0


def _cpf_query() -> str:
    parts = [
        f"select count(*) from mart.{table} where {column} ~ '{CPF_PATTERN}'"
        for table, columns in TEXT_COLUMNS.items()
        for column in columns
    ]
    return "select sum(n) from (" + " union all ".join(parts) + ") t(n)"


CHECKS = [
    Check(
        "emendas_year_out_of_range",
        "error",
        f"Amendment year before {FIRST_YEAR} or after the current year",
        f"select count(*) from mart.emendas where ano is null or ano < {FIRST_YEAR} "
        "or ano > extract(year from current_date)",
    ),
    Check(
        "emendas_null_amounts",
        "error",
        "Committed, settled or paid amount is null",
        "select count(*) from mart.emendas "
        "where valor_empenhado is null or valor_liquidado is null or valor_pago is null",
    ),
    Check(
        "emendas_negative_amounts",
        "error",
        "Committed, settled or paid amount is negative",
        "select count(*) from mart.emendas "
        "where valor_empenhado < 0 or valor_liquidado < 0 or valor_pago < 0",
    ),
    Check(
        "emendas_duplicate_rows",
        "error",
        "Extra rows repeating the same amendment, place, function, program and action",
        "select coalesce(sum(n - 1), 0) from (select count(*) n from mart.emendas "
        f"where codigo_emenda is not null group by {EMENDA_KEY} having count(*) > 1) d",
    ),
    Check(
        "emendas_municipio_missing_name",
        "error",
        "Municipal location without a municipality name",
        "select count(*) from mart.emendas where localidade_tipo = 'municipio' "
        "and municipio is null",
    ),
    Check(
        "convenios_negative_amounts",
        "error",
        "Negative convenio amount",
        "select count(*) from mart.convenios where valor_convenio < 0",
    ),
    Check(
        "pagamentos_period_out_of_range",
        "error",
        f"Payment month before {FIRST_YEAR} or in the future",
        "select count(*) from mart.pagamentos_favorecidos "
        f"where competencia < '{FIRST_YEAR}-01-01' or competencia > current_date",
    ),
    Check(
        "pessoa_fisica_exposed",
        "error",
        "Individual with name or code visible",
        "select count(*) from mart.pagamentos_favorecidos where tipo_favorecido = 'Pessoa Física' "
        "and (nome_favorecido <> 'Pessoa física (nome omitido)' or codigo_favorecido is not null)",
    ),
    Check(
        "cpf_like_text",
        "error",
        "Text that looks like a CPF in any mart column",
        _cpf_query(),
    ),
    Check(
        "mart_rows_differ_from_staging",
        "error",
        "Row count of a mart table differs from its Santa Catarina rows in staging",
        "select abs((select count(*) from mart.emendas)"
        " - (select count(*) from staging.emendas where uf_sigla = 'SC'))"
        " + abs((select count(*) from mart.convenios)"
        " - (select count(*) from staging.convenios where uf_sigla = 'SC'))"
        " + abs((select count(*) from mart.pagamentos_favorecidos)"
        " - (select count(*) from staging.pagamentos_favorecido"
        f" where codigo_emenda in ({SC_EMENDA_CODES})))",
    ),
    Check(
        "transferencias_duplicate_plans",
        "error",
        "Extra rows repeating the same Transferegov action plan",
        "select coalesce(sum(n - 1), 0) from (select count(*) n from mart.transferencias_especiais "
        "group by id_plano_acao having count(*) > 1) d",
    ),
    Check(
        "transferencias_null_amounts",
        "error",
        "Planned or committed amount of a special-transfer plan is null",
        "select count(*) from mart.transferencias_especiais where valor_planejado is null "
        "or valor_empenhado is null or valor_em_minuta is null",
    ),
    Check(
        "transferencias_negative_amounts",
        "error",
        "Negative amount in a special-transfer plan or commitment",
        "select (select count(*) from mart.transferencias_especiais "
        "where valor_custeio < 0 or valor_investimento < 0 or valor_empenhado < 0"
        " or valor_em_minuta < 0)"
        " + (select count(*) from mart.transferencias_especiais_empenhos where valor < 0)",
    ),
    Check(
        "transferencias_rows_differ_from_staging",
        "error",
        "Special-transfer rows in the mart differ from those of Santa Catarina in staging",
        "select abs((select count(*) from mart.transferencias_especiais)"
        " - (select count(*) from staging.transferegov_planos_acao p"
        " join staging.transferegov_beneficiarios b using (id_beneficiario)"
        " where b.uf_sigla = 'SC'))"
        " + abs((select count(*) from mart.transferencias_especiais_empenhos)"
        " - (select count(*) from staging.transferegov_empenhos e"
        " join staging.transferegov_planos_acao p using (id_plano_acao)"
        " join staging.transferegov_beneficiarios b using (id_beneficiario)"
        " where b.uf_sigla = 'SC'))",
    ),
    Check(
        "emendas_without_code",
        "info",
        "Rows with no amendment code in the source; they cannot be linked to other tables",
        "select count(*) from mart.emendas where codigo_emenda is null",
    ),
    Check(
        "emendas_negative_restos_a_pagar",
        "info",
        "Rows with a negative restos a pagar amount in the source",
        "select count(*) from mart.emendas "
        "where valor_restos_a_pagar_inscritos < 0 or valor_restos_a_pagar_cancelados < 0 "
        "or valor_restos_a_pagar_pagos < 0",
    ),
    Check(
        "emendas_paid_above_committed",
        "info",
        "Rows where the paid amount is greater than the committed amount",
        "select count(*) from mart.emendas where valor_pago > valor_empenhado",
    ),
    Check(
        "convenios_without_code",
        "info",
        "Convenios with no amendment code in the source",
        "select count(*) from mart.convenios where codigo_emenda is null",
    ),
    Check(
        "pagamentos_negative_amounts",
        "info",
        "Payment rows with a negative amount (reversals in the source)",
        "select count(*) from mart.pagamentos_favorecidos where valor_recebido < 0",
    ),
    Check(
        "transferencias_with_drafts",
        "info",
        "Plans with commitment drafts (minutas) not yet sent",
        "select count(*) from mart.transferencias_especiais where valor_em_minuta > 0",
    ),
    Check(
        "transferencias_municipality_not_in_portal",
        "info",
        "Municipal plans whose municipality has no IBGE code because the Portal lists no "
        "amendment for it",
        "select count(*) from mart.transferencias_especiais "
        "where municipio is not null and codigo_municipio_ibge is null",
    ),
]


def run_checks(conn: Connection) -> list[Result]:
    return [Result(check, conn.execute(check.query).fetchone()[0] or 0) for check in CHECKS]
