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


def add_run(db):
    db.execute("""insert into runs (client, period, anchor, period_start, period_end, trigger, status)
                  values ('A', 'last-week', '2025-03-10', '2025-03-03', '2025-03-09', 'manual', 'running')""")


def test_pipeline_role_can_record_runs(db):
    db.execute("set role pipeline")
    add_run(db)
    db.execute("update runs set status = 'succeeded'")


def test_app_role_can_read_runs_but_not_change_them(db):
    add_run(db)
    db.execute("set role app")
    db.execute("select * from runs")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("update runs set status = 'failed'")


def add_report(db):
    db.execute("""insert into reports (client, period, period_start, period_end, theme, subject, html)
                  values ('A', 'last-week', '2025-03-03', '2025-03-09', 'northlight', 's', 'h')""")


def test_app_role_can_move_a_report_on_but_not_change_what_it_says(db):
    add_report(db)
    db.execute("set role app")
    db.execute("update reports set status = 'approved', approved_at = now()")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("update reports set html = 'hacked'")


def test_app_role_cannot_add_reports(db):
    db.execute("set role app")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        add_report(db)


def test_pipeline_role_can_save_reports(db):
    db.execute("set role pipeline")
    add_report(db)
    db.execute("update reports set html = 'rebuilt'")
