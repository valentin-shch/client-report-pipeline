"""Fake ad API -> raw tables, incrementally.

    python -m pipeline.ingest --client all

Each source for each client is fetched completely, then written in one
transaction. If a fetch fails nothing is written for that source, so its
watermark stays put and the next run picks up exactly where this one should
have. Deals need this most: they're ordered by creation but filtered by update,
so a half-written fetch could move the watermark past updates it never saw.
"""

from __future__ import annotations

import argparse
import tomllib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import psycopg

from pipeline.apiclient import AdsApi
from pipeline.clean import RAW_FILES
from pipeline.db import connect

CLIENTS_FILE = Path(__file__).resolve().parent / "clients.toml"

# Before the data starts: LinkedIn's labels run a day behind, so its first row
# would be lost if the backfill started on the first real day.
BACKFILL_FROM = date(2025, 1, 1)
# Platforms restate recent days, so every run re-reads a few. Upserts make the
# overlap harmless.
OVERLAP_DAYS = 3

ADS_SOURCES = ("google_ads", "meta_ads", "linkedin_ads", "organic_search")
DATE_FORMATS = {Path(fname).stem: fmt for fname, fmt in RAW_FILES.values()}

UPSERT_AD = """
    INSERT INTO raw_ads (source, client, date, date_raw, channel, campaign_name, spend,
                         impressions, clicks, conversions, conversion_value)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (source, client, date, campaign_name) DO UPDATE SET
        date_raw = EXCLUDED.date_raw, channel = EXCLUDED.channel, spend = EXCLUDED.spend,
        impressions = EXCLUDED.impressions, clicks = EXCLUDED.clicks,
        conversions = EXCLUDED.conversions, conversion_value = EXCLUDED.conversion_value,
        ingested_at = now()
"""
UPSERT_DEAL = """
    INSERT INTO raw_deals (deal_id, client, created_date, closed_date, stage, deal_value,
                           source_campaign, updated_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (deal_id) DO UPDATE SET
        client = EXCLUDED.client, created_date = EXCLUDED.created_date,
        closed_date = EXCLUDED.closed_date, stage = EXCLUDED.stage,
        deal_value = EXCLUDED.deal_value, source_campaign = EXCLUDED.source_campaign,
        updated_at = EXCLUDED.updated_at, ingested_at = now()
"""
UPSERT_FX = """
    INSERT INTO raw_fx (date, usd_eur) VALUES (%s, %s)
    ON CONFLICT (date) DO UPDATE SET usd_eur = EXCLUDED.usd_eur, ingested_at = now()
"""


@dataclass
class IngestStats:
    source: str
    rows_received: int
    rows_written: int
    duplicates_collapsed: int
    since: date | None


def load_clients() -> dict[str, str]:
    with open(CLIENTS_FILE, "rb") as f:
        return {slug: cfg["name"] for slug, cfg in tomllib.load(f).items()}


def _last_seen(conn: psycopg.Connection, sql: str, params: tuple = ()) -> date | None:
    last = conn.execute(sql, params).fetchone()[0]
    conn.commit()  # don't hold a transaction open across the HTTP calls
    return last


def _since(last: date | None) -> date | None:
    return last - timedelta(days=OVERLAP_DAYS) if last else None


def _write(conn: psycopg.Connection, sql: str, rows: list[tuple]) -> None:
    if rows:
        with conn.transaction(), conn.cursor() as cur:
            cur.executemany(sql, rows)


def _ingest_ads(conn: psycopg.Connection, api: AdsApi, source: str, slug: str, name: str) -> IngestStats:
    last = _last_seen(conn, "SELECT max(date) FROM raw_ads WHERE source = %s AND client = %s",
                      (source, name))
    since = _since(last) or BACKFILL_FROM
    received = api.get_all(f"/v1/ads/{source}", {"client": slug, "since": since.isoformat()})

    rows, duplicates = {}, 0
    for r in received:
        day = datetime.strptime(r["date"], DATE_FORMATS[source]).date()
        key = (day, r["campaign_name"])
        # The overlap re-reads old days; a duplicate there was counted already.
        if key in rows and (last is None or day > last):
            duplicates += 1
        rows[key] = (
            source, name, day, r["date"], r["channel"], r["campaign_name"], r["spend"],
            r["impressions"], r["clicks"], r["conversions"], r["conversion_value"],
        )
    _write(conn, UPSERT_AD, list(rows.values()))
    return IngestStats(source, len(received), len(rows), duplicates, since)


def _ingest_deals(conn: psycopg.Connection, api: AdsApi, slug: str, name: str) -> IngestStats:
    since = _since(_last_seen(conn, "SELECT max(updated_at) FROM raw_deals WHERE client = %s", (name,)))
    params = {"client": slug, **({"updated_since": since.isoformat()} if since else {})}
    received = api.get_all("/v1/crm/deals", params)
    rows = [
        (r["deal_id"], name, r["created_date"], r["closed_date"], r["stage"], r["deal_value"],
         r["source_campaign"], r["updated_at"])
        for r in received
    ]
    _write(conn, UPSERT_DEAL, rows)
    return IngestStats("crm_deals", len(received), len(rows), 0, since)


def ingest_client(conn: psycopg.Connection, api: AdsApi, slug: str) -> list[IngestStats]:
    name = load_clients()[slug]
    stats = [_ingest_ads(conn, api, source, slug, name) for source in ADS_SOURCES]
    stats.append(_ingest_deals(conn, api, slug, name))
    return stats


def ingest_fx(conn: psycopg.Connection, api: AdsApi) -> IngestStats:
    since = _since(_last_seen(conn, "SELECT max(date) FROM raw_fx")) or BACKFILL_FROM
    received = api.get_all("/v1/fx/usd-eur", {"since": since.isoformat()})
    _write(conn, UPSERT_FX, [(r["date"], r["usd_eur"]) for r in received])
    return IngestStats("fx_rates", len(received), len(received), 0, since)


def _show(label: str, s: IngestStats) -> None:
    print(f"{label:<20}{s.source:<16}since {s.since}  received {s.rows_received:>6}  "
          f"written {s.rows_written:>6}  duplicates {s.duplicates_collapsed}")


def main(argv=None) -> None:
    clients = load_clients()
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", default="all", choices=["all", *clients])
    args = parser.parse_args(argv)

    slugs = list(clients) if args.client == "all" else [args.client]
    api = AdsApi.from_env()
    with connect() as conn:
        _show("-", ingest_fx(conn, api))
        for slug in slugs:
            for stats in ingest_client(conn, api, slug):
                _show(slug, stats)
    print(f"retries: {api.retries}")


if __name__ == "__main__":
    main()
