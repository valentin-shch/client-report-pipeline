import os
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import streamlit as st
from fastapi.testclient import TestClient
from psycopg import sql
from streamlit.testing.v1 import AppTest

from adsapi.app import create_app
from adsapi.data import load_dataset
from pipeline.apiclient import AdsApi
from pipeline.clean_db import clean_client_db
from pipeline.db import TABLES, connect
from pipeline.ingest import ingest_client, ingest_fx

ENTRY = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")


@pytest.fixture(scope="module")
def seeded(pg_url):
    """Two clients pulled and cleaned the real way. The generator's pixel outage
    sits in Solmar's week of 31 March 2025."""
    url = os.environ.get("TEST_APP_DATABASE_URL")
    if not url:
        pytest.skip("TEST_APP_DATABASE_URL is not set")
    ds = load_dataset(pd.Timestamp("2025-02-01"), pd.Timestamp("2025-06-30"), pd.Timestamp("2025-04-01"))
    api = AdsApi(TestClient(create_app(ds, "k", today=lambda: date(2025, 7, 1), rate_limit_per_min=10_000)),
                 "k", sleep=lambda s: None)
    with connect(pg_url) as conn:
        conn.execute(sql.SQL("truncate {}").format(sql.SQL(", ").join(sql.Identifier(t) for t in TABLES)))
        conn.commit()
        ingest_fx(conn, api)
        for slug, name in (("solmar-hotels", "Solmar Hotels"), ("nordfit-equipment", "Nordfit Equipment")):
            ingest_client(conn, api, slug)
            clean_client_db(conn, name)
    return url


@pytest.fixture
def app_url(seeded, monkeypatch):
    st.cache_data.clear()
    monkeypatch.setenv("APP_DATABASE_URL", seeded)
    return seeded


def open_page(page):
    at = AppTest.from_file(ENTRY, default_timeout=90)
    at.switch_page(page)
    return at.run()


def shown(at):
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption] + [s.value for s in at.subheader]
    for kind in (at.info, at.warning, at.error):
        parts += [e.value for e in kind]
    return "\n".join(parts)


def test_preview_opens_on_the_week_the_pipeline_flagged(app_url):
    at = open_page("app_pages/report_preview.py")
    assert not at.exception
    assert at.selectbox(key="client").value == "Solmar Hotels"
    assert "31 Mar – 6 Apr 2025" in shown(at)
    assert "alert(s) flagged" in shown(at)
    assert at.get("download_button")


def test_preview_switches_client_and_theme(app_url):
    at = open_page("app_pages/report_preview.py")
    at.selectbox(key="client").select("Nordfit Equipment").run()
    assert not at.exception
    assert "Nordfit Equipment, week of" in shown(at)


def test_preview_mentions_the_runner_not_the_old_command(app_url):
    text = shown(open_page("app_pages/report_preview.py"))
    assert "python -m runner" in text
    assert "reports.run" not in text


def test_alerts_open_on_the_same_week_and_cover_every_client_with_data(app_url):
    at = open_page("app_pages/alerts.py")
    assert not at.exception
    text = shown(at)
    assert "of 2 clients flagged" in text
    assert "31 Mar – 6 Apr 2025" in text
    assert {"Solmar Hotels", "Nordfit Equipment"} <= {s.value for s in at.subheader}


@pytest.mark.parametrize("page", ["app_pages/report_preview.py", "app_pages/alerts.py"])
def test_an_unreachable_database_is_explained(monkeypatch, page):
    st.cache_data.clear()
    monkeypatch.setenv("APP_DATABASE_URL", "postgresql://app:x@127.0.0.1:1/crp_test?connect_timeout=2")
    at = open_page(page)
    assert not at.exception
    assert "waking up" in shown(at)


def test_flagged_clients_come_first(app_url):
    # on a phone the clients with something to say should land above the fold
    at = open_page("app_pages/alerts.py")
    assert [s.value for s in at.subheader][0] == "Solmar Hotels"


def layout_css(at):
    return "\n".join(m.value for m in at.markdown if "st-key-layout" in m.value)


def test_the_layout_switch_starts_unset_so_the_screen_decides(app_url):
    at = open_page("app_pages/report_preview.py")
    switch = at.segmented_control(key="layout")
    assert switch.options == ["Desktop", "Phone"]
    assert switch.value is None


def test_until_someone_chooses_the_button_matching_the_screen_looks_selected(app_url):
    css = layout_css(open_page("app_pages/report_preview.py"))
    # narrow screens light up Phone (second), wide ones Desktop (first)
    assert "max-width: 699px" in css and "nth-of-type(2)" in css
    assert "min-width: 700px" in css and "nth-of-type(1)" in css


def test_a_real_choice_drops_the_painted_highlight(app_url):
    at = open_page("app_pages/report_preview.py")
    at.segmented_control(key="layout").set_value("Phone").run()
    assert not at.exception
    assert layout_css(at) == ""
