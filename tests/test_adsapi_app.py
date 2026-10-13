from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from adsapi.app import create_app, create_app_from_env
from adsapi.data import ads_rows, load_dataset

H = {"X-API-Key": "test-key"}
TODAY = date(2025, 3, 16)


@pytest.fixture(scope="module")
def ds():
    return load_dataset(pd.Timestamp("2025-02-01"), pd.Timestamp("2025-06-30"), pd.Timestamp("2025-04-01"))


@pytest.fixture
def client(ds):
    # a fresh app per test, so request counts never carry into the rate limit
    return TestClient(create_app(ds, "test-key", today=lambda: TODAY))


def test_health_needs_no_key(client):
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}])
def test_data_needs_the_key(client, headers):
    r = client.get("/v1/ads/google_ads", params={"client": "solmar-hotels"}, headers=headers)
    assert r.status_code == 401
    assert r.json() == {"detail": "invalid API key"}


def test_pagination_returns_every_row_exactly_once(client, ds):
    rows, token = [], None
    while True:
        params = {"client": "solmar-hotels", "page_size": 50, **({"page_token": token} if token else {})}
        body = client.get("/v1/ads/google_ads", params=params, headers=H).json()
        rows += body["data"]
        token = body["next_page_token"]
        if token is None:
            break
    expected = ads_rows(ds, "google_ads", "Solmar Hotels", date(2025, 2, 1), date(2025, 3, 15))
    assert len(rows) == len(expected)  # duplicates included, nothing lost
    assert pd.DataFrame(rows)[expected.columns].astype(str).equals(expected.astype(str))


def test_until_is_clamped_to_yesterday(client):
    params = {"client": "clinica-vantia", "until": "2030-01-01", "page_size": 1000}
    body = client.get("/v1/ads/organic_search", params=params, headers=H).json()
    assert max(r["date"] for r in body["data"]) == "2025-03-15"


def test_since_after_until_is_400(client):
    params = {"client": "solmar-hotels", "since": "2025-03-10", "until": "2025-03-01"}
    assert client.get("/v1/ads/google_ads", params=params, headers=H).status_code == 400


@pytest.mark.parametrize("token", ["abc", "-5"])
def test_bad_page_token_is_400(client, token):
    params = {"client": "solmar-hotels", "page_token": token}
    assert client.get("/v1/ads/google_ads", params=params, headers=H).status_code == 400


def test_page_token_past_the_end_is_an_empty_last_page(client):
    params = {"client": "solmar-hotels", "page_token": "999999"}
    body = client.get("/v1/ads/google_ads", params=params, headers=H).json()
    assert body == {"data": [], "next_page_token": None}


def test_unknown_client_and_source_are_404(client):
    assert client.get("/v1/ads/google_ads", params={"client": "nope"}, headers=H).status_code == 404
    assert client.get("/v1/ads/tiktok", params={"client": "solmar-hotels"}, headers=H).status_code == 404
    assert client.get("/v1/crm/deals", params={"client": "nope"}, headers=H).status_code == 404


def test_missing_conversion_value_is_null(client):
    # seeded, so this either always or never finds one; scan everything to be sure
    found = False
    for slug in ("solmar-hotels", "nordfit-equipment", "clinica-vantia"):
        for src in ("google_ads", "meta_ads", "linkedin_ads", "organic_search"):
            params = {"client": slug, "page_size": 1000}
            body = client.get(f"/v1/ads/{src}", params=params, headers=H).json()
            found |= any(r["conversion_value"] is None for r in body["data"])
    assert found


def test_rate_limit_returns_429_with_retry_after(ds):
    c = TestClient(create_app(ds, "k", rate_limit_per_min=2, today=lambda: TODAY))
    for _ in range(2):
        c.get("/v1/fx/usd-eur", headers={"X-API-Key": "k"})
    r = c.get("/v1/fx/usd-eur", headers={"X-API-Key": "k"})
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0


def test_deals_include_updated_at_and_null_closed_dates(client):
    body = client.get("/v1/crm/deals", params={"client": "solmar-hotels", "page_size": 1000}, headers=H).json()
    assert body["data"] and "updated_at" in body["data"][0]
    assert any(r["closed_date"] is None for r in body["data"])


def test_fx_rows_stop_at_yesterday(client):
    body = client.get("/v1/fx/usd-eur", params={"page_size": 1000}, headers=H).json()
    assert max(r["date"] for r in body["data"]) <= "2025-03-15"


def test_app_refuses_to_start_without_a_key(monkeypatch):
    monkeypatch.delenv("ADSAPI_KEY", raising=False)
    with pytest.raises(RuntimeError):
        create_app_from_env()
