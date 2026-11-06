from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from adsapi.app import create_app
from adsapi.data import ADS_SOURCES, ads_rows, fx_rows, load_dataset
from pipeline import clean
from pipeline.apiclient import AdsApi
from pipeline.clean_db import clean_client_db
from pipeline.db import read_frame
from pipeline.ingest import BACKFILL_FROM, DATE_FORMATS, ingest_client, ingest_fx
from reports.report import build_report, render_html
from reports.store import load_clean_ads, save_report
from reports.theme import load_theme

NAME, SLUG = "Solmar Hotels", "solmar-hotels"
TODAY = date(2025, 3, 19)
YESTERDAY = date(2025, 3, 18)
THEME = "northlight"


class Target:
    name, period, start, end = NAME, "last-week", date(2025, 3, 10), date(2025, 3, 16)


@pytest.fixture(scope="module")
def ds():
    return load_dataset(pd.Timestamp("2025-02-01"), pd.Timestamp("2025-06-30"), pd.Timestamp("2025-04-01"))


@pytest.fixture
def cleaned(db, ds):
    app = create_app(ds, "k", today=lambda: TODAY, rate_limit_per_min=10_000)
    api = AdsApi(TestClient(app), "k", sleep=lambda s: None)
    ingest_fx(db, api)
    ingest_client(db, api, SLUG)
    clean_client_db(db, NAME)
    return db


def built(ads, anchor=TODAY):
    theme = load_theme(THEME)
    report = build_report(ads, NAME, anchor, "last-week", theme.accent)
    return report, render_html(report, theme)


def save(db, html="<p>report</p>", report=None, force=False):
    report = report or built(load_clean_ads(db, NAME))[0]
    return save_report(db, None, Target, report, html, THEME, force=force)


def status(db):
    db.commit()
    return read_frame(db, "select status, html from reports")


def test_a_report_from_the_database_matches_one_from_the_same_rows(cleaned, ds):
    frames = []
    for source in ADS_SOURCES:
        rows = ads_rows(ds, source, NAME, BACKFILL_FROM, YESTERDAY)
        rows["date"] = pd.to_datetime(rows["date"], format=DATE_FORMATS[source])
        frames.append(rows)
    fx = fx_rows(ds, BACKFILL_FROM, YESTERDAY)
    fx["date"] = pd.to_datetime(fx["date"])
    frame, _ = clean.clean_ads(pd.concat(frames, ignore_index=True), fx)
    frame = frame.sort_values(["date", "channel", "campaign_name"]).reset_index(drop=True)

    assert built(load_clean_ads(cleaned, NAME))[1] == built(frame)[1]


def test_a_new_report_is_pending(cleaned):
    assert save(cleaned) == "created"
    assert status(cleaned)["status"].tolist() == ["pending"]


def test_alerts_are_stored_as_json(cleaned):
    report, _ = built(load_clean_ads(cleaned, NAME))
    save(cleaned, report=report)
    stored = cleaned.execute("select alerts, subject from reports").fetchone()
    assert len(stored[0]) == len(report.alerts)
    assert stored[1].startswith(NAME)


def test_a_pending_report_is_replaced(cleaned):
    save(cleaned, html="old")
    assert save(cleaned, html="new") == "replaced"
    assert status(cleaned)["html"].tolist() == ["new"]


@pytest.mark.parametrize("state", ["approved", "sending", "sent", "send_failed"])
def test_a_decided_report_is_left_alone(cleaned, state):
    save(cleaned, html="original")
    cleaned.execute("update reports set status = %s", (state,))
    cleaned.commit()
    assert save(cleaned, html="new") == "kept"
    row = status(cleaned).iloc[0]
    assert (row["status"], row["html"]) == (state, "original")


def test_force_rebuilds_a_sent_report_as_pending(cleaned):
    save(cleaned, html="original")
    cleaned.execute("update reports set status = 'sent', sent_at = now()")
    cleaned.commit()
    assert save(cleaned, html="new", force=True) == "replaced"
    row = status(cleaned).iloc[0]
    assert (row["status"], row["html"]) == ("pending", "new")
    assert cleaned.execute("select sent_at from reports").fetchone() == (None,)


def test_force_never_touches_a_report_mid_send(cleaned):
    # the email is already going out; rebuilding now would leave the row saying
    # a report was sent that nobody received
    save(cleaned, html="original")
    cleaned.execute("update reports set status = 'sending'")
    cleaned.commit()
    assert save(cleaned, html="new", force=True) == "kept"
    row = status(cleaned).iloc[0]
    assert (row["status"], row["html"]) == ("sending", "original")


def test_a_week_and_a_month_starting_the_same_day_are_separate(cleaned):
    save(cleaned)

    class Month(Target):
        period = "last-month"
    report, _ = built(load_clean_ads(cleaned, NAME))
    assert save_report(cleaned, None, Month, report, "m", THEME) == "created"
    assert len(status(cleaned)) == 2


def test_a_hostile_campaign_name_is_escaped_in_the_html(cleaned):
    ads = load_clean_ads(cleaned, NAME)
    ads.loc[ads["channel"] == "Meta Ads", "campaign_theme"] = "<script>alert(1)</script>"
    ads.loc[ads["channel"] == "Meta Ads", "campaign_type"] = "<script>alert(1)</script>"
    ads.loc[ads["channel"] == "Meta Ads", "campaign_name"] = "<script>alert(1)</script>"
    ads.loc[ads["channel"] == "Meta Ads", "channel"] = "<script>alert(1)</script>"
    html = built(ads)[1]
    assert "<script>alert(1)" not in html
