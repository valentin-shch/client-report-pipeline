"""Assemble a client report: clean data + metrics -> a Report -> email-safe HTML."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import jinja2
import pandas as pd

from pipeline import metrics
from reports import anomalies, charts, commentary
from reports.theme import Theme

_TEMPLATES = Path(__file__).resolve().parent / "templates"
_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(_TEMPLATES),
    autoescape=jinja2.select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

# Shown first, so the number a client cares about lands above the fold on a
# phone. (label, formatter) keyed by the metric name in pipeline.metrics.
_KPI_SPEC = [
    ("conversion_value", "Revenue", lambda v: f"€{v:,.0f}"),
    ("conversions", "Conversions", lambda v: f"{v:,.0f}"),
    ("roas", "ROAS", lambda v: f"{v:.2f}x"),
    ("spend", "Spend", lambda v: f"€{v:,.0f}"),
    ("cpa", "Cost / conversion", lambda v: "n/a" if pd.isna(v) else f"€{v:,.2f}"),
]

_GOOD, _BAD, _NEUTRAL = "#1a7f4b", "#c0392b", "#5b6470"


@dataclass
class Report:
    client: str
    period: str
    period_label: str
    subtitle: str
    window: tuple[pd.Timestamp, pd.Timestamp]
    prior_window: tuple[pd.Timestamp, pd.Timestamp]
    kpi_rows: list[dict]
    alerts: list[anomalies.Alert]
    what_changed: list[str]
    commentary: str
    charts: list[dict]
    generated_for: str


def slug(client: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", client.lower()).strip("-")


def _day(d: pd.Timestamp) -> str:
    # strftime("%-d") isn't portable to Windows, so format the day by hand.
    return f"{d.day} {d:%b}"


def _period_label(period: str, start: pd.Timestamp, end: pd.Timestamp) -> str:
    if period in ("last-month", "month"):
        return start.strftime("%B %Y")
    if start.month == end.month:
        return f"Week of {start.day}–{end.day} {end:%b %Y}"
    return f"Week of {_day(start)} – {_day(end)} {end.year}"


def _subtitle(period: str) -> str:
    unit = "month" if period in ("last-month", "month") else "week"
    return f"How paid and organic media performed, versus the previous {unit}."


def _kpi_rows(deltas: dict) -> list[dict]:
    rows = []
    for key, label, fmt in _KPI_SPEC:
        d = deltas[key]
        rows.append({
            "label": label,
            "value": fmt(d["current"]),
            **_delta_display(d),
        })
    return rows


def _delta_display(d: dict) -> dict:
    cp = d["change_pct"]
    if pd.isna(cp):
        return {"delta": "", "delta_color": ""}
    pct = cp * 100
    text = "0% vs prev" if round(pct) == 0 else f"{pct:+.0f}% vs prev"
    if d["direction"] == "neutral" or round(pct) == 0:
        return {"delta": text, "delta_color": _NEUTRAL}
    improved = (cp > 0) == (d["direction"] == "higher_better")
    return {"delta": text, "delta_color": _GOOD if improved else _BAD}


def build_report(ads: pd.DataFrame, client: str, anchor, period: str, accent: str) -> Report:
    client_ads = ads[ads["client"] == client]
    (cur_start, cur_end), (pri_start, pri_end) = metrics.period_windows(anchor, period)

    current = metrics.slice_dates(client_ads, cur_start, cur_end)
    prior = metrics.slice_dates(client_ads, pri_start, pri_end)
    comparable = prior["spend"].sum() > 0

    deltas = metrics.kpi_deltas(current, prior)
    cur_channels = metrics.channel_breakdown(current)
    pri_channels = metrics.channel_breakdown(prior)
    movers = metrics.movers(current, prior, "channel", "conversion_value", n=3)
    daily = metrics.daily_series(current)

    chart_list = [
        charts.spend_revenue_by_day(daily, accent),
        charts.spend_by_channel(cur_channels, accent),
    ]
    if comparable and (cur_channels["spend"] > 0).any():
        chart_list.append(charts.roas_by_channel(cur_channels, pri_channels, accent))

    return Report(
        client=client,
        period=period,
        period_label=_period_label(period, cur_start, cur_end),
        subtitle=_subtitle(period),
        window=(cur_start, cur_end),
        prior_window=(pri_start, pri_end),
        kpi_rows=_kpi_rows(deltas),
        alerts=anomalies.detect_alerts(ads, client, cur_end),
        what_changed=commentary.what_changed(
            movers, comparable, deltas["conversion_value"]["current"]
        ),
        commentary=commentary.headline_read(
            deltas, "month" if period in ("last-month", "month") else "week", comparable
        ),
        charts=chart_list,
        generated_for=f"{pd.Timestamp(anchor).day} {pd.Timestamp(anchor):%b %Y}",
    )


def render_html(report: Report, theme: Theme) -> str:
    return _env.get_template("report.html.j2").render(
        client=report.client,
        agency=theme.name,
        accent=theme.accent,
        accent_ink=theme.accent_ink,
        logo=theme.logo_data_uri,
        period_label=report.period_label,
        subtitle=report.subtitle,
        kpis=report.kpi_rows,
        alerts=report.alerts,
        what_changed=report.what_changed,
        commentary=report.commentary,
        threshold_note=commentary.THRESHOLD_NOTE,
        charts=report.charts,
        footer=theme.footer,
        generated_for=report.generated_for,
    )
