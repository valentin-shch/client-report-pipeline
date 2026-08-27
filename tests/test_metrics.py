import math

import pandas as pd
import pytest

from pipeline import metrics


def test_safe_divide():
    assert metrics.safe_divide(10, 2) == 5
    assert math.isnan(metrics.safe_divide(10, 0))
    assert math.isnan(metrics.safe_divide(10, float("nan")))


def test_pct_change():
    assert metrics.pct_change(100, 150) == pytest.approx(0.5)
    assert metrics.pct_change(100, 80) == pytest.approx(-0.2)
    assert math.isnan(metrics.pct_change(0, 50))


def test_trend_label():
    assert metrics.trend_label(0.5) == "up"
    assert metrics.trend_label(-0.5) == "down"
    assert metrics.trend_label(0.01) == "flat"  # inside the default 2% band
    assert metrics.trend_label(float("nan")) == "flat"


def test_summarize_sums_then_divides():
    df = pd.DataFrame({
        "spend": [100, 200],
        "impressions": [1000, 3000],
        "clicks": [50, 150],
        "conversions": [5, 10],
        "conversion_value": [300, 900],
    })
    result = metrics.summarize(df)
    assert result["spend"] == 300
    assert result["conversion_value"] == 1200
    assert result["roas"] == pytest.approx(4.0)
    assert result["cpa"] == pytest.approx(20.0)
    assert result["ctr"] == pytest.approx(0.05)       # 200 clicks / 4000 impressions
    assert result["cvr"] == pytest.approx(0.075)      # 15 conversions / 200 clicks


def test_summarize_zero_denominator_is_nan_not_error():
    df = pd.DataFrame({
        "spend": [50], "impressions": [100], "clicks": [0],
        "conversions": [0], "conversion_value": [0],
    })
    s = metrics.summarize(df)
    assert math.isnan(s["cpa"])
    assert math.isnan(s["cpc"])
    assert math.isnan(s["cvr"])


def test_kpi_deltas_carries_direction_and_change():
    current = pd.DataFrame({
        "spend": [200], "impressions": [2000], "clicks": [100],
        "conversions": [10], "conversion_value": [600],
    })
    prior = pd.DataFrame({
        "spend": [100], "impressions": [1000], "clicks": [50],
        "conversions": [10], "conversion_value": [400],
    })
    d = metrics.kpi_deltas(current, prior)
    assert d["spend"]["change_pct"] == pytest.approx(1.0)
    assert d["spend"]["direction"] == "neutral"
    assert d["roas"]["current"] == pytest.approx(3.0)
    assert d["roas"]["prior"] == pytest.approx(4.0)
    assert d["roas"]["direction"] == "higher_better"
    assert d["cpa"]["direction"] == "lower_better"


def test_week_bounds_from_a_midweek_date():
    # 2025-06-18 is a Wednesday
    start, end = metrics.week_bounds("2025-06-18")
    assert start == pd.Timestamp("2025-06-16")  # Monday
    assert end == pd.Timestamp("2025-06-22")    # Sunday


def test_month_bounds():
    start, end = metrics.month_bounds("2025-02-14")
    assert start == pd.Timestamp("2025-02-01")
    assert end == pd.Timestamp("2025-02-28")


def test_period_windows_last_week():
    (cs, ce), (ps, pe) = metrics.period_windows("2025-06-18", "last-week")
    assert (cs, ce) == (pd.Timestamp("2025-06-09"), pd.Timestamp("2025-06-15"))
    assert (ps, pe) == (pd.Timestamp("2025-06-02"), pd.Timestamp("2025-06-08"))


def test_period_windows_last_month():
    (cs, ce), (ps, pe) = metrics.period_windows("2025-06-18", "last-month")
    assert (cs, ce) == (pd.Timestamp("2025-05-01"), pd.Timestamp("2025-05-31"))
    assert (ps, pe) == (pd.Timestamp("2025-04-01"), pd.Timestamp("2025-04-30"))


