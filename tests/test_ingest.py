from datetime import date, timedelta

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from adsapi.app import create_app
from adsapi.data import ads_rows, load_dataset
from pipeline.apiclient import AdsApi, RetriesExhausted
from pipeline.db import read_frame
from pipeline.ingest import main as ingest_main
from pipeline.ingest import (ADS_SOURCES, BACKFILL_FROM, OVERLAP_DAYS, ingest_client, ingest_fx,
                             load_clients)

SLUG, NAME = "solmar-hotels", "Solmar Hotels"
ALL_RAW = """select source, client, date, date_raw, channel, campaign_name, spend, impressions,
                    clicks, conversions, conversion_value
             from raw_ads order by source, client, date, campaign_name"""
ALL_DEALS = """select deal_id, client, created_date, closed_date, stage, deal_value,
                      source_campaign, updated_at
               from raw_deals order by deal_id"""


def by_source(stats):
    return {s.source: s for s in stats}


def count(db, where="true", params=()):
    query = sql.SQL("select count(*) from raw_ads where {}").format(sql.SQL(where))
    return db.execute(query, params).fetchone()[0]


@pytest.fixture(scope="module")
def ds():
    return load_dataset(pd.Timestamp("2025-02-01"), pd.Timestamp("2025-06-30"), pd.Timestamp("2025-04-01"))


@pytest.fixture
def clock():
    return [date(2025, 3, 16)]


@pytest.fixture
def api(ds, clock):
    app = create_app(ds, "k", today=lambda: clock[0], rate_limit_per_min=10_000)
    return AdsApi(TestClient(app), "k", sleep=lambda s: None)


def test_load_clients_reads_the_config():
    clients = load_clients()
    assert clients[SLUG] == NAME
    assert len(clients) == 3


def test_first_ingest_backfills_everything_including_linkedins_first_row(db, api, ds):
    stats = by_source(ingest_client(db, api, SLUG))
    assert stats["google_ads"].since == BACKFILL_FROM
    # LinkedIn's labels run a day behind, so its first row sits before the data window
    assert count(db, "source = 'linkedin_ads' and date = '2025-01-31'") > 0
    for source in ADS_SOURCES:
        expected = ads_rows(ds, source, NAME, BACKFILL_FROM, date(2025, 3, 15))
        distinct = len(expected.drop_duplicates(["date", "campaign_name"]))
        assert count(db, "source = %s", (source,)) == distinct


def test_the_raw_date_keeps_the_platforms_format(db, api):
    ingest_client(db, api, SLUG)
    row = db.execute("""select date, date_raw from raw_ads where source = 'meta_ads'
                        and date = '2025-03-01' limit 1""").fetchone()
    assert row == (date(2025, 3, 1), "01/03/2025")


def test_ingesting_twice_changes_nothing(db, api):
    ingest_client(db, api, SLUG)
    before_ads, before_deals = read_frame(db, ALL_RAW), read_frame(db, ALL_DEALS)
    stats = by_source(ingest_client(db, api, SLUG))
    pd.testing.assert_frame_equal(read_frame(db, ALL_RAW), before_ads)
    pd.testing.assert_frame_equal(read_frame(db, ALL_DEALS), before_deals)
    assert stats["google_ads"].since == date(2025, 3, 15) - timedelta(days=OVERLAP_DAYS)


def test_a_week_later_matches_a_fresh_backfill(db, api, clock):
    ingest_fx(db, api)
    ingest_client(db, api, SLUG)
    clock[0] = date(2025, 3, 23)
    ingest_fx(db, api)
    incremental = by_source(ingest_client(db, api, SLUG))
    assert incremental["google_ads"].rows_received < 100  # days since the watermark, not everything
    ads, deals = read_frame(db, ALL_RAW), read_frame(db, ALL_DEALS)
    fx = read_frame(db, "select date, usd_eur from raw_fx order by date")

    db.execute("truncate raw_ads, raw_deals, raw_fx")
    db.commit()
    ingest_fx(db, api)
    ingest_client(db, api, SLUG)
    pd.testing.assert_frame_equal(read_frame(db, ALL_RAW), ads)
    pd.testing.assert_frame_equal(read_frame(db, ALL_DEALS), deals)
    pd.testing.assert_frame_equal(read_frame(db, "select date, usd_eur from raw_fx order by date"), fx)


