from datetime import date

import pandas as pd
import pytest

from adsapi.data import ads_rows, deals_as_of, load_dataset


@pytest.fixture(scope="module")
def ds():
    return load_dataset(pd.Timestamp("2025-02-01"), pd.Timestamp("2025-06-30"), pd.Timestamp("2025-04-01"))


def test_ads_rows_hide_everything_after_until(ds):
    rows = ads_rows(ds, "google_ads", "Solmar Hotels", date(2025, 3, 1), date(2025, 3, 7))
    assert set(rows["date"]) == {f"2025-03-0{d}" for d in range(1, 8)}
    assert "_date" not in rows.columns


def test_meta_rows_keep_platform_date_format(ds):
    rows = ads_rows(ds, "meta_ads", "Clinica Vantia", date(2025, 3, 1), date(2025, 3, 1))
    assert set(rows["date"]) == {"01/03/2025"}


def test_ads_rows_keep_duplicates(ds):
    rows = ads_rows(ds, "google_ads", "Solmar Hotels", date(2025, 2, 1), date(2025, 6, 30))
    assert rows.duplicated().any()


def test_deal_closing_after_yesterday_looks_open(ds):
    yesterday = date(2025, 3, 15)
    out = deals_as_of(ds, "Solmar Hotels", yesterday, None)
    closes_later = pd.to_datetime(ds.deals["closed_date"]) > pd.Timestamp(yesterday)
    ids = set(ds.deals.loc[closes_later & (ds.deals["client"] == "Solmar Hotels"), "deal_id"])
    hidden = out[out["deal_id"].isin(ids)]
    assert len(hidden)
    assert hidden["closed_date"].isna().all()
    assert set(hidden["stage"]) <= {"New", "Qualified"}


def test_deals_never_include_deals_created_after_yesterday(ds):
    out = deals_as_of(ds, "Solmar Hotels", date(2025, 3, 15), None)
    assert (pd.to_datetime(out["created_date"]) <= "2025-03-15").all()


def test_updated_since_returns_only_recent_changes(ds):
    out = deals_as_of(ds, "Solmar Hotels", date(2025, 4, 30), updated_since=date(2025, 4, 20))
    assert len(out)
    assert (pd.to_datetime(out["updated_at"]) >= "2025-04-20").all()
