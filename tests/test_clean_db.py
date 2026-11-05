import json
from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from adsapi.app import create_app
from adsapi.data import ADS_SOURCES, ads_rows, deals_as_of, fx_rows, load_dataset
from pipeline import clean, clean_db
from pipeline.apiclient import AdsApi
from pipeline.clean_db import clean_client_db
from pipeline.db import connect, read_frame
from pipeline.ingest import BACKFILL_FROM, DATE_FORMATS, ingest_client, ingest_fx

SOLMAR, NORDFIT = "Solmar Hotels", "Nordfit Equipment"
YESTERDAY = date(2025, 6, 30)
BASE = clean.BASE_DIR / "data" / "clean"


@pytest.fixture(scope="module")
def ds():
    return load_dataset(pd.Timestamp("2025-02-01"), pd.Timestamp("2025-06-30"), pd.Timestamp("2025-04-01"))


@pytest.fixture
def ingested(db, ds):
    app = create_app(ds, "k", today=lambda: date(2025, 7, 1), rate_limit_per_min=10_000)
    api = AdsApi(TestClient(app), "k", sleep=lambda s: None)
    ingest_fx(db, api)
    ingest_client(db, api, "solmar-hotels")
    ingest_client(db, api, "nordfit-equipment")
    return db


def clean_rows(db, client):
    return read_frame(db, "select * from clean_ads where client = %s", (client,))


def test_file_mode_still_matches_the_committed_output(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(clean, "CLEAN_DIR", tmp_path)
    clean.main()
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path / "ads.parquet"),
                                  pd.read_parquet(BASE / "ads.parquet"))
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path / "crm_deals.parquet"),
                                  pd.read_parquet(BASE / "crm_deals.parquet"))
    assert (json.loads((tmp_path / "data_quality_summary.json").read_text())
            == json.loads((BASE / "data_quality_summary.json").read_text()))


def normal(frame):
    """Sorted, with dates as dates, so DB and pandas output compare directly."""
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out[sorted(out.columns)]
    return out.sort_values(["date", "channel", "campaign_name"]).reset_index(drop=True)


def test_db_clean_matches_file_clean_for_the_same_data(ingested, ds):
    # the same rows the API served, through the same steps file mode uses
    frames = []
    for source in ADS_SOURCES:
        rows = ads_rows(ds, source, SOLMAR, BACKFILL_FROM, YESTERDAY)
        rows["date"] = pd.to_datetime(rows["date"], format=DATE_FORMATS[source])
        frames.append(rows)
    fx = fx_rows(ds, BACKFILL_FROM, YESTERDAY)
    fx["date"] = pd.to_datetime(fx["date"])
    expected, _ = clean.clean_ads(pd.concat(frames, ignore_index=True), fx)

    clean_client_db(ingested, SOLMAR)

    got = normal(clean_rows(ingested, SOLMAR))
    pd.testing.assert_frame_equal(got, normal(expected), check_dtype=False)


def test_db_clean_attributes_deals_like_file_clean(ingested, ds):
    clean_client_db(ingested, SOLMAR)
    deals = read_frame(ingested, "select * from clean_deals where client = %s order by deal_id", (SOLMAR,))
    assert len(deals) == len(deals_as_of(ds, SOLMAR, YESTERDAY, None))
    assert set(deals["attribution_status"]) <= {"matched", "unmatched_source", "no_source_recorded"}
    assert (deals["attribution_status"] == "matched").any()
    matched = deals[deals["attribution_status"] == "matched"]
    assert matched["attributed_channel"].notna().all()


def test_linkedin_dates_are_shifted_back_onto_the_real_day(ingested):
    clean_client_db(ingested, SOLMAR)
    first = ingested.execute("""select min(date) from clean_ads
                                where client = %s and channel = 'LinkedIn Ads'""", (SOLMAR,)).fetchone()
    assert first == (date(2025, 2, 1),)


