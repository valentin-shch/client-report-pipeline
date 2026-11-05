import random
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import psycopg
import pytest
from fastapi.testclient import TestClient

import runner
from adsapi.app import create_app
from adsapi.data import load_dataset
from pipeline.apiclient import AdsApi
from pipeline.db import read_frame

SOLMAR, NORDFIT = "solmar-hotels", "nordfit-equipment"
TODAY = date(2025, 3, 19)  # a Wednesday; the last full week is 10-16 March


@pytest.fixture(scope="module")
def ds():
    return load_dataset(pd.Timestamp("2025-02-01"), pd.Timestamp("2025-06-30"), pd.Timestamp("2025-04-01"))


def make_api(ds, key="k", **kwargs):
    app = create_app(ds, "k", today=lambda: TODAY, rate_limit_per_min=10_000, **kwargs)
    return AdsApi(TestClient(app), key, sleep=lambda s: None)


@pytest.fixture
def api(ds):
    return make_api(ds)


def target(slug=SOLMAR):
    return runner.target_for(slug, "last-week", TODAY)


def runs(db):
    db.commit()
    return read_frame(db, "select * from runs order by id")


def test_target_for_is_the_last_full_week():
    t = target()
    assert (t.name, t.start, t.end) == ("Solmar Hotels", date(2025, 3, 10), date(2025, 3, 16))


def test_a_good_run_records_every_step(db, pg_url, api):
    result = runner.run_client(pg_url, api, target(), "manual")
    assert result.status == "succeeded"
    run = runs(db).iloc[0]
    assert (run["client"], run["period"], run["trigger"]) == ("Solmar Hotels", "last-week", "manual")
    assert run["status"] == "succeeded" and run["error"] is None
    assert run["period_start"] == date(2025, 3, 10) and run["anchor"] == TODAY
    assert [s["step"] for s in run["steps"]] == ["ingest", "clean"]
    assert run["rows_ingested"] > 0
    assert run["dq_summary"]["rows_out"]["ads_clean"] > 0
    assert run["dq_summary"]["fx_stale_days"] <= 4
    assert run["finished_at"] is not None


def test_clean_rows_are_there_after_a_run(db, pg_url, api):
    runner.run_client(pg_url, api, target(), "manual")
    db.commit()
    count = db.execute("select count(*) from clean_ads where client = 'Solmar Hotels'").fetchone()[0]
    assert count > 0


def test_a_wrong_key_fails_at_once_and_says_so(db, pg_url, ds):
    result = runner.run_client(pg_url, make_api(ds, key="wrong"), target(), "manual")
    assert result.status == "failed"
    run = runs(db).iloc[0]
    assert run["status"] == "failed"
    assert run["step"] == "ingest"
    assert "PermanentError" in run["error"] and "401" in run["error"]
    assert run["retries"] == 0
    assert run["finished_at"] is not None


def test_stored_errors_hold_no_secrets(db, pg_url, ds):
    runner.run_client(pg_url, make_api(ds, key="wrong-secret-key"), target(), "manual")
    run = runs(db).iloc[0]
    assert "wrong-secret-key" not in run["error"]
    password = pg_url.split("@")[0].split(":")[-1]
    assert password not in run["error"]


def test_one_client_failing_never_stops_the_next(db, pg_url, api, monkeypatch):
    real = runner.ingest_client

    def flaky(conn, api_, slug):
        if slug == SOLMAR:
            raise RuntimeError("solmar broke")
        return real(conn, api_, slug)
    monkeypatch.setattr(runner, "ingest_client", flaky)

    results = runner.run_all(pg_url, api, [target(SOLMAR), target(NORDFIT)], "schedule")
    assert [r.status for r in results] == ["failed", "succeeded"]
    assert list(runs(db)["status"]) == ["failed", "succeeded"]


def test_a_database_failure_does_not_poison_the_next_client(db, pg_url, api, monkeypatch):
    real = runner.clean_client_db

    def bad_sql(conn, name):
        if name == "Solmar Hotels":
            conn.execute("select * from no_such_table")
        return real(conn, name)
    monkeypatch.setattr(runner, "clean_client_db", bad_sql)

    results = runner.run_all(pg_url, api, [target(SOLMAR), target(NORDFIT)], "schedule")
    assert [r.status for r in results] == ["failed", "succeeded"]
    assert runs(db).iloc[0]["step"] == "clean"


