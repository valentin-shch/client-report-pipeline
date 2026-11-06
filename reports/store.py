"""Reports in the database: reading clean rows in, saving built reports out."""

from __future__ import annotations

from dataclasses import asdict

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from pipeline.db import read_frame
from reports.report import Report


def load_clean_ads(conn: psycopg.Connection, client: str) -> pd.DataFrame:
    ads = read_frame(conn, """
        SELECT * FROM clean_ads WHERE client = %s
        ORDER BY date, channel, campaign_name""", (client,))
    conn.commit()
    ads["date"] = pd.to_datetime(ads["date"])
    return ads


def save_report(conn: psycopg.Connection, run_id: int, target, report: Report, html: str,
                theme: str, force: bool = False) -> str:
    """"created", "replaced" or "kept". Once a report has been approved a
    person has made a decision about it, so a re-run leaves it alone unless
    told otherwise. Even then, never mid-send: the row would end up describing
    an email nobody received."""
    key = (target.name, target.period, target.start, theme)
    row = conn.execute("""
        SELECT status FROM reports
        WHERE client = %s AND period = %s AND period_start = %s AND theme = %s
        FOR UPDATE""", key).fetchone()

    subject = f"{target.name}: {report.period_label}"
    alerts = Jsonb([asdict(a) for a in report.alerts])
    if row is None:
        conn.execute("""
            INSERT INTO reports (run_id, client, period, period_start, period_end, theme,
                                 subject, html, alerts)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                     (run_id, *key[:3], target.end, theme, subject, html, alerts))
        outcome = "created"
    elif row[0] == "pending" or (force and row[0] != "sending"):
        conn.execute("""
            UPDATE reports SET run_id = %s, subject = %s, html = %s, alerts = %s, status = 'pending',
                               error = NULL, approved_at = NULL, claimed_at = NULL, sent_at = NULL
            WHERE client = %s AND period = %s AND period_start = %s AND theme = %s""",
                     (run_id, subject, html, alerts, *key))
        outcome = "replaced"
    else:
        outcome = "kept"
    conn.commit()
    return outcome