def test_period_windows_rejects_unknown():
    with pytest.raises(ValueError):
        metrics.period_windows("2025-06-18", "last-quarter")


def test_slice_dates_is_inclusive():
    df = pd.DataFrame({"date": pd.to_datetime(
        ["2025-06-01", "2025-06-05", "2025-06-10", "2025-06-15"]
    ), "spend": [1, 2, 3, 4]})
    out = metrics.slice_dates(df, "2025-06-05", "2025-06-10")
    assert list(out["spend"]) == [2, 3]


def _ads(rows):
    cols = ["date", "channel", "spend", "impressions", "clicks",
            "conversions", "conversion_value"]
    df = pd.DataFrame(rows, columns=cols)
    df["date"] = pd.to_datetime(df["date"])
    return df


def test_channel_breakdown_ratios_and_order():
    df = _ads([
        ["2025-06-01", "Google Ads", 100, 1000, 50, 5, 400],
        ["2025-06-02", "Google Ads", 100, 1000, 50, 5, 400],
        ["2025-06-01", "Meta Ads", 50, 2000, 40, 2, 100],
    ])
    out = metrics.channel_breakdown(df)
    assert list(out["channel"]) == ["Google Ads", "Meta Ads"]  # by spend desc
    google = out[out["channel"] == "Google Ads"].iloc[0]
    assert google["spend"] == 200
    assert google["roas"] == pytest.approx(4.0)
    assert google["cpa"] == pytest.approx(20.0)


def test_daily_series_sums_per_day_sorted():
    df = _ads([
        ["2025-06-02", "Google Ads", 10, 0, 0, 1, 30],
        ["2025-06-01", "Google Ads", 20, 0, 0, 2, 60],
        ["2025-06-02", "Meta Ads", 5, 0, 0, 0, 0],
    ])
    out = metrics.daily_series(df)
    assert list(out["date"]) == [pd.Timestamp("2025-06-01"), pd.Timestamp("2025-06-02")]
    assert list(out["spend"]) == [20, 15]


def test_weekly_totals_buckets_mon_to_sun():
    dates = pd.date_range("2025-06-09", "2025-06-22", freq="D")  # two full weeks
    df = pd.DataFrame({"date": dates, "spend": [10] * 14})
    weekly = metrics.weekly_totals(df, "spend")
    assert list(weekly.values) == [70, 70]
    assert list(weekly.index) == [pd.Timestamp("2025-06-15"), pd.Timestamp("2025-06-22")]


def test_movers_sorted_by_absolute_change():
    current = pd.DataFrame({
        "channel": ["Google Ads", "Meta Ads", "LinkedIn Ads"],
        "conversion_value": [1000, 100, 500],
    })
    prior = pd.DataFrame({
        "channel": ["Google Ads", "Meta Ads", "LinkedIn Ads"],
        "conversion_value": [400, 300, 480],
    })
    out = metrics.movers(current, prior, n=2)
    assert list(out["channel"]) == ["Google Ads", "Meta Ads"]
    assert out.iloc[0]["change"] == pytest.approx(600)
    assert out.iloc[1]["change"] == pytest.approx(-200)


def test_mad():
    assert metrics.mad([1, 1, 1]) == 0.0
    assert metrics.mad([1, 2, 3, 4, 5]) == 1.0
    assert math.isnan(metrics.mad([]))


def test_robust_z_flags_outlier_and_handles_flat_series():
    z = metrics.robust_z([10, 12, 9, 11, 8, 13, 40])
    assert z.iloc[-1] > 5           # the 40 is far outside the spread
    assert abs(z.iloc[0]) < 1       # a normal week sits near the median

    flat = metrics.robust_z([5, 5, 5, 5])
    assert flat.isna().all()        # no scale, no score


def test_rolling_anomaly_score_leading_nans_then_spike():
    normal = [10, 11, 9, 10, 12, 8, 10, 11]
    series = normal + [45]  # week 9 spikes
    scores = metrics.rolling_anomaly_score(series, window=8)
    assert scores.iloc[:8].isna().all()
    assert scores.iloc[8] > 5
