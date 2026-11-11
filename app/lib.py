"""Shared helpers for the report preview and alert pages.

The pages are thin viewers. Everything here either reads the clean rows the
pipeline wrote or calls into reports/ to build a report exactly the way the
runner does; a page never computes anything the pipeline doesn't.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from control import load_clean_ads
from reports import anomalies
from reports.report import build_report, render_html
from reports.theme import available_themes, load_theme

CONFIDENCE_LEVELS = anomalies.CONFIDENCE_LEVELS
filter_confidence = anomalies.filter_confidence

BASE_DIR = Path(__file__).resolve().parent.parent

# A tiny component that renders the report and reports its own height, so the
# embed has no fixed pixel guess. See app/components/report_frame/index.html.
_report_frame = components.declare_component(
    "report_frame", path=str(BASE_DIR / "app" / "components" / "report_frame")
)


def report_frame(html: str) -> None:
    _report_frame(html=html)

SYNTHETIC_NOTE = (
    "Everything here is synthetic: three fictional clients, generated data, no real "
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


def clients(ads: pd.DataFrame) -> list[str]:
    return sorted(ads["client"].unique())


def theme_names() -> dict[str, str]:
    """Display name -> theme file stem, for a theme picker."""
    return {load_theme(stem).name: stem for stem in available_themes()}


def last_finished_day(today=None) -> pd.Timestamp:
    # LinkedIn's one-day label shift leaves a row on today's date, a day that
    # isn't over, so data is only trusted up to yesterday.
    today = pd.Timestamp(today) if today is not None else pd.Timestamp.now(tz="UTC").tz_localize(None)
    return today.normalize() - pd.Timedelta(days=1)


def available_weeks(ads: pd.DataFrame, client: str, today=None) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Every complete Mon–Sun week the client has data for, newest last."""
    sub = ads.loc[ads["client"] == client, "date"]
    if sub.empty:
        return []
    lo, hi = sub.min(), min(sub.max(), last_finished_day(today))
    monday = lo + pd.Timedelta(days=(7 - lo.weekday()) % 7)
    weeks = []
    while monday + pd.Timedelta(days=6) <= hi:
        weeks.append((monday, monday + pd.Timedelta(days=6)))
        monday += pd.Timedelta(days=7)
    return weeks


def shared_weeks(ads: pd.DataFrame, today=None) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Weeks complete for every client, so none is judged on a partial week."""
    per_client = [set(available_weeks(ads, c, today)) for c in clients(ads)]
    return sorted(set.intersection(*per_client)) if per_client else []


def week_label(start: pd.Timestamp, end: pd.Timestamp) -> str:
    if start.month == end.month:
        return f"{start.day}–{end.day} {end:%b %Y}"
    return f"{start.day} {start:%b} – {end.day} {end:%b %Y}"


@st.cache_data(show_spinner="Building the report…", max_entries=50)
def build_preview(url: str, client: str, week_end: str, theme_stem: str):
    """Returns (html, alerts, period_label) for the week ending `week_end`."""
    ads = load_clean_ads(url)
    theme = load_theme(theme_stem)
    # build_report measures "last-week" back from its anchor, so anchor the day
    # after the week we actually want to see.
    anchor = pd.Timestamp(week_end) + pd.Timedelta(days=1)
    report = build_report(ads, client, anchor, "last-week", theme.accent)
    return render_html(report, theme), report.alerts, report.period_label


@st.cache_data(show_spinner=False, max_entries=200)
def client_alerts(url: str, client: str, week_end: str):
    """All alerts for `client` for the week ending `week_end` (ISO date)."""
    return anomalies.detect_alerts(load_clean_ads(url), client, pd.Timestamp(week_end))


# The Week choice is the one control shared between the Report and Alerts pages.
# It lives under our own session-state key, never bound to a widget, so switching
# client or theme on one page can't perturb the other. session_state is per
# Streamlit session (one browser connection), so nothing leaks between visitors
# or between two open tabs either.
_WEEK_KEY = "shared_week_start"


def remembered_week_start(
    weeks: list[tuple[pd.Timestamp, pd.Timestamp]], fallback: str
) -> str:
    """Week-start ISO to preselect: whatever the other page last looked at, if
    that week exists in `weeks`; otherwise `fallback`."""
    want = st.session_state.get(_WEEK_KEY, fallback)
    starts = {w[0].strftime("%Y-%m-%d") for w in weeks}
    return want if want in starts else fallback


def remember_week_start(week_start: str) -> None:
    st.session_state[_WEEK_KEY] = week_start


def default_selection(ads: pd.DataFrame, today=None) -> tuple[str, str]:
    """(client, week-start ISO) the pages open on: the latest complete week where
    a client spent on paid ads and recorded no conversions at all, the clearest
    thing the pipeline catches (a broken pixel). A cold visitor lands on the week
    with the most to say. Found from the data, since the live window keeps
    moving. Falls back to the newest complete week."""
    last_full = min(ads["date"].max(), last_finished_day(today)) - pd.Timedelta(days=6)
    paid = ads[ads["channel"] != "Organic Search"]
    weekly = (paid.assign(week=paid["date"] - pd.to_timedelta(paid["date"].dt.weekday, unit="D"))
              .groupby(["client", "week"])[["spend", "conversions"]].sum().reset_index())
    dark = weekly[(weekly["spend"] > 0) & (weekly["conversions"] == 0) & (weekly["week"] <= last_full)]
    if not dark.empty:
        pick = dark.sort_values(["week", "client"]).iloc[-1]
        return pick["client"], pick["week"].strftime("%Y-%m-%d")
    client = clients(ads)[0]
    return client, available_weeks(ads, client, today)[-1][0].strftime("%Y-%m-%d")
