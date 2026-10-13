"""The fake platforms' data: one fixed, seeded dataset, served as of yesterday.

The generator draws its random numbers in one long sequence, so regenerating
"up to yesterday" every day would rewrite all of history. Instead the whole
span is generated once and requests only ever see the part that has happened.
"""

from __future__ import annotations

import pickle
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from data.generate import DATE_FORMATS, generate

DATA_START = pd.Timestamp("2025-02-01")
DATA_END = pd.Timestamp("2028-12-31")
# Same pixel-outage week as the committed samples (w/c 2026-04-06).
BREAK_REF = pd.Timestamp("2026-04-12")

ADS_SOURCES = ("google_ads", "meta_ads", "linkedin_ads", "organic_search")
_SOURCE_CHANNEL = {
    "google_ads": "Google Ads",
    "meta_ads": "Meta Ads",
    "linkedin_ads": "LinkedIn Ads",
    "organic_search": "Organic Search",
}

CLIENTS = {
    "solmar-hotels": "Solmar Hotels",
    "nordfit-equipment": "Nordfit Equipment",
    "clinica-vantia": "Clinica Vantia",
}


@dataclass(frozen=True)
class Dataset:
    ads: dict[str, pd.DataFrame]
    deals: pd.DataFrame
    fx: pd.DataFrame


def load_dataset(start=DATA_START, end=DATA_END, break_ref=BREAK_REF) -> Dataset:
    raw = generate(start, end, break_ref)
    ads = {}
    for source in ADS_SOURCES:
        frame = raw[source].copy()
        fmt = DATE_FORMATS[_SOURCE_CHANNEL[source]]
        frame["_date"] = pd.to_datetime(frame["date"], format=fmt)
        ads[source] = frame
    deals = raw["crm_deals"].copy()
    deals["_created"] = pd.to_datetime(deals["created_date"])
    deals["_closed"] = pd.to_datetime(deals["closed_date"])
    fx = raw["fx_rates"].copy()
    fx["_date"] = pd.to_datetime(fx["date"])
    return Dataset(ads=ads, deals=deals, fx=fx)


def save_dataset(ds: Dataset, path: Path) -> None:
    # Plain frames, not the Dataset itself: run as a script this module is
    # __main__, and a pickled __main__.Dataset wouldn't load in the app.
    Path(path).write_bytes(pickle.dumps({"ads": ds.ads, "deals": ds.deals, "fx": ds.fx}))


def load_saved_dataset(path: Path) -> Dataset:
    # Only ever a file this project's own image build wrote (see the
    # Dockerfile), never anything uploaded, so unpickling it is safe.
    return Dataset(**pickle.loads(Path(path).read_bytes()))


def _hidden(frame: pd.DataFrame) -> list[str]:
    return [c for c in frame.columns if c.startswith("_")]


def ads_rows(ds: Dataset, source: str, client_name: str, since: date, until: date) -> pd.DataFrame:
    frame = ds.ads[source]
    hit = (frame["client"] == client_name) & frame["_date"].between(pd.Timestamp(since), pd.Timestamp(until))
    # stable sort: re-exported duplicate rows stay in their original order
    out = frame[hit].sort_values(["_date", "campaign_name"], kind="stable")
    return out.drop(columns=_hidden(out)).reset_index(drop=True)


def deals_as_of(ds: Dataset, client_name: str, yesterday: date, updated_since: date | None) -> pd.DataFrame:
    """A deal that closes after `yesterday` hasn't closed yet, so it shows as
    still open; otherwise the API would leak the future."""
    y = pd.Timestamp(yesterday)
    d = ds.deals[(ds.deals["client"] == client_name) & (ds.deals["_created"] <= y)].copy()
    later = d["_closed"] > y
    d.loc[later, "closed_date"] = None
    d.loc[later, "stage"] = "Qualified"
    d["updated_at"] = d["closed_date"].fillna(d["created_date"])
    if updated_since is not None:
        d = d[pd.to_datetime(d["updated_at"]) >= pd.Timestamp(updated_since)]
    d = d.sort_values(["_created", "deal_id"], kind="stable")
    return d.drop(columns=_hidden(d)).reset_index(drop=True)


def fx_rows(ds: Dataset, since: date, until: date) -> pd.DataFrame:
    frame = ds.fx
    out = frame[frame["_date"].between(pd.Timestamp(since), pd.Timestamp(until))]
    return out.drop(columns=_hidden(out)).reset_index(drop=True)


if __name__ == "__main__":
    # Run at image build: generating takes seconds locally but much longer on
    # a small cloud CPU, and it would otherwise happen on every cold start.
    save_dataset(load_dataset(), Path(sys.argv[1]))