def test_duplicates_are_counted_and_written_once(ds, db, clock, api):
    clock[0] = date(2025, 7, 1)  # the whole window, so the generator's overlap is in it
    stats = by_source(ingest_client(db, api, SLUG))["google_ads"]
    assert stats.duplicates_collapsed > 0
    assert stats.rows_written == stats.rows_received - stats.duplicates_collapsed
    assert count(db, "source = 'google_ads'") == stats.rows_written


def test_null_conversion_value_stays_null(db, api, clock):
    clock[0] = date(2025, 7, 1)
    for slug in load_clients():
        ingest_client(db, api, slug)
    assert count(db, "conversion_value is null") > 0


def test_changed_row_inside_the_overlap_is_updated(db, api):
    ingest_client(db, api, SLUG)
    key = db.execute("""select date, campaign_name, spend from raw_ads
                        where source = 'google_ads' order by date desc limit 1""").fetchone()
    db.execute("""update raw_ads set spend = -1
                  where source = 'google_ads' and date = %s and campaign_name = %s""", key[:2])
    db.commit()
    ingest_client(db, api, SLUG)
    spend = db.execute("""select spend from raw_ads
                          where source = 'google_ads' and date = %s and campaign_name = %s""",
                       key[:2]).fetchone()[0]
    assert spend == key[2]


def scripted_api(handler):
    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test")
    return AdsApi(http, "k", sleep=lambda s: None)


def ad_row(day):
    return {"date": day, "client": NAME, "channel": "Google Ads", "campaign_name": "x", "spend": 1.0,
            "impressions": 1, "clicks": 1, "conversions": 0, "conversion_value": 0.0}


def test_failing_on_a_later_page_writes_nothing_for_that_source(db):
    def handler(request):
        if "page_token" in request.url.params:
            return httpx.Response(503)
        return httpx.Response(200, json={"data": [ad_row("2025-03-01")], "next_page_token": "1"})

    with pytest.raises(RetriesExhausted):
        ingest_client(db, scripted_api(handler), SLUG)
    assert count(db) == 0


def test_a_failed_source_leaves_earlier_sources_and_its_watermark_alone(db):
    def handler(request):
        if request.url.path.endswith("google_ads"):
            return httpx.Response(200, json={"data": [ad_row("2025-03-01")], "next_page_token": None})
        return httpx.Response(503)

    with pytest.raises(RetriesExhausted):
        ingest_client(db, scripted_api(handler), SLUG)
    assert count(db, "source = 'google_ads'") == 1
    assert count(db, "source = 'meta_ads'") == 0


def test_deal_that_closes_later_is_updated_on_a_later_run(db, api, clock, ds):
    d = ds.deals
    picks = d[(d["client"] == NAME) & (d["_created"] < "2025-03-10")
              & d["_closed"].between("2025-03-20", "2025-04-05")]
    deal = picks.iloc[0]
    query = "select closed_date, stage from raw_deals where deal_id = %s"

    ingest_client(db, api, SLUG)
    assert db.execute(query, (deal["deal_id"],)).fetchone() == (None, "Qualified")

    clock[0] = date(2025, 4, 10)
    ingest_client(db, api, SLUG)
    assert db.execute(query, (deal["deal_id"],)).fetchone() == (deal["_closed"].date(), deal["stage"])


def test_nothing_new_is_not_an_error(db):
    def handler(request):
        return httpx.Response(200, json={"data": [], "next_page_token": None})

    stats = ingest_client(db, scripted_api(handler), SLUG)
    assert all(s.rows_written == 0 for s in stats)


def test_ingest_fx_is_incremental(db, api, clock):
    first = ingest_fx(db, api)
    assert first.since == BACKFILL_FROM
    assert first.rows_written > 0
    clock[0] = date(2025, 3, 23)
    second = ingest_fx(db, api)
    assert second.since > BACKFILL_FROM
    assert second.rows_written < first.rows_written


def test_a_duplicate_in_the_overlap_is_only_counted_the_first_time(db):
    def handler(request):
        rows = [ad_row("2025-03-01"), ad_row("2025-03-01")] if request.url.path.endswith("google_ads") else []
        return httpx.Response(200, json={"data": rows, "next_page_token": None})

    api = scripted_api(handler)
    first = by_source(ingest_client(db, api, SLUG))["google_ads"]
    second = by_source(ingest_client(db, api, SLUG))["google_ads"]
    assert first.duplicates_collapsed == 1
    assert second.duplicates_collapsed == 0


def test_ingest_cli_rejects_an_unknown_client():
    with pytest.raises(SystemExit):
        ingest_main(["--client", "nope"])
