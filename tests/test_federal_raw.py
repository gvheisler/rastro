import hashlib
import shutil

import pytest

from rastro.db import apply_sql
from rastro.ingest.federal import FILES, load_raw
from rastro.ingest.load import SchemaMismatchError, normalize_column
from support import FIXTURES, read_csv


@pytest.fixture
def raw_db(db):
    apply_sql(db, "01_raw.sql")
    load_raw(db, FIXTURES)
    return db


@pytest.mark.parametrize(("filename", "table"), FILES.items())
def test_raw_table_matches_csv_exactly(raw_db, filename, table):
    header, rows = read_csv(filename)
    columns = ", ".join(normalize_column(h) for h in header)
    loaded = raw_db.execute(f"select {columns} from raw.{table} order by linha_arquivo").fetchall()
    assert [list(r) for r in loaded] == rows


def test_load_is_idempotent(db):
    apply_sql(db, "01_raw.sql")
    load_raw(db, FIXTURES)
    load_raw(db, FIXTURES)
    for filename, table in FILES.items():
        _, rows = read_csv(filename)
        assert db.execute(f"select count(*) from raw.{table}").fetchone()[0] == len(rows)
    assert db.execute("select count(*) from raw.cargas").fetchone()[0] == len(FILES)


def test_load_records_checksum_and_row_count(raw_db):
    for filename in FILES:
        sha256, linhas = raw_db.execute(
            "select sha256, linhas from raw.cargas where arquivo = %s", (filename,)
        ).fetchone()
        assert sha256 == hashlib.sha256((FIXTURES / filename).read_bytes()).hexdigest()
        assert linhas == len(read_csv(filename)[1])


def test_load_rejects_changed_header(db, tmp_path):
    for filename in FILES:
        shutil.copy(FIXTURES / filename, tmp_path / filename)
    broken = tmp_path / "EmendasParlamentares.csv"
    raw = broken.read_bytes().replace("Valor Pago".encode("latin-1"), b"Valor Quitado", 1)
    broken.write_bytes(raw)
    apply_sql(db, "01_raw.sql")
    with pytest.raises(SchemaMismatchError, match="valor_quitado"):
        load_raw(db, tmp_path)
