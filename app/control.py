"""The control room's view of the database. The app connects as the `app` role,
which can read everything and change nothing but a report's status."""

from __future__ import annotations

import hmac
import os

import pandas as pd
import psycopg
import streamlit as st

from delivery.mailer import SmtpMailer
from delivery.send import approve, retry_send, send_report
from pipeline.db import read_frame

MAX_WRONG_PASSCODES = 5
PASSCODE_LOCK = 7402  # any fixed number, distinct from the send lock


def _setting(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    try:
        return st.secrets.get(name)
    except FileNotFoundError:  # no secrets.toml at all, the usual case locally
        return None


def database_url() -> str | None:
    return _setting("APP_DATABASE_URL")


def approval_passcode() -> str | None:
    return _setting("APPROVAL_PASSCODE")


def stop_if_unavailable(load, *args):
    """Run a loader, or say plainly why there's nothing to show. A sleeping
    Neon database answers in a few seconds; a traceback would just scare."""
    url = database_url()
    if not url:
        st.info("The control room isn't connected to a database here. "
                "Set APP_DATABASE_URL to point it at one.")
        st.stop()
    try:
        return load(url, *args)
    except psycopg.OperationalError:
        st.warning("The demo database is waking up. Refresh in a few seconds.",
                   icon=":material/hourglass_top:")
        st.stop()
    except psycopg.Error as e:
        # Anything else is a bug or a schema out of step. A public page says so
        # plainly; the details go to the server log, not the visitor.
        print(f"control room query failed: {type(e).__name__}: {e}")
        st.error("The control room can't read its data right now.", icon=":material/error:")
        st.stop()


@st.cache_data(ttl=60, show_spinner=False)
def load_runs(url: str, limit: int = 60) -> pd.DataFrame:
    with psycopg.connect(url, connect_timeout=10) as conn:
        return read_frame(conn, """
            SELECT r.id, r.client, r.period, r.period_start, r.period_end, r.trigger, r.status,
                   r.step, r.retries, r.error, r.rows_ingested, r.steps, r.dq_summary,
                   r.started_at, r.finished_at,
                   -- runs from before batches existed group by the hour they started
                   coalesce(r.batch, to_char(date_trunc('hour', r.started_at), 'YYYY-MM-DD HH24')) AS batch,
                   coalesce(jsonb_array_length(rep.alerts), 0) AS alerts
            FROM runs r LEFT JOIN reports rep ON rep.run_id = r.id
            ORDER BY r.started_at DESC LIMIT %s""", (limit,))


def error_type(error: str | None) -> str:
    # Only the exception's name goes on a public page: the message can carry
    # host names, or the demo inbox's address.
    return (error or "").split(":", 1)[0]


@st.cache_data(ttl=60, show_spinner=False)
def load_reports(url: str, limit: int = 30) -> pd.DataFrame:
    with psycopg.connect(url, connect_timeout=10) as conn:
        return read_frame(conn, """
            SELECT id, run_id, client, period_start, period_end, subject, status, error,
                   jsonb_array_length(alerts) AS alerts, approved_at, sent_at, created_at
            FROM reports ORDER BY coalesce(sent_at, approved_at, created_at) DESC LIMIT %s""", (limit,))


@st.cache_data(ttl=60, show_spinner=False, max_entries=20)
def report_html(url: str, report_id: int, run_id: int) -> str | None:
    """The report as that run built it, or None if a later run has replaced it."""
    with psycopg.connect(url, connect_timeout=10) as conn:
        row = conn.execute("SELECT html FROM reports WHERE id = %s AND run_id = %s",
                           (report_id, run_id)).fetchone()
    return row[0] if row else None


def try_passcode(url: str, entered: str, passcode: str) -> str:
    """"ok", "wrong" or "locked". The count is in the database, so a fresh
    session or a second tab doesn't reset it."""
    with psycopg.connect(url, connect_timeout=10) as conn:
        # One check at a time across every session, or parallel guesses would
        # all see room under the limit.
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (PASSCODE_LOCK,))
        # Locked for an hour from the fifth wrong try in any hour, not merely
        # while five sit in the last hour, which lets a guesser pace themselves.
        locked = conn.execute("""
            SELECT coalesce(max(at) + interval '1 hour' > now(), false) FROM (
                SELECT at, count(*) OVER (ORDER BY at RANGE BETWEEN interval '1 hour' PRECEDING
                                          AND CURRENT ROW) AS n
                FROM approval_attempts WHERE NOT ok AND at > now() - interval '2 hours') tries
            WHERE n >= %s""", (MAX_WRONG_PASSCODES,)).fetchone()[0]
        if locked:
            return "locked"  # not recorded, so waiting it out really ends it
        ok = hmac.compare_digest(entered.encode(), passcode.encode())
        conn.execute("INSERT INTO approval_attempts (ok) VALUES (%s)", (ok,))
    return "ok" if ok else "wrong"


def approve_and_send(url: str, report_id: int, run_id: int) -> str:
    try:
        mailer = SmtpMailer.from_env()
    except RuntimeError:
        return "no_mailer"  # checked before approving, so nothing is left half done
    with psycopg.connect(url, connect_timeout=10) as conn:
        if not approve(conn, report_id, run_id):
            outcome = "changed"
        else:
            outcome = send_report(conn, report_id, mailer)
    _forget_reports()
    return outcome


def _forget_reports() -> None:
    # Only the report lists: the shared clean-data and preview caches stay warm.
    load_reports.clear()
    report_html.clear()


def retry(url: str, report_id: int) -> str:
    try:
        mailer = SmtpMailer.from_env()
    except RuntimeError:
        return "no_mailer"
    with psycopg.connect(url, connect_timeout=10) as conn:
        outcome = retry_send(conn, report_id, mailer)
    _forget_reports()
    return outcome


@st.cache_data(ttl=600, show_spinner="Loading the data…")
def load_clean_ads(url: str) -> pd.DataFrame:
    with psycopg.connect(url, connect_timeout=10) as conn:
        ads = read_frame(conn, "SELECT * FROM clean_ads ORDER BY client, date, channel, campaign_name")
    ads["date"] = pd.to_datetime(ads["date"])
    return ads
