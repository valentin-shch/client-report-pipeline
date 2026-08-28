"""Shared helpers for the preview app.

The app is a thin viewer. Everything here either loads the committed parquet or
calls into reports/ to build a report exactly the way `python -m reports.run`
does — the page never computes anything the pipeline doesn't.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from reports import anomalies
from reports.report import build_report, render_html
from reports.theme import available_themes, load_theme

CONFIDENCE_LEVELS = anomalies.CONFIDENCE_LEVELS
filter_confidence = anomalies.filter_confidence

BASE_DIR = Path(__file__).resolve().parent.parent
ADS_PARQUET = BASE_DIR / "data" / "clean" / "ads.parquet"

SYNTHETIC_NOTE = (
    "Everything here is synthetic — three fictional clients, generated data, no real "
    "accounts."
)

# Trims Streamlit's generous top padding and keeps the embedded report from
# forcing a horizontal scroll on a narrow phone.
MOBILE_CSS = """
<style>
  .block-container { padding-top: 2.2rem; padding-bottom: 3rem; }
  iframe { max-width: 100%; }
  @media (max-width: 640px) {
    .block-container { padding-left: 0.9rem; padding-right: 0.9rem; }
    h1 { font-size: 1.6rem; }
  }
</style>
"""


@st.cache_data
def load_ads() -> pd.DataFrame:
    return pd.read_parquet(ADS_PARQUET)


def clients(ads: pd.DataFrame) -> list[str]:
    return sorted(ads["client"].unique())


def theme_names() -> dict[str, str]:
    """Display name -> theme file stem, for a theme picker."""
    return {load_theme(stem).name: stem for stem in available_themes()}


def available_weeks(ads: pd.DataFrame, client: str) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Every complete Mon–Sun week the client has data for, newest last."""
    sub = ads.loc[ads["client"] == client, "date"]
    lo, hi = sub.min(), sub.max()
    monday = lo + pd.Timedelta(days=(7 - lo.weekday()) % 7)
    weeks = []
    while monday + pd.Timedelta(days=6) <= hi:
        weeks.append((monday, monday + pd.Timedelta(days=6)))
        monday += pd.Timedelta(days=7)
    return weeks


def week_label(start: pd.Timestamp, end: pd.Timestamp) -> str:
    if start.month == end.month:
        return f"{start.day}–{end.day} {end:%b %Y}"
    return f"{start.day} {start:%b} – {end.day} {end:%b %Y}"


@st.cache_data(show_spinner="Building the report…")
def build_preview(client: str, week_end: str, theme_stem: str):
    """Returns (html, alerts, period_label, iframe_height) for the week ending `week_end`."""
    ads = load_ads()
    theme = load_theme(theme_stem)
    # build_report measures "last-week" back from its anchor, so anchor the day
    # after the week we actually want to see.
    anchor = pd.Timestamp(week_end) + pd.Timedelta(days=1)
    report = build_report(ads, client, anchor, "last-week", theme.accent)
    return render_html(report, theme), report.alerts, report.period_label, _iframe_height(report)


@st.cache_data(show_spinner=False)
def client_alerts(client: str, week_end: str):
    """All alerts for `client` for the week ending `week_end` (ISO date)."""
    return anomalies.detect_alerts(load_ads(), client, pd.Timestamp(week_end))


def _iframe_height(report) -> int:
    # components.html needs a fixed pixel height and the report can't report its
    # own. Estimate from the parts that vary (measured against the rendered
    # report, ~30–70px of slack); scrolling=True on the embed covers the rest.
    height = 760 + 3 * 335  # shell + KPIs + the three charts
    height += 95 if not report.alerts else 140 * len(report.alerts)
    height += 24 * len(report.what_changed)
    return height
