import random
from datetime import date

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from adsapi.app import create_app
from adsapi.data import ads_rows, load_dataset
from pipeline.apiclient import AdsApi, PermanentError, RetriesExhausted


def page(rows, token=None):
    return httpx.Response(200, json={"data": rows, "next_page_token": token})


def scripted(*steps, **kwargs):
    """An AdsApi whose server replays `steps`, each a Response or an exception
    to raise. Returns (api, requests seen, waits slept)."""
    steps, requests, waits = list(steps), [], []

    def handler(request):
        requests.append(request)
        step = steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test")
    kwargs.setdefault("rand", lambda: 0.5)
    return AdsApi(http, "secret", sleep=waits.append, **kwargs), requests, waits


def test_retries_a_429_then_succeeds_honouring_retry_after():
    api, _, waits = scripted(httpx.Response(429, headers={"Retry-After": "3"}), page([{"a": 1}]))
    assert api.get_all("/x", {}) == [{"a": 1}]
    assert waits == [3]
    assert api.retries == 1


def test_backoff_doubles_with_jitter():
    api, _, waits = scripted(httpx.Response(500), httpx.Response(500), page([]))
    api.get_all("/x", {})
    assert waits == [2.0, 4.0]


def test_jitter_spreads_the_wait():
    api, _, waits = scripted(httpx.Response(503), page([]), rand=lambda: 0.0)
    api.get_all("/x", {})
    assert waits == [1.0]


def test_gives_up_after_five_attempts():
    api, requests, waits = scripted(*[httpx.Response(503) for _ in range(5)])
    with pytest.raises(RetriesExhausted, match="/x"):
        api.get_all("/x", {})
    assert len(requests) == 5
    assert len(waits) == 4  # no pointless sleep after the last attempt


def test_401_fails_at_once():
    api, requests, waits = scripted(httpx.Response(401, json={"detail": "invalid API key"}))
    with pytest.raises(PermanentError, match="401"):
        api.get_all("/x", {})
    assert len(requests) == 1
    assert waits == []


def test_404_fails_at_once():
    api, requests, _ = scripted(httpx.Response(404))
    with pytest.raises(PermanentError):
        api.get_all("/x", {})
    assert len(requests) == 1


@pytest.mark.parametrize("error", [httpx.ReadTimeout("slow"), httpx.ConnectError("refused")],
                         ids=["timeout", "connection"])
def test_network_errors_are_transient(error):
    api, _, _ = scripted(error, page([{"a": 1}]))
    assert api.get_all("/x", {}) == [{"a": 1}]
    assert api.retries == 1


def test_network_errors_exhaust_too():
    api, _, _ = scripted(*[httpx.ReadTimeout("slow") for _ in range(5)])
    with pytest.raises(RetriesExhausted):
        api.get_all("/x", {})


def test_follows_pages_to_the_end():
    api, requests, _ = scripted(page([1, 2], "2"), page([3, 4], "4"), page([5]))
    assert api.get_all("/x", {}) == [1, 2, 3, 4, 5]
    assert "page_token" not in requests[0].url.params
    assert requests[1].url.params["page_token"] == "2"
    assert requests[2].url.params["page_token"] == "4"


def test_a_failure_on_a_later_page_retries_that_page():
    api, requests, _ = scripted(page([1], "1"), httpx.Response(500), page([2]))
    assert api.get_all("/x", {}) == [1, 2]
    assert requests[2].url.params["page_token"] == "1"


def test_sends_the_key_and_params():
    api, requests, _ = scripted(page([]))
    api.get_all("/x", {"client": "solmar-hotels", "since": "2025-01-01"})
    assert requests[0].headers["X-API-Key"] == "secret"
    assert requests[0].url.params["client"] == "solmar-hotels"
    assert requests[0].url.params["since"] == "2025-01-01"


def test_from_env_needs_url_and_key(monkeypatch):
    monkeypatch.delenv("ADSAPI_URL", raising=False)
    monkeypatch.setenv("ADSAPI_KEY", "k")
    with pytest.raises(RuntimeError, match="ADSAPI_URL"):
        AdsApi.from_env()


def test_survives_the_fake_apis_injected_faults():
    ds = load_dataset(pd.Timestamp("2025-02-01"), pd.Timestamp("2025-06-30"), pd.Timestamp("2025-04-01"))
    app = create_app(ds, "k", fault_rate=0.3, rng=random.Random(1), today=lambda: date(2025, 3, 16),
                     rate_limit_per_min=10_000)
    api = AdsApi(TestClient(app), "k", sleep=lambda s: None)
    rows = api.get_all("/v1/ads/google_ads", {"client": "solmar-hotels", "page_size": 20})
    assert len(rows) == len(ads_rows(ds, "google_ads", "Solmar Hotels", date(2025, 2, 1), date(2025, 3, 15)))
    assert api.retries > 0
