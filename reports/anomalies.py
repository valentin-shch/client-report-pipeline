"""Anomaly alerts — the "spot it before the client does" layer.

Deliberately simple and inspectable: week-over-week percentage moves, plus a
robust z-score (median and MAD) against the recent weekly history. No trained
model, nothing that can't be explained in the sentence attached to each alert.

Alerts are always evaluated week-over-week, even for a monthly report — a month
is too coarse to notice a campaign that stopped delivering on the 3rd.

The bias is on purpose: this over-flags. A false positive costs someone two
minutes checking a chart; a missed drop costs a client. Every alert carries a
magnitude and a confidence so the reader can triage:

    high    — a large move, or well outside the normal range
    medium  — just past the threshold
    low     — barely enough history to judge

Thresholds are the constants below; each one has a note on why it's set where
it is.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from pipeline import metrics

# A +30% week-on-week spend move is a real budget change, not weekly noise.
SPEND_SURGE = 0.30
# Under +5% more conversions alongside that spend counts as "no lift".
CONVERSION_FLAT = 0.05
# A quarter of the conversions gone in a week is worth a call.
CONVERSION_SLUMP = -0.25
# ...as long as spend didn't also move — under 15% either way is "held steady".
SPEND_STEADY = 0.15
# Robust z on weekly CPC. ~3.5 MADs is well clear of ordinary auction wobble.
CPC_Z = 3.5
CPC_MIN_HISTORY = 5      # weeks of CPC before its "normal band" means anything
# Below ~100 clicks a week, weekly CPC swings on a handful of clicks and there's
# no stable band to compare against — skip the check rather than cry wolf. In
# this data that excludes LinkedIn, which runs 15–30 clicks a week.
CPC_MIN_CLICKS = 100
# Google CPC is stable enough that a 3-cent move can score a huge z. Also
# require the move to be at least 8% in plain terms before it's worth a line.
CPC_MIN_REL_MOVE = 0.08
DELIVERY_LOOKBACK = 4    # weeks of history for the "stopped delivering" check
DELIVERY_MIN_ACTIVE = 3  # active in at least this many of those weeks

PAID_CHANNELS = ("Google Ads", "Meta Ads", "LinkedIn Ads")
CONFIDENCE_LEVELS = ("low", "medium", "high")
_RANK = {level: i for i, level in enumerate(CONFIDENCE_LEVELS)}


@dataclass(frozen=True)
class Alert:
    scope: str        # "Account", "Google Ads", "Retargeting Social · Meta Ads"
    headline: str
    detail: str       # the full plain-language sentence
    magnitude: str    # the numbers, compactly
    confidence: str    # one of CONFIDENCE_LEVELS
    severity: int      # for ordering only


def detect_alerts(ads: pd.DataFrame, client: str, anchor) -> list[Alert]:
    client_ads = ads[ads["client"] == client]
    ref_start, ref_end = _reference_week(anchor)

    weekly = _weekly_totals(client_ads, ref_end)
    if len(weekly) < 2 or weekly.index[-1] < ref_start:
        return []  # not enough history, or the data doesn't reach this week

    current, prior = weekly.iloc[-1], weekly.iloc[-2]
    alerts: list[Alert] = []
    alerts += _spend_without_conversions(current, prior)
    alerts += _conversions_without_spend_change(current, prior)
    alerts += _cpc_out_of_band(client_ads, ref_end)
    alerts += _stopped_delivering(client_ads, ref_start, ref_end)

    return sorted(alerts, key=lambda a: (a.severity, _RANK[a.confidence]), reverse=True)


def filter_confidence(alerts: list[Alert], minimum: str) -> list[Alert]:
    floor = _RANK[minimum]
    return [a for a in alerts if _RANK[a.confidence] >= floor]


# --- helpers ---------------------------------------------------------------

def _reference_week(anchor) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Most recent complete Mon–Sun week ending on or before `anchor`."""
    d = pd.Timestamp(anchor).normalize()
    sunday = d - pd.Timedelta(days=(d.weekday() + 1) % 7)
    return sunday - pd.Timedelta(days=6), sunday


