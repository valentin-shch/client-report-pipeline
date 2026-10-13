"""A stand-in for the ad platforms' reporting APIs.

Run: ADSAPI_KEY=... uvicorn adsapi.app:create_app_from_env --factory
"""

from __future__ import annotations

import hmac
import math
import os
import random
import re
from datetime import date, datetime, timedelta, timezone
from typing import Callable

import pandas as pd
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request

from adsapi.data import (ADS_SOURCES, CLIENTS, DATA_START, Dataset, ads_rows, deals_as_of, fx_rows,
                         load_dataset, load_saved_dataset)
from adsapi.ratelimit import RateLimiter

MAX_PAGE = 1000


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _page(frame: pd.DataFrame, page_size: int, page_token: str | None) -> dict:
    # The token is just the offset of the next row. Opaque enough for a fake,
    # and the data is append-only, so a new day arriving mid-pagination only
    # adds rows at the end.
    offset = 0
    if page_token is not None:
        # ASCII only and bounded: str.isdigit() also accepts "²" and "١", and
        # int() refuses strings past 4300 digits.
        if not re.fullmatch(r"[0-9]{1,12}", page_token):
            raise HTTPException(400, "invalid page_token")
        offset = int(page_token)
    chunk = frame.iloc[offset:offset + page_size]
    end = offset + page_size
    records = chunk.astype(object).where(chunk.notna(), None).to_dict("records")
    return {"data": records, "next_page_token": str(end) if end < len(frame) else None}


def _client_name(slug: str) -> str:
    if slug not in CLIENTS:
        raise HTTPException(404, "unknown client")
    return CLIENTS[slug]


def create_app(
    ds: Dataset,
    api_key: str,
    *,
    fault_rate: float = 0.0,
    rate_limit_per_min: int = 60,
    today: Callable[[], date] = _utc_today,
    rng: random.Random | None = None,
) -> FastAPI:
    limiter = RateLimiter(rate_limit_per_min, 60)
    rng = rng or random.Random()

    def guard(request: Request, x_api_key: str | None = Header(default=None)) -> None:
        if not x_api_key or not hmac.compare_digest(x_api_key.encode(), api_key.encode()):
            raise HTTPException(401, "invalid API key")
        wait = limiter.hit(request.client.host if request.client else "unknown")
        if wait is not None:
            raise HTTPException(429, "rate limit exceeded",
                                headers={"Retry-After": str(max(1, math.ceil(wait)))})
        # Deliberate flakiness so the pipeline's retries do real work. After
        # auth on purpose: a bad key always gets a clean 401, never a fake 5xx.
        if rng.random() < fault_rate:
            status = rng.choice((429, 500, 503))
            headers = {"Retry-After": "2"} if status == 429 else None
            raise HTTPException(status, "injected fault", headers=headers)

    def window(since: date | None, until: date | None) -> tuple[date, date]:
        if since and until and since > until:
            raise HTTPException(400, "since is after until")
        yesterday = today() - timedelta(days=1)
        return since or DATA_START.date(), min(until or yesterday, yesterday)

    app = FastAPI(title="Fake ad platform API",
                  description="Synthetic Google Ads, Meta, LinkedIn, organic and CRM data.")
    v1 = APIRouter(prefix="/v1", dependencies=[Depends(guard)])

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @v1.get("/ads/{source}")
    def ads(source: str, client: str, since: date | None = None, until: date | None = None,
            page_size: int = Query(500, ge=1, le=MAX_PAGE), page_token: str | None = None):
        if source not in ADS_SOURCES:
            raise HTTPException(404, "unknown source")
        name = _client_name(client)
        lo, hi = window(since, until)
        return _page(ads_rows(ds, source, name, lo, hi), page_size, page_token)

    @v1.get("/crm/deals")
    def deals(client: str, updated_since: date | None = None,
              page_size: int = Query(500, ge=1, le=MAX_PAGE), page_token: str | None = None):
        name = _client_name(client)
        yesterday = today() - timedelta(days=1)
        return _page(deals_as_of(ds, name, yesterday, updated_since), page_size, page_token)

    @v1.get("/fx/usd-eur")
    def fx(since: date | None = None, until: date | None = None,
           page_size: int = Query(500, ge=1, le=MAX_PAGE), page_token: str | None = None):
        lo, hi = window(since, until)
        return _page(fx_rows(ds, lo, hi), page_size, page_token)

    app.include_router(v1)
    return app


def create_app_from_env() -> FastAPI:
    key = os.environ.get("ADSAPI_KEY", "").strip()
    if not key:
        raise RuntimeError("ADSAPI_KEY is not set; refusing to start an open API")
    saved = os.environ.get("ADSAPI_DATASET")
    return create_app(
        load_saved_dataset(saved) if saved else load_dataset(),
        key,
        fault_rate=float(os.environ.get("FAULT_RATE", "0")),
        rate_limit_per_min=int(os.environ.get("RATE_LIMIT_PER_MIN", "60")),
    )
