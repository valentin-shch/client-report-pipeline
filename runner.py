"""The unattended run: for each client, ingest, clean and build a report, every
step recorded. Reports wait for approval; nothing is emailed from here.

    python -m runner --trigger schedule
    python -m runner --client nordfit-equipment --anchor 2026-10-05
    python -m runner --retry-failed

One client failing never stops the others, and a failed run stays in the runs
table with its error until a re-run picks it up. Exits 1 if any client failed,
so a scheduled job shows red.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone

import psycopg
from psycopg.types.json import Jsonb

from delivery.slack import post_summary
from pipeline.apiclient import AdsApi
from pipeline.clean_db import clean_client_db
from pipeline.db import connect
from pipeline.ingest import ingest_client, ingest_fx, load_client_config, load_clients
from pipeline.metrics import period_windows
from reports.report import build_report, render_html
from reports.store import load_clean_ads, save_report
from reports.theme import load_theme

PERIODS = ("last-week", "last-month")
RETRY_WINDOW_DAYS = 7
FINISH_WAITS = (2, 8)


@dataclass
class RunTarget:
    slug: str
    name: str
    period: str
    anchor: date
    start: date
    end: date


@dataclass
class RunResult:
    slug: str
    status: str
    error: str | None = None
    report: str | None = None
    alerts: int = 0


def target_for(slug: str, period: str, anchor: date) -> RunTarget:
    (start, end), _ = period_windows(anchor, period)
    return RunTarget(slug, load_clients()[slug], period, anchor, start.date(), end.date())


def mark_abandoned(conn: psycopg.Connection) -> int:
    """A job killed mid-run can't record its own failure, so the next run does."""
    cur = conn.execute("""
        UPDATE runs SET status = 'failed', error = 'abandoned', finished_at = now()
        WHERE status = 'running' AND started_at < now() - interval '1 hour'""")
    conn.commit()
    return cur.rowcount


def failed_targets(conn: psycopg.Connection) -> list[RunTarget]:
    # Latest run per client and period: a failure a later run already fixed
    # isn't a failure any more.
    rows = conn.execute("""
        SELECT DISTINCT ON (client, period, period_start) client, period, anchor, status
        FROM runs
        WHERE started_at > now() - %s * interval '1 day'
        ORDER BY client, period, period_start, started_at DESC""", (RETRY_WINDOW_DAYS,)).fetchall()
    conn.commit()
    slugs = {name: slug for slug, name in load_clients().items()}
    return [target_for(slugs[client], period, anchor)
            for client, period, anchor, status in rows
            if status == "failed" and client in slugs]


def _start(conn: psycopg.Connection, t: RunTarget, trigger: str) -> int:
    return conn.execute("""
        INSERT INTO runs (client, period, anchor, period_start, period_end, trigger, status)
        VALUES (%s, %s, %s, %s, %s, %s, 'running') RETURNING id""",
                        (t.name, t.period, t.anchor, t.start, t.end, trigger)).fetchone()[0]


def _begin_step(conn: psycopg.Connection, run_id: int, step: str) -> float:
    conn.execute("UPDATE runs SET step = %s WHERE id = %s", (step, run_id))
    conn.commit()  # committed now, so a failure knows where it happened
    return time.monotonic()


def _end_step(conn: psycopg.Connection, run_id: int, step: str, began: float, rows: int) -> None:
    entry = {"step": step, "seconds": round(time.monotonic() - began, 1), "rows": rows}
    conn.execute("UPDATE runs SET steps = steps || %s WHERE id = %s", (Jsonb([entry]), run_id))
    conn.commit()


def _work(conn: psycopg.Connection, run_id: int, api: AdsApi, t: RunTarget,
          force: bool) -> tuple[dict, str, int]:
    began = _begin_step(conn, run_id, "ingest")
    # FX here rather than once per batch: if it fails, this run shows it and
    # --retry-failed covers it, with no batch-level state to manage.
    ingest_fx(conn, api)
    stats = ingest_client(conn, api, t.slug)
    ingested = sum(s.rows_written for s in stats)
    conn.execute("UPDATE runs SET rows_ingested = %s WHERE id = %s", (ingested, run_id))
    _end_step(conn, run_id, "ingest", began, ingested)

    began = _begin_step(conn, run_id, "clean")
    summary = clean_client_db(conn, t.name)
    _end_step(conn, run_id, "clean", began, summary["rows_out"]["ads_clean"])

    began = _begin_step(conn, run_id, "build")
    theme_name = load_client_config()[t.slug]["theme"]
    theme = load_theme(theme_name)
    report = build_report(load_clean_ads(conn, t.name), t.name, t.anchor, t.period, theme.accent)
    outcome = save_report(conn, run_id, t, report, render_html(report, theme), theme_name, force)
    _end_step(conn, run_id, "build", began, 1)

    duplicates = sum(s.duplicates_collapsed for s in stats)
    return {**summary, "duplicates_collapsed_at_ingest": duplicates}, outcome, len(report.alerts)