def _weekly_totals(client_ads: pd.DataFrame, ref_end: pd.Timestamp) -> pd.DataFrame:
    scoped = client_ads[client_ads["date"] <= ref_end]
    return scoped.groupby(pd.Grouper(key="date", freq="W-SUN")).agg(
        spend=("spend", "sum"),
        clicks=("clicks", "sum"),
        impressions=("impressions", "sum"),
        conversions=("conversions", "sum"),
        conversion_value=("conversion_value", "sum"),
    )


def _pct(old, new) -> float:
    return metrics.pct_change(old, new)


def _signed_pct(x: float) -> str:
    return "0%" if round(x * 100) == 0 else f"{x * 100:+.0f}%"


def _mag(x: float) -> str:
    """Bare magnitude for prose that already carries the direction word."""
    return f"{abs(x) * 100:.0f}%"


# --- detectors -----------------------------------------------------------------

def _spend_without_conversions(current, prior) -> list[Alert]:
    spend_wow = _pct(prior["spend"], current["spend"])
    conv_wow = _pct(prior["conversions"], current["conversions"])
    if pd.isna(spend_wow) or spend_wow <= SPEND_SURGE:
        return []
    if pd.isna(conv_wow) or conv_wow >= CONVERSION_FLAT:
        return []

    confidence = "high" if spend_wow >= 0.6 or conv_wow < 0 else "medium"
    conv_clause = (
        f"conversions fell {_mag(conv_wow)} to {current['conversions']:,.0f}"
        if conv_wow < 0 else
        f"conversions barely moved ({current['conversions']:,.0f})"
    )
    detail = (
        f"Spend rose {_mag(spend_wow)} week-over-week to €{current['spend']:,.0f}, but "
        f"{conv_clause}. More spend usually brings more conversions — worth checking "
        f"targeting, landing pages, or whether conversion tracking has broken."
    )
    return [Alert(
        scope="Account",
        headline="Spend up sharply, conversions flat",
        detail=detail,
        magnitude=f"spend {_signed_pct(spend_wow)}, conversions {_signed_pct(conv_wow)}",
        confidence=confidence,
        severity=2,
    )]


def _conversions_without_spend_change(current, prior) -> list[Alert]:
    conv_wow = _pct(prior["conversions"], current["conversions"])
    spend_wow = _pct(prior["spend"], current["spend"])
    if pd.isna(conv_wow) or conv_wow >= CONVERSION_SLUMP:
        return []
    if pd.isna(spend_wow) or abs(spend_wow) >= SPEND_STEADY:
        return []

    confidence = "high" if conv_wow <= -0.4 else "medium"
    spend_note = "" if round(spend_wow * 100) == 0 else f" ({_signed_pct(spend_wow)})"
    detail = (
        f"Conversions fell {_mag(conv_wow)} week-over-week to {current['conversions']:,.0f} "
        f"while spend held roughly steady{spend_note}. The budget went out but brought back "
        f"less — check for a tracking gap, a landing-page problem, or a drop in lead quality."
    )
    return [Alert(
        scope="Account",
        headline="Conversions dropped, spend held",
        detail=detail,
        magnitude=f"conversions {_signed_pct(conv_wow)}, spend {_signed_pct(spend_wow)}",
        confidence=confidence,
        severity=3,
    )]


