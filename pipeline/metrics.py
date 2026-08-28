"""Business metric calculations over the clean ads and CRM tables.

Pure functions only: each takes a DataFrame already loaded from data/clean/ and
returns numbers, dicts, or a new DataFrame. No file I/O, so they unit-test
cheaply and are safe to call from a cached Streamlit page or the report
generator.

Three groups of things live here:
  - period KPIs and period-over-period deltas (the report headline)
  - breakdowns and time series (the report charts)
  - robust-z anomaly primitives (the raw signal the alert layer sits on top of)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Whether a delta on this metric has an unambiguous good/bad direction. Spend
# and raw volume move because a client changed budget or the season turned —
# "spend up 40%" is not good or bad on its own, so it stays neutral and gets no
# red/green arrow. Only ratios and outcomes carry a direction.
METRIC_DIRECTION = {
    "spend": "neutral",
    "impressions": "neutral",
    "clicks": "neutral",
    "conversions": "higher_better",
    "conversion_value": "higher_better",
    "roas": "higher_better",
    "cpa": "lower_better",
    "cpc": "lower_better",
    "ctr": "higher_better",
    "cvr": "higher_better",
}

KPI_KEYS = ("spend", "conversions", "conversion_value", "roas", "cpa", "cpc", "ctr", "cvr")


def safe_divide(numerator, denominator):
    if not denominator or pd.isna(denominator):
        return float("nan")
    return numerator / denominator


def pct_change(old, new):
    # NaN when the base is zero or missing: a jump from zero has no meaningful
    # percentage. The report layer handles "started from nothing" separately.
    if not old or pd.isna(old):
        return float("nan")
    return (new - old) / old


def trend_label(change_pct, flat_band=0.02):
    if pd.isna(change_pct):
        return "flat"
    if change_pct > flat_band:
        return "up"
    if change_pct < -flat_band:
        return "down"
    return "flat"


# --- period KPIs -----------------------------------------------------------

def summarize(df: pd.DataFrame) -> dict:
    spend = df["spend"].sum()
    impressions = df["impressions"].sum()
    clicks = df["clicks"].sum()
    conversions = df["conversions"].sum()
    conversion_value = df["conversion_value"].sum()
    # Ratios come off the period totals, never an average of per-row ratios —
    # one low-spend day with a freak ROAS shouldn't weigh the same as the day
    # that actually spent the budget.
    return {
        "spend": spend,
        "impressions": impressions,
        "clicks": clicks,
        "conversions": conversions,
        "conversion_value": conversion_value,
        "roas": safe_divide(conversion_value, spend),
        "cpa": safe_divide(spend, conversions),
        "cpc": safe_divide(spend, clicks),
        "ctr": safe_divide(clicks, impressions),
        "cvr": safe_divide(conversions, clicks),
    }


def kpi_deltas(current_df: pd.DataFrame, prior_df: pd.DataFrame, keys=KPI_KEYS) -> dict:
    cur = summarize(current_df)
    pri = summarize(prior_df)
    return {
        k: {
            "current": cur[k],
            "prior": pri[k],
            "change_pct": pct_change(pri[k], cur[k]),
            "direction": METRIC_DIRECTION.get(k, "neutral"),
        }
        for k in keys
    }


# --- period selection ----------------------------------------------------------

def week_bounds(anchor):
    """Monday–Sunday of the ISO week containing `anchor`."""
    d = pd.Timestamp(anchor).normalize()
    start = d - pd.Timedelta(days=d.weekday())
    return start, start + pd.Timedelta(days=6)


def month_bounds(anchor):
    d = pd.Timestamp(anchor).normalize()
    start = d.replace(day=1)
    return start, start + pd.offsets.MonthEnd(1)


def period_windows(anchor, period: str):
    """((current_start, current_end), (prior_start, prior_end)) for a report run.

    "last-week" is the most recent complete Mon–Sun week before the week holding
    `anchor`; "last-month" is the previous calendar month. The prior window is
    the equivalent span immediately before the current one — a week before a
    week, a calendar month before a month — so the comparison lines up on the
    same weekday / day-of-month structure rather than a rolling 7 or 30 days.
    """
    anchor = pd.Timestamp(anchor).normalize()
    if period in ("last-week", "week"):
        this_week_start, _ = week_bounds(anchor)
        cur_end = this_week_start - pd.Timedelta(days=1)
        cur_start = cur_end - pd.Timedelta(days=6)
        prior_end = cur_start - pd.Timedelta(days=1)
        prior_start = prior_end - pd.Timedelta(days=6)
    elif period in ("last-month", "month"):
        this_month_start, _ = month_bounds(anchor)
        cur_end = this_month_start - pd.Timedelta(days=1)
        cur_start, _ = month_bounds(cur_end)
        prior_end = cur_start - pd.Timedelta(days=1)
        prior_start, _ = month_bounds(prior_end)
    else:
        raise ValueError(f"unknown period: {period!r}")
    return (cur_start, cur_end), (prior_start, prior_end)


def slice_dates(df: pd.DataFrame, start, end, date_col="date") -> pd.DataFrame:
    return df[df[date_col].between(pd.Timestamp(start), pd.Timestamp(end))]


# --- breakdowns and series ---------------------------------------------------

def channel_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("channel", as_index=False).agg(
        spend=("spend", "sum"),
        impressions=("impressions", "sum"),
        clicks=("clicks", "sum"),
        conversions=("conversions", "sum"),
        conversion_value=("conversion_value", "sum"),
    )
    g["roas"] = g.apply(lambda r: safe_divide(r["conversion_value"], r["spend"]), axis=1)
    g["cpa"] = g.apply(lambda r: safe_divide(r["spend"], r["conversions"]), axis=1)
    return g.sort_values("spend", ascending=False).reset_index(drop=True)


def daily_series(df: pd.DataFrame, metrics=("spend", "conversions", "conversion_value"),
                 date_col="date") -> pd.DataFrame:
    return (
        df.groupby(date_col, as_index=False)[list(metrics)].sum()
        .sort_values(date_col)
        .reset_index(drop=True)
    )


def weekly_totals(df: pd.DataFrame, metric="spend", date_col="date") -> pd.Series:
    """Weekly sums of `metric`, one row per Mon–Sun week, labelled by the
    Sunday. Used for the week-over-week anomaly checks."""
    s = df.set_index(date_col)[metric].sort_index()
    return s.resample("W-SUN").sum()


def movers(current_df: pd.DataFrame, prior_df: pd.DataFrame, dimension="channel",
           metric="conversion_value", n=3) -> pd.DataFrame:
    """Largest absolute changes in `metric` between the two periods, grouped by
    `dimension` — the raw material for the report's "what changed" lines.
    Sorted by absolute change, biggest mover first."""
    cur = current_df.groupby(dimension)[metric].sum()
    pri = prior_df.groupby(dimension)[metric].sum()
    joined = pd.DataFrame({"current": cur, "prior": pri}).fillna(0.0)
    joined["change"] = joined["current"] - joined["prior"]
    joined["change_pct"] = joined.apply(
        lambda r: pct_change(r["prior"], r["current"]), axis=1
    )
    order = joined["change"].abs().sort_values(ascending=False).index
    return joined.reindex(order).head(n).reset_index()


# --- anomaly primitives ------------------------------------------------------
# Robust z-score against a rolling baseline. Deliberately not a model — a
# client can be told "this week's spend was 4 times its normal week-to-week
# swing above the recent median" and follow it. The alert layer in reports/
# turns these scores into the plain sentences and the business rules.

def mad(series) -> float:
    """Median absolute deviation."""
    s = pd.Series(series, dtype="float64").dropna()
    if s.empty:
        return float("nan")
    return float((s - s.median()).abs().median())


def robust_z(series) -> pd.Series:
    """Per-point robust z-score: (x - median) / (1.4826 * MAD) over the whole
    series. The 1.4826 rescales MAD to estimate the standard deviation for
    roughly-normal data, so a cutoff near 3.5 keeps its usual "well outside
    normal" reading. All-NaN when MAD is 0 — a flat series gives no scale to
    judge an outlier against.
    """
    s = pd.Series(series, dtype="float64").reset_index(drop=True)
    scale = 1.4826 * mad(s)
    if not scale or pd.isna(scale):
        return pd.Series([float("nan")] * len(s))
    return (s - s.median()) / scale


def _mad_np(window: np.ndarray) -> float:
    return float(np.median(np.abs(window - np.median(window))))


def rolling_anomaly_score(series, window=8) -> pd.Series:
    """Robust z-score of each point against the `window` points before it,
    itself excluded. NaN for the leading points without a full baseline —
    "not enough history" is more honest than flagging against a two-point
    median.
    """
    s = pd.Series(series, dtype="float64").reset_index(drop=True)
    # .shift(1) so each point is scored against the window that ends just before
    # it, not one that includes it.
    baseline_median = s.rolling(window).median().shift(1)
    baseline_scale = 1.4826 * s.rolling(window).apply(_mad_np, raw=True).shift(1)
    scale = baseline_scale.where(baseline_scale > 0)  # 0 or NaN -> no score
    return (s - baseline_median) / scale