def test_retries_are_counted_per_run_not_across_clients(db, pg_url, api, monkeypatch):
    real = runner.ingest_client
    extra = {SOLMAR: 3, NORDFIT: 2}

    def with_retries(conn, api_, slug):
        api_.retries += extra[slug]
        return real(conn, api_, slug)
    monkeypatch.setattr(runner, "ingest_client", with_retries)

    runner.run_all(pg_url, api, [target(SOLMAR), target(NORDFIT)], "schedule")
    assert runs(db)["retries"].tolist() == [3, 2]


def test_real_faults_show_up_as_retries_on_the_run(db, pg_url, ds):
    api = make_api(ds, fault_rate=0.25, rng=random.Random(1))
    assert runner.run_client(pg_url, api, target(SOLMAR), "schedule").status == "succeeded"
    assert runs(db).iloc[0]["retries"] == api.retries > 0


def old_run(db, status, hours_ago=2, client="Solmar Hotels", anchor=TODAY):
    t = target()
    started = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    db.execute("""insert into runs (client, period, anchor, period_start, period_end, trigger,
                                    status, started_at)
                  values (%s, 'last-week', %s, %s, %s, 'schedule', %s, %s)""",
               (client, anchor, t.start, t.end, status, started))
    db.commit()


def test_old_running_rows_become_abandoned(db):
    old_run(db, "running", hours_ago=2)
    assert runner.mark_abandoned(db) == 1
    run = runs(db).iloc[0]
    assert run["status"] == "failed"
    assert run["error"] == "abandoned"
    assert run["finished_at"] is not None


def test_a_recent_running_row_is_left_alone(db):
    old_run(db, "running", hours_ago=0)
    assert runner.mark_abandoned(db) == 0
    assert runs(db).iloc[0]["status"] == "running"


def test_failed_targets_finds_the_failure(db):
    old_run(db, "failed")
    assert [(t.slug, t.anchor) for t in runner.failed_targets(db)] == [(SOLMAR, TODAY)]


def test_a_failure_fixed_by_a_later_success_is_not_rerun(db):
    old_run(db, "failed", hours_ago=3)
    old_run(db, "succeeded", hours_ago=1)
    assert runner.failed_targets(db) == []


def test_a_success_followed_by_a_failure_is_rerun(db):
    old_run(db, "succeeded", hours_ago=3)
    old_run(db, "failed", hours_ago=1)
    assert len(runner.failed_targets(db)) == 1


def test_old_failures_are_not_picked_up(db):
    old_run(db, "failed", hours_ago=24 * 8)
    assert runner.failed_targets(db) == []


def test_failures_for_a_client_no_longer_configured_are_ignored(db):
    old_run(db, "failed", client="Gone Client")
    assert runner.failed_targets(db) == []


def use(monkeypatch, api, pg_url):
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setattr(runner.AdsApi, "from_env", classmethod(lambda cls: api))


def test_main_exits_zero_when_everything_worked(db, pg_url, api, monkeypatch):
    use(monkeypatch, api, pg_url)
    args = ["--client", SOLMAR, "--anchor", TODAY.isoformat(), "--trigger", "schedule"]
    assert runner.main(args) == 0
    assert list(runs(db)["trigger"]) == ["schedule"]


def test_main_exits_one_when_a_client_failed(db, pg_url, ds, monkeypatch):
    use(monkeypatch, make_api(ds, key="wrong"), pg_url)
    assert runner.main(["--client", SOLMAR, "--anchor", TODAY.isoformat()]) == 1


def test_main_marks_abandoned_runs_first(db, pg_url, api, monkeypatch):
    use(monkeypatch, api, pg_url)
    old_run(db, "running", hours_ago=2, client="Clinica Vantia")
    runner.main(["--client", SOLMAR, "--anchor", TODAY.isoformat()])
    assert runs(db).iloc[0]["error"] == "abandoned"


