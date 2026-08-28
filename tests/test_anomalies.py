import pandas as pd
import pytest

from reports import anomalies
from reports.anomalies import Alert


def _weeks(specs, *, client="X", channel="Google Ads", campaign="Brand Search ES Q1",
           convention="A", theme="Brand", ctype="Search", country="ES", start="2026-01-07"):
    """One row per week (on a Wednesday), from a list of per-week dicts."""
    base = pd.Timestamp(start)
    rows = []
    for i, s in enumerate(specs):
        clicks = s.get("clicks", 0)
        rows.append({
            "date": base + pd.Timedelta(weeks=i),
            "client": client,
            "channel": channel,
            "campaign_name": campaign,
            "spend": float(s.get("spend", 0.0)),
            "impressions": int(s.get("impressions", clicks * 20)),
            "clicks": int(clicks),
            "conversions": int(s.get("conversions", 0)),
            "conversion_value": float(s.get("value", s.get("conversions", 0) * 50.0)),
            "campaign_convention": convention,
            "campaign_theme": theme,
            "campaign_type": ctype,
            "campaign_country": country,
        })
    return pd.DataFrame(rows)


def _anchor(ads):
    return ads["date"].max() + pd.Timedelta(days=4)  # the Sunday after the last row


def _headlines(alerts):
    return [a.headline for a in alerts]


def test_reference_week():
    start, end = anomalies._reference_week("2026-06-18")  # a Wednesday
    assert (start, end) == (pd.Timestamp("2026-06-08"), pd.Timestamp("2026-06-14"))
    start, end = anomalies._reference_week("2026-06-14")  # a Sunday
    assert (start, end) == (pd.Timestamp("2026-06-08"), pd.Timestamp("2026-06-14"))


def test_spend_up_without_conversion_lift():
    flat = [{"spend": 1000, "clicks": 500, "conversions": 50}] * 6
    surge = [{"spend": 1600, "clicks": 520, "conversions": 51}]
    ads = _weeks(flat + surge)
    alerts = anomalies.detect_alerts(ads, "X", _anchor(ads))
    assert "Spend up sharply, conversions flat" in _headlines(alerts)
    alert = next(a for a in alerts if a.headline.startswith("Spend up"))
    assert alert.confidence == "high"  # +60% spend clears the 0.6 bar
    assert "+60%" in alert.magnitude


def test_tracking_break_shape_spend_up_conversions_gone():
    # the scenario inject_tracking_break() builds: spend runs higher, the pixel
    # stopped firing so conversions are zero
    normal = [{"spend": 1000, "clicks": 500, "conversions": 45}] * 6
    broken = [{"spend": 1400, "clicks": 520, "conversions": 0}]
    ads = _weeks(normal + broken)
    alerts = anomalies.detect_alerts(ads, "X", _anchor(ads))
    alert = next(a for a in alerts if a.headline.startswith("Spend up"))
    assert alert.headline == "Spend up sharply, conversions fell"
    assert alert.confidence == "high"
    assert "tracking has broken" in alert.detail


def test_conversions_drop_while_spend_holds():
    flat = [{"spend": 1000, "clicks": 500, "conversions": 50}] * 6
    slump = [{"spend": 1010, "clicks": 480, "conversions": 30}]
    ads = _weeks(flat + slump)
    alerts = anomalies.detect_alerts(ads, "X", _anchor(ads))
    alert = next(a for a in alerts if a.headline == "Conversions dropped, spend held")
    assert alert.confidence == "high"  # -40%
    assert alert.severity == 3


def test_cpc_out_of_band_flags_a_real_jump():
    baseline = [{"spend": 500, "clicks": 490 + (i % 2) * 20, "conversions": 20} for i in range(8)]
    spike = [{"spend": 2000, "clicks": 500, "conversions": 20}]
    ads = _weeks(baseline + spike)
    alerts = anomalies.detect_alerts(ads, "X", _anchor(ads))
    assert "Google Ads CPC outside its normal range" in _headlines(alerts)


def test_cpc_check_skips_low_volume_channels():
    # same shape, but ~20 clicks a week — no stable band, so no alert
    baseline = [{"spend": 20, "clicks": 18 + (i % 2) * 4, "conversions": 1} for i in range(8)]
    spike = [{"spend": 90, "clicks": 20, "conversions": 1}]
    ads = _weeks(baseline + spike, channel="LinkedIn Ads")
    alerts = anomalies.detect_alerts(ads, "X", _anchor(ads))
    assert not any("CPC" in h for h in _headlines(alerts))


def test_stopped_delivering_flags_the_week_it_goes_dark():
    ran = [{"spend": 800, "clicks": 400, "conversions": 40}] * 4
    dark = [{"spend": 0, "clicks": 0, "conversions": 0}]
    ads = _weeks(ran + dark)
    alerts = anomalies.detect_alerts(ads, "X", _anchor(ads))
    alert = next(a for a in alerts if a.headline == "A campaign stopped delivering")
    assert alert.scope == "Brand Search · Google Ads"
    assert alert.confidence == "high"  # ran all four prior weeks


def test_quarter_rename_is_not_a_stop():
    q1 = _weeks([{"spend": 800, "clicks": 400, "conversions": 40}] * 3,
                campaign="Brand Search ES Q1")
    q2 = _weeks([{"spend": 800, "clicks": 400, "conversions": 40}] * 2,
                campaign="Brand Search ES Q2", start="2026-01-28")
    ads = pd.concat([q1, q2], ignore_index=True)
    alerts = anomalies.detect_alerts(ads, "X", _anchor(ads))
    assert "A campaign stopped delivering" not in _headlines(alerts)


def test_calm_history_produces_nothing():
    calm = [{"spend": 1000, "clicks": 500, "conversions": 50}] * 9
    ads = _weeks(calm)
    assert anomalies.detect_alerts(ads, "X", _anchor(ads)) == []


def test_too_little_history_is_silent():
    ads = _weeks([{"spend": 1000, "clicks": 500, "conversions": 50}])
    assert anomalies.detect_alerts(ads, "X", _anchor(ads)) == []


def test_filter_confidence():
    made = [
        Alert("Account", "a", "d", "m", "low", 1),
        Alert("Account", "b", "d", "m", "medium", 2),
        Alert("Account", "c", "d", "m", "high", 3),
    ]
    assert len(anomalies.filter_confidence(made, "low")) == 3
    assert [a.confidence for a in anomalies.filter_confidence(made, "medium")] == ["medium", "high"]
    assert [a.confidence for a in anomalies.filter_confidence(made, "high")] == ["high"]