def test_imputed_rows_are_flagged_and_nothing_is_left_blank(ingested):
    clean_client_db(ingested, SOLMAR)
    rows = clean_rows(ingested, SOLMAR)
    assert rows["conversion_value_imputed"].any()
    assert rows["conversion_value"].notna().all()


def test_db_clean_twice_gives_the_same_rows(ingested):
    clean_client_db(ingested, SOLMAR)
    first = normal(clean_rows(ingested, SOLMAR))
    clean_client_db(ingested, SOLMAR)
    pd.testing.assert_frame_equal(normal(clean_rows(ingested, SOLMAR)), first)


def test_failed_clean_leaves_the_previous_rows(ingested, monkeypatch):
    clean_client_db(ingested, SOLMAR)
    before = len(clean_rows(ingested, SOLMAR))

    def boom(*args):
        raise RuntimeError("copy failed")
    monkeypatch.setattr(clean_db, "_copy_rows", boom)

    with pytest.raises(RuntimeError):
        clean_client_db(ingested, SOLMAR)
    assert len(clean_rows(ingested, SOLMAR)) == before


def test_db_clean_only_touches_its_own_client(ingested):
    clean_client_db(ingested, SOLMAR)
    clean_client_db(ingested, NORDFIT)
    solmar = len(clean_rows(ingested, SOLMAR))
    clean_client_db(ingested, NORDFIT)
    assert len(clean_rows(ingested, SOLMAR)) == solmar
    assert len(clean_rows(ingested, NORDFIT)) > 0


def test_summary_reports_what_happened(ingested):
    summary = clean_client_db(ingested, SOLMAR)
    assert summary["rows_out"]["ads_clean"] == len(clean_rows(ingested, SOLMAR))
    assert summary["rows_in"]["raw_ads"] > 0
    assert summary["fx_conversion"]["linkedin_rows_converted"] > 0
    assert summary["conversion_value_imputed"]["rows_imputed"] > 0


def test_a_client_with_nothing_ingested_is_a_clear_error(db):
    with pytest.raises(ValueError, match="no raw rows"):
        clean_client_db(db, SOLMAR)


def committed_rows(pg_url, client):
    # a second connection only sees what was really committed
    with connect(pg_url) as other:
        return other.execute("select count(*) from clean_ads where client = %s", (client,)).fetchone()[0]


def test_clean_is_committed_when_it_returns(ingested, pg_url):
    summary = clean_client_db(ingested, SOLMAR)
    assert committed_rows(pg_url, SOLMAR) == summary["rows_out"]["ads_clean"]


def test_failed_clean_keeps_the_committed_rows(ingested, pg_url, monkeypatch):
    clean_client_db(ingested, SOLMAR)
    before = committed_rows(pg_url, SOLMAR)

    def boom(*args):
        raise RuntimeError("copy failed")
    monkeypatch.setattr(clean_db, "_copy_rows", boom)

    with pytest.raises(RuntimeError):
        clean_client_db(ingested, SOLMAR)
    assert committed_rows(pg_url, SOLMAR) == before


def test_a_later_client_failing_keeps_the_earlier_clients(ingested, pg_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg_url)
    with pytest.raises(ValueError):  # clinica-vantia was never ingested
        clean_db.main(["--client", "all"])
    assert committed_rows(pg_url, SOLMAR) > 0
    assert committed_rows(pg_url, NORDFIT) > 0


def test_no_fx_rates_is_a_clear_error(ingested):
    ingested.execute("truncate raw_fx")
    ingested.commit()
    with pytest.raises(ValueError, match="no FX rates"):
        clean_client_db(ingested, SOLMAR)


def test_summary_says_how_stale_the_fx_rates_are(ingested):
    ingested.execute("delete from raw_fx where date > '2025-06-20'")
    ingested.commit()
    summary = clean_client_db(ingested, SOLMAR)
    assert summary["fx_stale_days"] >= 10


def test_clean_cli_rejects_an_unknown_client():
    with pytest.raises(SystemExit):
        clean_db.main(["--client", "nope"])
