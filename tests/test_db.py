import psycopg
import pytest

from pipeline.db import TABLES, connect, init_schema, read_frame


def test_init_schema_is_idempotent(pg_url):
    with connect(pg_url) as conn:
        init_schema(conn)
        init_schema(conn)
        tables = read_frame(
            conn, "select table_name from information_schema.tables where table_schema = 'public'"
        )
    assert set(TABLES) <= set(tables["table_name"])


def test_read_frame_uses_params_and_column_names(db):
    db.execute("insert into raw_fx (date, usd_eur) values ('2025-01-01', 0.9), ('2025-01-02', 0.8)")
    out = read_frame(db, "select usd_eur as rate from raw_fx where date = %s", ("2025-01-02",))
    assert list(out.columns) == ["rate"]
    assert out["rate"].tolist() == [0.8]


def test_read_frame_keeps_columns_on_an_empty_result(db):
    out = read_frame(db, "select date, usd_eur from raw_fx")
    assert list(out.columns) == ["date", "usd_eur"]
    assert out.empty


def test_app_role_can_read_but_not_write(db):
    db.execute("set role app")
    db.execute("select count(*) from raw_ads")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("insert into raw_fx (date, usd_eur) values ('2025-01-01', 0.9)")


def test_pipeline_role_can_write_but_not_drop(db):
    db.execute("set role pipeline")
    db.execute("insert into raw_fx (date, usd_eur) values ('2025-01-01', 0.9)")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("drop table raw_fx")


def test_connect_without_url_says_so(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
        connect()