def run_client(url: str | None, api: AdsApi, t: RunTarget, trigger: str,
               force: bool = False) -> RunResult:
    # A connection per phase: if the database drops mid-work (Neon suspends),
    # recording the failure still gets a working one.
    with connect(url) as conn:
        run_id = _start(conn, t, trigger)

    retries_before = api.retries
    status, error, dq, report, alerts = "succeeded", None, None, None, 0
    try:
        with connect(url) as conn:
            dq, report, alerts = _work(conn, run_id, api, t, force)
    except Exception as e:  # the isolation boundary: whatever broke, record it and move on
        status, error = "failed", f"{type(e).__name__}: {e}"[:500]

    outcome = (status, error, api.retries - retries_before, Jsonb(dq) if dq else None, run_id)
    _record(url, outcome)
    return RunResult(t.slug, status, error, report, alerts)


def _record(url: str | None, outcome: tuple) -> None:
    # The work is done, so ride out a short outage rather than lose the result.
    for wait in (*FINISH_WAITS, None):
        try:
            with connect(url) as conn:
                conn.execute("""
                    UPDATE runs SET status = %s, error = %s, retries = %s, dq_summary = %s,
                                    finished_at = now()
                    WHERE id = %s""", outcome)
            return
        except psycopg.OperationalError:
            if wait is None:
                raise
            time.sleep(wait)


def run_all(url: str | None, api: AdsApi, targets: list[RunTarget], trigger: str,
            force: bool = False) -> list[RunResult]:
    results = []
    for t in targets:
        try:
            results.append(run_client(url, api, t, trigger, force))
        except psycopg.Error as e:
            # run_client records its own failures. This one is the database
            # refusing even that, and it still mustn't stop the next client.
            results.append(RunResult(t.slug, "failed", f"{type(e).__name__}: {e}"[:500]))
    return results


def main(argv=None) -> int:
    clients = load_clients()
    parser = argparse.ArgumentParser(prog="python -m runner")
    parser.add_argument("--client", choices=["all", *clients], help="default: all")
    parser.add_argument("--period", choices=PERIODS, help="default: last-week")
    parser.add_argument("--anchor", type=date.fromisoformat, metavar="YYYY-MM-DD",
                        help="date the period is measured back from (default: today)")
    parser.add_argument("--trigger", choices=("schedule", "manual"), help="default: manual")
    parser.add_argument("--retry-failed", action="store_true",
                        help=f"re-run failed runs from the last {RETRY_WINDOW_DAYS} days")
    parser.add_argument("--force", action="store_true",
                        help="rebuild reports even if already approved or sent")
    args = parser.parse_args(argv)
    if args.retry_failed and (args.client or args.period or args.anchor or args.trigger or args.force):
        parser.error("--retry-failed re-runs what failed, as it was; it takes no other options")
    today = datetime.now(timezone.utc).date()
    if args.anchor and args.anchor > today:
        parser.error("--anchor can't be in the future: that week has no data yet")

    with connect() as conn:
        abandoned = mark_abandoned(conn)
        retrying = failed_targets(conn) if args.retry_failed else None
    if abandoned:
        print(f"marked {abandoned} abandoned run(s) as failed")

    if retrying == []:
        print("nothing to retry")
        return 0
    if retrying is None:
        anchor = args.anchor or today
        slugs = list(clients) if args.client in (None, "all") else [args.client]
        targets = [target_for(slug, args.period or "last-week", anchor) for slug in slugs]
    else:
        targets = retrying

    api = AdsApi.from_env()
    results = run_all(None, api, targets, args.trigger or "manual", args.force)
    for r in results:
        print(f"{r.slug:<20}{r.status}" + (f"  {r.error}" if r.error else f"  report {r.report}, {r.alerts} alert(s)"))
    print(f"retries: {api.retries}")
    post_summary(results)
    return 1 if any(r.status == "failed" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