def _cpc_out_of_band(client_ads: pd.DataFrame, ref_end: pd.Timestamp) -> list[Alert]:
    alerts = []
    for channel in PAID_CHANNELS:
        chan = client_ads[(client_ads["channel"] == channel) & (client_ads["date"] <= ref_end)]
        if chan.empty:
            continue
        weekly = chan.groupby(pd.Grouper(key="date", freq="W-SUN")).agg(
            spend=("spend", "sum"), clicks=("clicks", "sum")
        )
        cpc = (weekly["spend"] / weekly["clicks"].replace(0, np.nan))
        if len(cpc) < CPC_MIN_HISTORY + 1:
            continue

        current_cpc = cpc.iloc[-1]
        baseline_weeks = weekly.iloc[-(CPC_MIN_HISTORY + 4):-1]
        baseline = (baseline_weeks["spend"] / baseline_weeks["clicks"].replace(0, np.nan)).dropna()
        if pd.isna(current_cpc) or len(baseline) < CPC_MIN_HISTORY:
            continue
        if weekly["clicks"].iloc[-1] < CPC_MIN_CLICKS or baseline_weeks["clicks"].median() < CPC_MIN_CLICKS:
            continue

        scale = 1.4826 * metrics.mad(baseline)
        if not scale:
            continue
        typical = baseline.median()
        z = (current_cpc - typical) / scale
        if abs(z) < CPC_Z or abs(current_cpc / typical - 1) < CPC_MIN_REL_MOVE:
            continue

        moved = "jumped" if z > 0 else "dropped"
        direction = ("Auction pressure or a bid change" if z > 0
                     else "A bid cut, or a shift toward cheaper placements")
        confidence = "high" if abs(z) >= 5 else "medium"
        detail = (
            f"{channel} CPC {moved} to €{current_cpc:.2f} this week, well {'above' if z > 0 else 'below'} "
            f"its recent norm of about €{typical:.2f} (robust z {z:+.1f}). {direction} — "
            f"confirm it's intended."
        )
        alerts.append(Alert(
            scope=channel,
            headline=f"{channel} CPC outside its normal range",
            detail=detail,
            magnitude=f"€{current_cpc:.2f} vs €{typical:.2f} typical (z {z:+.1f})",
            confidence=confidence,
            severity=2,
        ))
    return alerts


def _stopped_delivering(client_ads: pd.DataFrame, ref_start, ref_end) -> list[Alert]:
    lookback_start = ref_start - pd.Timedelta(weeks=DELIVERY_LOOKBACK)
    recent = client_ads[
        (client_ads["date"] >= lookback_start)
        & (client_ads["date"] <= ref_end)
        & (client_ads["channel"] != "Organic Search")
    ].copy()
    if recent.empty:
        return []

    recent["week"] = recent["date"].dt.to_period("W-SUN").dt.start_time
    recent["ckey"] = [_campaign_key(r) for r in recent.itertuples(index=False)]
    weekly = recent.groupby(["ckey", "week"]).agg(
        spend=("spend", "sum"), impressions=("impressions", "sum")
    )

    # TODO: this can't tell a planned seasonal end (a Black Friday campaign
    # finishing on schedule) from an unplanned stop — there's no campaign
    # calendar to check against. For now it flags both and the sentence asks
    # the reader to confirm it was intended.
    prior_weeks = [ref_start - pd.Timedelta(weeks=k) for k in range(1, DELIVERY_LOOKBACK + 1)]
    last_week = prior_weeks[0]
    alerts = []
    for ckey, g in weekly.groupby(level="ckey"):
        g = g.droplevel("ckey")
        active_prior = sum(1 for w in prior_weeks if _delivered(g, w))
        # Flag only the week it actually goes dark: established campaign, running
        # right up to last week, nothing this week. Without the last-week check
        # it would re-flag every week the campaign stays off.
        if active_prior < DELIVERY_MIN_ACTIVE or not _delivered(g, last_week):
            continue
        if _delivered(g, ref_start):
            continue

        avg = g.loc[[w for w in prior_weeks if w in g.index], "spend"].mean()
        confidence = "high" if active_prior == DELIVERY_LOOKBACK else "medium"
        detail = (
            f"The {ckey} campaign spent nothing this week after averaging €{avg:,.0f}/week "
            f"over the previous month. It may have been paused, hit a budget cap, or had its "
            f"ads rejected — worth confirming it was meant to stop."
        )
        alerts.append(Alert(
            scope=ckey,
            headline="A campaign stopped delivering",
            detail=detail,
            magnitude=f"was €{avg:,.0f}/wk, now €0",
            confidence=confidence,
            severity=3,
        ))
    return alerts


def _delivered(g: pd.DataFrame, week: pd.Timestamp) -> bool:
    if week not in g.index:
        return False
    row = g.loc[week]
    return bool(row["spend"] > 0 or row["impressions"] > 0)


def _campaign_key(row) -> str:
    # Group by the campaign's identity minus its quarter label, so the routine
    # Q1 -> Q2 rename doesn't read as a campaign stopping and a new one starting.
    if row.campaign_convention in ("unknown", "organic") or pd.isna(row.campaign_theme):
        return row.campaign_name
    return f"{row.campaign_theme} {row.campaign_type} · {row.channel}"
