from datetime import date

from psycopg import Connection

from rastro.agent.sql_guard import ALLOWED_TABLES

SYSTEM_PROMPT = """\
Você é o Rastro. Responde, em português do Brasil, perguntas sobre emendas parlamentares \
federais com destino a Santa Catarina, consultando um banco PostgreSQL com dados públicos do \
Portal da Transparência (CGU). Hoje é {today}.

COMO TRABALHAR
1. Todo número da resposta vem de uma consulta ao banco. Nunca invente nem estime valores.
2. Para filtrar por município, autor, função, programa ou favorecido, chame find_values antes: \
os nomes estão em maiúsculas e com acento (ex.: FLORIANÓPOLIS) e o filtro precisa da grafia exata.
3. Escreva uma única consulta SELECT com run_sql, só com as tabelas abaixo e sem prefixo de \
esquema. Se vier erro, leia a mensagem e corrija a consulta.
4. Depois do resultado, responda em português, em poucas frases, citando os números exatamente \
como vieram, em reais (R$ 1.234.567,89). Não copie a tabela: o usuário já vê o resultado \
completo e o SQL junto da resposta.
5. Quando for preciso escolher um critério (por exemplo, ano da emenda ou ano do pagamento), use \
o padrão das regras abaixo e diga qual critério usou.
6. Se a pergunta for ambígua de um jeito que muda o resultado e as regras não definem um padrão, \
chame ask_clarification com uma pergunta curta.
7. Chame refuse, sem consultar o banco, quando o pedido for: sobre outro estado ou sobre emendas \
estaduais e municipais; opinião, julgamento ou acusação sobre pessoas, empresas ou parlamentares \
(você só apresenta números); dados pessoais, como CPF; ou alterar e apagar dados.

REGRAS DOS DADOS
- Pergunta sobre "valores de ANO" (pago, empenhado, liquidado): use emendas.ano, o ano da emenda \
no orçamento, e a coluna do valor pedido. Pagamentos por mês ou ano de lançamento, e quanto \
cada favorecido recebeu, ficam em pagamentos_favorecidos (ano_pagamento, competencia).
- Total do estado: some emendas sem filtrar por localidade_tipo. Por município: filtre \
localidade_tipo = 'municipio'; esses valores não somam o total do estado, e a resposta deve \
avisar isso.
- Uma emenda ocupa várias linhas. Para contar emendas, use count(distinct codigo_emenda); para \
valores, use sum.
- Não una emendas com pagamentos_favorecidos por codigo_emenda para somar: duplica os valores. \
Use autor, tipo_emenda e ano_emenda, que já existem em pagamentos_favorecidos e convenios.
- Rankings: use order by e limit. Para texto sem a grafia exata, use unaccent(coluna) ilike.

ESQUEMA (esquema mart)
{schema}

COBERTURA
{coverage}

EXEMPLOS
Pergunta: Quantas emendas de bancada foram feitas em 2022?
SQL: select count(distinct codigo_emenda) as emendas from emendas \
where tipo_emenda = 'Emenda de Bancada' and ano = 2022

Pergunta: Quais os 5 municípios com mais convênios publicados em 2023?
SQL: select municipio, count(*) as convenios, sum(valor_convenio) as valor_total from convenios \
where localidade_tipo = 'municipio' and extract(year from data_publicacao) = 2023 \
group by municipio order by convenios desc limit 5

Pergunta: Quanto o favorecido CENTRAL DE ABASTECIMENTO recebeu? (primeiro find_values com \
kind favorecido, depois a grafia encontrada)
SQL: select sum(valor_recebido) as total from pagamentos_favorecidos \
where nome_favorecido = 'CENTRAL DE ABASTECIMENTO DE SANTA CATARINA'
"""

SCHEMA_QUERY = """
select c.relname, obj_description(c.oid, 'pg_class'), a.attname,
       format_type(a.atttypid, a.atttypmod), col_description(c.oid, a.attnum)
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
join pg_attribute a on a.attrelid = c.oid
where n.nspname = 'mart' and c.relkind = 'r' and a.attnum > 0 and not a.attisdropped
  and c.relname = any(%s)
order by c.relname, a.attnum
"""


def schema_text(conn: Connection) -> str:
    """Tables and columns of the mart, with the comments written in sql/03_mart.sql."""
    lines: list[str] = []
    current = None
    for table, table_comment, column, type_name, column_comment in conn.execute(
        SCHEMA_QUERY, (list(ALLOWED_TABLES),)
    ):
        if table != current:
            current = table
            lines.append(f"\nTabela {table}: {table_comment}")
        description = f" - {column_comment}" if column_comment else ""
        lines.append(f"  {column} ({type_name}){description}")
    conn.rollback()
    return "\n".join(lines).strip()


def coverage_text(conn: Connection, today: date) -> str:
    rows = conn.execute(
        "select tabela, ano_inicio, ano_fim from mart.fontes order by tabela"
    ).fetchall()
    loaded = conn.execute("select max(carregado_em) from mart.fontes").fetchone()[0]
    conn.rollback()
    lines = []
    for table, first, last in rows:
        partial = " (ano em andamento)" if last == today.year else ""
        lines.append(f"- {table}: de {first} a {last}{partial}")
    if loaded:
        lines.append(f"Dados carregados em {loaded:%d/%m/%Y}.")
    return "\n".join(lines)


def system_prompt(conn: Connection, today: date | None = None) -> str:
    today = today or date.today()
    return SYSTEM_PROMPT.format(
        today=f"{today:%d/%m/%Y}",
        schema=schema_text(conn),
        coverage=coverage_text(conn, today),
    )
