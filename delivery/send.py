"""Approval and sending. A report only ever goes out by being claimed, once, by
a single UPDATE, so a double click or two app instances can't send it twice.

If a process dies between the claim and the email, the report stays `sending`
for a person to look at. That's deliberate: a late email beats a duplicate one.
"""

from __future__ import annotations

import os

import psycopg

from pipeline.ingest import load_client_config

DAILY_SEND_CAP = 10
SEND_LOCK = 7401  # any fixed number: it only has to be the same for every sender


def recipients_for(client: str) -> list[str]:
    # Only ever from config: nothing that reaches this code can name an address.
    config = next((c for c in load_client_config().values() if c["name"] == client), None)
    if config is None or not config.get("recipients"):
        raise ValueError(f"no recipients configured for {client}")
    demo = os.environ.get("DEMO_RECIPIENT")
    return [demo] if demo else config["recipients"]


def approve(conn: psycopg.Connection, report_id: int) -> bool:
    row = conn.execute("""
        UPDATE reports SET status = 'approved', approved_at = now()
        WHERE id = %s AND status = 'pending' RETURNING id""", (report_id,)).fetchone()
    conn.commit()
    return row is not None


def _sends_today(conn: psycopg.Connection) -> int:
    return conn.execute("""
        SELECT count(*) FROM reports
        WHERE status IN ('sent', 'sending') AND claimed_at >= date_trunc('day', now())""").fetchone()[0]


def send_report(conn: psycopg.Connection, report_id: int, mailer, cap: int | None = None) -> str:
    """"sent", "failed", "not_approved", "not_found" or "cap_reached"."""
    row = conn.execute("SELECT client, status FROM reports WHERE id = %s", (report_id,)).fetchone()
    conn.commit()
    if row is None:
        return "not_found"
    client, status = row
    if status != "approved":
        return "not_approved"

    to = recipients_for(client)
    cap = cap if cap is not None else int(os.environ.get("DAILY_SEND_CAP", DAILY_SEND_CAP))
    # Counting and claiming under one lock, or concurrent sends of different
    # reports all see room under the cap. Released by the commit.
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (SEND_LOCK,))
    if _sends_today(conn) >= cap:
        conn.commit()
        return "cap_reached"
    claimed = conn.execute("""
        UPDATE reports SET status = 'sending', claimed_at = now()
        WHERE id = %s AND status = 'approved' RETURNING subject, html""", (report_id,)).fetchone()
    conn.commit()
    if claimed is None:
        return "not_approved"

    subject, html = claimed
    try:
        mailer.send(to, subject, html)
    except Exception as e:  # any failure at all: a claimed report must not stay stuck
        conn.execute("""UPDATE reports SET status = 'send_failed', error = %s
                        WHERE id = %s AND status = 'sending'""",
                     (f"{type(e).__name__}: {e}"[:500], report_id))
        conn.commit()
        return "failed"
    conn.execute("""UPDATE reports SET status = 'sent', sent_at = now(), error = NULL
                    WHERE id = %s AND status = 'sending'""", (report_id,))
    conn.commit()
    return "sent"


def retry_send(conn: psycopg.Connection, report_id: int, mailer, cap: int | None = None) -> str:
    conn.execute("UPDATE reports SET status = 'approved' WHERE id = %s AND status = 'send_failed'",
                 (report_id,))
    conn.commit()
    return send_report(conn, report_id, mailer, cap)
