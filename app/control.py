"""The control room's view of the database. The app connects as the `app` role,
which can read everything and change nothing but a report's status."""

from __future__ import annotations

import os

import pandas as pd
import psycopg
import streamlit as st

from pipeline.db import read_frame


def database_url() -> str | None:
    url = os.environ.get("APP_DATABASE_URL")
    if url:
        return url
    try:
        return st.secrets.get("APP_DATABASE_URL")
    except FileNotFoundError:  # no secrets.toml at all, the usual case locally
        return None


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
