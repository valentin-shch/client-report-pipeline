import json
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

ENTRY = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")
NOW = datetime.now(timezone.utc)


@pytest.fixture
def app_url(db):
    url = os.environ.get("TEST_APP_DATABASE_URL")
    if not url:
        pytest.skip("TEST_APP_DATABASE_URL is not set")
    st.cache_data.clear()
    return url


def add_run(db, client, batch, status="succeeded", minutes_ago=10, error=None, step="build",
            alerts=0, retries=0):
    started = NOW - timedelta(minutes=minutes_ago)
    steps = [{"step": "ingest", "seconds": 7.6, "rows": 28}, {"step": "clean", "seconds": 6.9, "rows": 4587}]
    if status == "succeeded":
        steps.append({"step": "build", "seconds": 1.2, "rows": 1})
    dq = {"rows_in": {"raw_ads": 4587}, "duplicates_collapsed_at_ingest": 3,
          "conversion_value_imputed": {"rows_imputed": 141}, "fx_stale_days": 0} if status == "succeeded" else None
    run_id = db.execute("""
        insert into runs (client, period, anchor, period_start, period_end, trigger, status, step,
                          retries, error, rows_ingested, steps, dq_summary, started_at, finished_at, batch)
        values (%s, 'last-week', '2025-03-19', '2025-03-10', '2025-03-16', 'schedule', %s, %s,
                %s, %s, 28, %s, %s, %s, %s, %s)
        returning id""",
        (client, status, step, retries, error, json.dumps(steps), json.dumps(dq) if dq else None,
         started, started + timedelta(seconds=54), batch)).fetchone()[0]
    if status == "succeeded":
        db.execute("""
            insert into reports (run_id, client, period, period_start, period_end, theme, subject, html, alerts)
            values (%s, %s, 'last-week', '2025-03-10', '2025-03-16', 'northlight', 's', '<p>r</p>', %s)
            on conflict (client, period, period_start, theme)
            do update set run_id = excluded.run_id, alerts = excluded.alerts""",
                   (run_id, client, json.dumps([{"headline": "x"}] * alerts)))
    db.commit()


def run_page(url):
    at = AppTest.from_file(ENTRY, default_timeout=60)
    os.environ["APP_DATABASE_URL"] = url
    try:
        return at.run()
    finally:
        del os.environ["APP_DATABASE_URL"]


def cards(at):
    # AppTest reports an expander with an icon as a status element
    return list(at.expander) + list(at.status)


def text(at):
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption]
    parts += [e.label for e in cards(at)] + [i.value for i in at.info] + [w.value for w in at.warning]
    parts += [s.value for s in at.subheader]
    return "\n".join(parts)


def test_runs_is_the_landing_page_and_explains_itself(app_url):
    at = run_page(app_url)
    assert not at.exception
    assert at.title[0].value == "Client Report Pipeline"
    assert "synthetic" in text(at).lower()


def test_the_last_run_card_shows_the_newest_batch(db, app_url):
    add_run(db, "Solmar Hotels", "old", minutes_ago=60 * 24 * 7)
    add_run(db, "Solmar Hotels", "new", alerts=2)
    add_run(db, "Nordfit Equipment", "new", status="failed", step="ingest",
            error="PermanentError: /v1/fx/usd-eur: HTTP 401")
    at = run_page(app_url)
    assert not at.exception
    shown = text(at)
    assert "1 of 2 clients succeeded" in shown
    assert "2 alerts" in shown
    assert "failed at ingest" in shown


def test_errors_show_their_type_only(db, app_url):
    add_run(db, "Nordfit Equipment", "b", status="failed", step="ingest",
            error="ConnectionRefusedError: owner@private.example could not be reached")
    shown = text(run_page(app_url))
    assert "ConnectionRefusedError" in shown
    assert "owner@private.example" not in shown


def test_history_has_one_card_per_run_with_its_detail(db, app_url):
    add_run(db, "Solmar Hotels", "b1", minutes_ago=200, retries=2)
    add_run(db, "Solmar Hotels", "b2", minutes_ago=100)
    add_run(db, "Nordfit Equipment", "b2", minutes_ago=100)
    at = run_page(app_url)
    assert len(cards(at)) == 3
    assert any("Solmar Hotels" in e.label for e in cards(at))
    detail = text(at)
    assert "ingest 7.6 s" in detail
    assert "2 retries" in detail
    assert "141 imputed" in detail


def test_no_runs_yet_is_said_plainly(app_url):
    at = run_page(app_url)
    assert not at.exception
    assert "No runs yet" in text(at)


def test_an_unreachable_database_shows_a_friendly_message():
    st.cache_data.clear()
    at = run_page("postgresql://app:x@127.0.0.1:1/crp_test?connect_timeout=2")
    assert not at.exception
    assert "waking up" in text(at)


def test_no_database_configured_says_so(monkeypatch):
    st.cache_data.clear()
    monkeypatch.delenv("APP_DATABASE_URL", raising=False)
    at = AppTest.from_file(ENTRY, default_timeout=60).run()
    assert not at.exception
    assert "isn't connected" in text(at)


FAILING_PAGE = """
import os, sys
sys.path[:0] = [{root!r}, {app!r}]
import psycopg
import streamlit as st
from control import stop_if_unavailable
os.environ["APP_DATABASE_URL"] = "postgresql://unused"

def load(url):
    raise psycopg.errors.UndefinedColumn("column r.batch does not exist SELECT secret_table")

stop_if_unavailable(load)
st.markdown("should not get here")
"""


def test_any_other_database_error_shows_a_plain_message_not_a_traceback():
    root = Path(__file__).resolve().parents[1]
    script = FAILING_PAGE.format(root=str(root), app=str(root / "app"))
    at = AppTest.from_string(script, default_timeout=30).run()
    assert not at.exception
    shown = "\n".join(e.value for e in at.error)
    assert "can't read" in shown
    assert "secret_table" not in shown
    assert "should not get here" not in text(at)


def test_the_other_pages_are_linked_on_the_page_itself(db, app_url):
    # on a phone the top menu collapses behind a button, so the page links them too
    add_run(db, "Solmar Hotels", "b")
    at = run_page(app_url)
    labels = [link.label for link in at.get("page_link")]
    assert "Report preview" in labels and "Alerts" in labels


def test_one_client_reads_in_the_singular(db, app_url):
    add_run(db, "Solmar Hotels", "b")
    assert "1 of 1 client succeeded" in text(run_page(app_url))


def test_an_abandoned_run_says_so_instead_of_a_misleading_duration(db, app_url):
    add_run(db, "Solmar Hotels", "b", status="failed", step="ingest", error="abandoned")
    db.execute("update runs set finished_at = started_at + interval '62 minutes'")
    db.commit()
    label = cards(run_page(app_url))[0].label
    assert "abandoned" in label
    assert "3720 s" not in label
