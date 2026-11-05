"""Raw tables -> clean tables, one client at a time.

    python -m pipeline.clean_db --client all

Separate from clean.py because that one also runs as a plain script
(`python pipeline/clean.py`), where this package's imports aren't available.
"""

from __future__ import annotations

import argparse

import pandas as pd
import psycopg
from psycopg import sql

from pipeline.clean import attribute_deals, build_summary, clean_ads
from pipeline.db import connect, read_frame
from pipeline.ingest import load_clients

ADS_COLUMNS = (
    "date", "client", "channel", "campaign_name", "spend", "impressions", "clicks", "conversions",
    "conversion_value", "conversion_value_imputed", "campaign_convention", "campaign_country",
    "campaign_type", "campaign_theme", "campaign_period",
)
DEAL_COLUMNS = (
    "deal_id", "client", "created_date", "closed_date", "stage", "deal_value", "source_campaign",
    "attribution_status", "attributed_channel",
)


def _read_raw(conn: psycopg.Connection, client: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ads = read_frame(conn, """
        SELECT date, client, channel, campaign_name, spend, impressions, clicks, conversions,
               conversion_value
        FROM raw_ads WHERE client = %s ORDER BY source, date, campaign_name""", (client,))
    deals = read_frame(conn, """
        SELECT deal_id, client, created_date, closed_date, stage, deal_value, source_campaign
        FROM raw_deals WHERE client = %s ORDER BY deal_id""", (client,))
    fx = read_frame(conn, "SELECT date, usd_eur FROM raw_fx ORDER BY date")

    ads["date"] = pd.to_datetime(ads["date"])
    ads["conversion_value"] = ads["conversion_value"].astype(float)  # None -> NaN
    deals["created_date"] = pd.to_datetime(deals["created_date"])
    deals["closed_date"] = pd.to_datetime(deals["closed_date"])
    fx["date"] = pd.to_datetime(fx["date"])
    return ads, deals, fx


def _copy_rows(cur: psycopg.Cursor, table: str, columns: tuple, frame: pd.DataFrame) -> None:
    statement = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(table), sql.SQL(", ").join(sql.Identifier(c) for c in columns))
    rows = frame[list(columns)].astype(object).where(frame[list(columns)].notna(), None)
    with cur.copy(statement) as copy:
        for row in rows.itertuples(index=False):
            copy.write_row(row)


def _as_dates(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = frame.copy()
    for column in columns:
        out[column] = pd.to_datetime(out[column]).dt.date
    return out


def clean_client_db(conn: psycopg.Connection, client: str) -> dict:
    ads, deals, fx = _read_raw(conn, client)
    # End the transaction the reads opened. Otherwise conn.transaction() below
    # is only a savepoint inside it, and nothing is committed when it closes.
    conn.commit()
    if ads.empty:
        raise ValueError(f"no raw rows for {client}; ingest it first")
    if fx.empty:
        raise ValueError("no FX rates; ingest them first")

    rows_in = {"raw_ads": len(ads), "raw_deals": len(deals)}
    # Rates are carried forward over gaps, so say how far they've been stretched.
    fx_stale_days = int((ads["date"].max() - fx["date"].max()).days)
    ads, stats = clean_ads(ads, fx)
    deals = attribute_deals(deals, ads)

    # One transaction: a failure part-way leaves the previous clean rows, so a
    # report can never be built from half a client.
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("DELETE FROM clean_ads WHERE client = %s", (client,))
        cur.execute("DELETE FROM clean_deals WHERE client = %s", (client,))
        _copy_rows(cur, "clean_ads", ADS_COLUMNS, _as_dates(ads, ["date"]))
        _copy_rows(cur, "clean_deals", DEAL_COLUMNS, _as_dates(deals, ["created_date", "closed_date"]))
    return {**build_summary(rows_in, stats, ads, deals), "fx_stale_days": fx_stale_days}


def main(argv=None) -> None:
    clients = load_clients()
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", default="all", choices=["all", *clients])
    args = parser.parse_args(argv)

    slugs = list(clients) if args.client == "all" else [args.client]
    with connect() as conn:
        for slug in slugs:
            s = clean_client_db(conn, clients[slug])
            print(f"{slug:<20}rows in {s['rows_in']['raw_ads']:>6}  out {s['rows_out']['ads_clean']:>6}  "
                  f"imputed {s['conversion_value_imputed']['rows_imputed']}  "
                  f"deals {s['rows_out']['crm_deals_clean']}")


if __name__ == "__main__":
    main()
