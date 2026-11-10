import csv
import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path

import psycopg
from psycopg import sql

CHUNK_SIZE = 1 << 20


class SchemaMismatchError(Exception):
    """The CSV header does not match the columns of the target raw table."""


def normalize_column(header: str) -> str:
    """Turn a CSV header such as 'Código da Emenda' into 'codigo_da_emenda'."""
    ascii_text = unicodedata.normalize("NFKD", header).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")


def _csv_columns(path: Path) -> list[str]:
    with path.open(encoding="latin-1", newline="") as f:
        return [normalize_column(h) for h in next(csv.reader(f, delimiter=";"))]


def _table_columns(conn: psycopg.Connection, table: str) -> list[str]:
    rows = conn.execute(
        """
        select column_name from information_schema.columns
        where table_schema = 'raw' and table_name = %s and is_identity = 'NO'
        order by ordinal_position
        """,
        (table,),
    ).fetchall()
    return [name for (name,) in rows]


def _check_header(source: str, table: str, actual: list[str], expected: list[str]) -> None:
    if actual == expected:
        return
    unexpected = [c for c in actual if c not in expected]
    missing = [c for c in expected if c not in actual]
    detail = f"unexpected columns {unexpected}, missing columns {missing}"
    if not unexpected and not missing:
        detail = "same columns in a different order"
    raise SchemaMismatchError(f"{source}: header does not match raw.{table}: {detail}")


def load_raw_csv(conn: psycopg.Connection, table: str, path: Path) -> int:
    """Replace the contents of raw.<table> with the CSV, as text, and record the load.

    The file is streamed to COPY in its original ISO-8859-1 encoding, so values reach the
    table exactly as they appear in the source. Returns the number of data rows loaded.
    """
    columns = _table_columns(conn, table)
    _check_header(path.name, table, _csv_columns(path), columns)

    target = sql.Identifier("raw", table)
    copy_statement = sql.SQL(
        "copy {} ({}) from stdin (format csv, delimiter ';', header true, encoding 'LATIN1')"
    ).format(target, sql.SQL(", ").join(map(sql.Identifier, columns)))

    digest = hashlib.sha256()
    with conn.transaction():
        conn.execute(sql.SQL("truncate {} restart identity").format(target))
        with conn.cursor() as cur:
            with cur.copy(copy_statement) as copy, path.open("rb") as f:
                while chunk := f.read(CHUNK_SIZE):
                    digest.update(chunk)
                    copy.write(chunk)
            rows = cur.rowcount
        conn.execute(
            """
            insert into raw.cargas (arquivo, sha256, linhas)
            values (%s, %s, %s)
            on conflict (arquivo) do update
                set sha256 = excluded.sha256, linhas = excluded.linhas, carregado_em = now()
            """,
            (path.name, digest.hexdigest(), rows),
        )
    return rows


def load_raw_rows(
    conn: psycopg.Connection,
    table: str,
    columns: Sequence[str],
    rows: Iterable[Sequence[str | None]],
    *,
    arquivo: str,
    atualizado_na_fonte: date | None = None,
) -> int:
    """Replace the contents of raw.<table> with text rows and record the load.

    The SHA-256 fingerprints the rows, so loading the same source state twice is detectable.
    """
    _check_header(arquivo, table, list(columns), _table_columns(conn, table))

    target = sql.Identifier("raw", table)
    copy_statement = sql.SQL("copy {} ({}) from stdin").format(
        target, sql.SQL(", ").join(map(sql.Identifier, columns))
    )

    digest = hashlib.sha256()
    with conn.transaction():
        conn.execute(sql.SQL("truncate {} restart identity").format(target))
        with conn.cursor() as cur:
            with cur.copy(copy_statement) as copy:
                for row in rows:
                    digest.update(json.dumps(row, ensure_ascii=False).encode() + b"\n")
                    copy.write_row(row)
            count = cur.rowcount
        conn.execute(
            """
            insert into raw.cargas (arquivo, sha256, linhas, atualizado_na_fonte)
            values (%s, %s, %s, %s)
            on conflict (arquivo) do update
                set sha256 = excluded.sha256, linhas = excluded.linhas,
                    atualizado_na_fonte = excluded.atualizado_na_fonte, carregado_em = now()
            """,
            (arquivo, digest.hexdigest(), count, atualizado_na_fonte),
        )
    return count