def test_retry_failed_reruns_only_the_failures_then_has_nothing_to_do(db, pg_url, ds, api, monkeypatch, capsys):
    runner.run_client(pg_url, make_api(ds, key="wrong"), target(SOLMAR), "schedule")
    runner.run_client(pg_url, api, target(NORDFIT), "schedule")

    use(monkeypatch, api, pg_url)
    assert runner.main(["--retry-failed"]) == 0
    latest = runs(db).iloc[-1]
    assert (latest["client"], latest["status"], latest["trigger"]) == ("Solmar Hotels", "succeeded", "manual")
    assert latest["anchor"] == TODAY
    assert len(runs(db)) == 3

    assert runner.main(["--retry-failed"]) == 0
    assert len(runs(db)) == 3
    assert "nothing to retry" in capsys.readouterr().out


def test_main_rejects_an_unknown_client():
    with pytest.raises(SystemExit):
        runner.main(["--client", "nope"])


def failing_connects(monkeypatch, *which, error=None):
    """runner.connect raises on the given calls, counting from 1."""
    real, calls = runner.connect, {"n": 0}

    def connect(url=None):
        calls["n"] += 1
        if calls["n"] in which:
            raise error or psycopg.OperationalError("connection dropped")
        return real(url)
    monkeypatch.setattr(runner, "connect", connect)
    monkeypatch.setattr(runner, "FINISH_WAITS", (0, 0))
    return calls


def test_failing_to_start_a_run_never_stops_the_next(db, pg_url, api, monkeypatch):
    failing_connects(monkeypatch, 1)
    results = runner.run_all(pg_url, api, [target(SOLMAR), target(NORDFIT)], "schedule")
    assert [r.status for r in results] == ["failed", "succeeded"]
    assert "connection dropped" in results[0].error
    assert list(runs(db)["client"]) == ["Nordfit Equipment"]


def test_losing_the_database_during_the_work_is_recorded(db, pg_url, api, monkeypatch):
    failing_connects(monkeypatch, 2)
    result = runner.run_client(pg_url, api, target(), "schedule")
    assert result.status == "failed"
    run = runs(db).iloc[0]
    assert run["status"] == "failed"
    assert "OperationalError" in run["error"]


def test_recording_the_result_is_retried(db, pg_url, api, monkeypatch):
    failing_connects(monkeypatch, 3, 4)  # start, work, then the first two finish attempts
    result = runner.run_client(pg_url, api, target(), "schedule")
    assert result.status == "succeeded"
    assert runs(db).iloc[0]["status"] == "succeeded"


def test_failing_to_record_a_result_never_stops_the_next(db, pg_url, api, monkeypatch):
    failing_connects(monkeypatch, 3, 4, 5)
    results = runner.run_all(pg_url, api, [target(SOLMAR), target(NORDFIT)], "schedule")
    assert [r.status for r in results] == ["failed", "succeeded"]
    # stuck on running until the next run's housekeeping, which is what it's for
    assert list(runs(db)["status"]) == ["running", "succeeded"]


def test_a_real_connection_failure_stores_no_password(db, pg_url, api, monkeypatch):
    real, calls = runner.connect, {"n": 0}

    def connect(url=None):
        calls["n"] += 1
        return real("postgresql://postgres:s3cret-pw@127.0.0.1:1/x?connect_timeout=2" if calls["n"] == 2 else url)
    monkeypatch.setattr(runner, "connect", connect)

    runner.run_client(pg_url, api, target(), "schedule")
    run = runs(db).iloc[0]
    assert run["status"] == "failed"
    assert run["error"]
    assert "s3cret-pw" not in run["error"]


@pytest.mark.parametrize("extra", [
    ["--client", SOLMAR], ["--anchor", "2025-03-19"], ["--period", "last-month"], ["--trigger", "schedule"],
], ids=["client", "anchor", "period", "trigger"])
def test_retry_failed_refuses_other_options(extra):
    with pytest.raises(SystemExit) as e:
        runner.main(["--retry-failed", *extra])
    assert e.value.code == 2
