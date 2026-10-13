import math

import pandas as pd
import pytest

from reports import commentary, report, theme


# --- theme -----------------------------------------------------------------

def test_example_themes_load_with_a_logo():
    for name in theme.available_themes():
        t = theme.load_theme(name)
        assert t.name
        assert t.accent.startswith("#") and len(t.accent) == 7
        assert t.logo_data_uri.startswith("data:image/png;base64,")


def test_unknown_theme_names_the_alternatives():
    with pytest.raises(FileNotFoundError) as e:
        theme.load_theme("does-not-exist")
    assert "northlight" in str(e.value)


def test_bad_accent_colour_is_rejected(tmp_path):
    bad = tmp_path / "broken.toml"
    bad.write_text('name = "Broken"\naccent = "teal"\n')
    with pytest.raises(ValueError):
        theme.load_theme(str(bad))


def test_missing_logo_file_is_rejected(tmp_path):
    bad = tmp_path / "noglogo.toml"
    bad.write_text('name = "No Logo"\naccent = "#123456"\nlogo = "nope.png"\n')
    with pytest.raises(FileNotFoundError):
        theme.load_theme(str(bad))


# --- period labels -------------------------------------------------------------

def test_period_label_week_same_month():
    label = report._period_label("last-week", pd.Timestamp("2026-07-20"), pd.Timestamp("2026-07-26"))
    assert label == "Week of 20–26 Jul 2026"


def test_period_label_week_spanning_months():
    label = report._period_label("last-week", pd.Timestamp("2026-06-29"), pd.Timestamp("2026-07-05"))
    assert label == "Week of 29 Jun – 5 Jul 2026"


def test_period_label_month():
    label = report._period_label("last-month", pd.Timestamp("2026-05-01"), pd.Timestamp("2026-05-31"))
    assert label == "May 2026"


# --- delta display -----------------------------------------------------------

def test_delta_display_directions():
    # roas up is good; roas down is bad; bold and coloured either way
    good = report._delta_display({"change_pct": 0.2, "direction": "higher_better"})
    bad = report._delta_display({"change_pct": -0.2, "direction": "higher_better"})
    assert good["delta_color"] == report._GOOD
    assert bad["delta_color"] == report._BAD
    assert good["delta_weight"] == "600"

    # cpa down is good (lower is better)
    cpa_good = report._delta_display({"change_pct": -0.15, "direction": "lower_better"})
    assert cpa_good["delta_color"] == report._GOOD


def test_spend_delta_is_never_a_red_green_verdict():
    # the A1 lesson: spend/volume has no inherent good direction. A big drop
    # gets the quiet grey and normal weight, not red.
    for cp in (-0.24, 0.5, -0.6):
        out = report._delta_display({"change_pct": cp, "direction": "neutral"})
        assert out["delta_color"] == report._NEUTRAL
        assert out["delta_color"] not in (report._GOOD, report._BAD)
        assert out["delta_weight"] == "400"


def test_delta_display_nan_is_blank():
    out = report._delta_display({"change_pct": float("nan"), "direction": "higher_better"})
    assert out["delta"] == "" and out["delta_color"] == ""


def test_cpa_blowup_from_collapsed_conversions_shows_euros_not_percent():
    # conversions crater from 23 to 1 (already its own high-confidence alert);
    # cost/conversion "explodes" mathematically even though nothing new happened.
    # A four-digit percentage reads as a data error, so show the euro move instead.
    d = {"current": 484.0, "prior": 10.0, "change_pct": 47.4, "direction": "lower_better"}
    fmt = lambda v: "n/a" if pd.isna(v) else f"€{v:,.2f}"
    out = report._delta_display(d, fmt)
    assert "%" not in out["delta"]
    assert out["delta"] == "+€474.00 vs prev"
    assert out["delta_color"] == report._BAD  # cpa up is bad (lower is better)


def test_roas_spike_from_near_zero_prior_shows_multiple_not_percent():
    d = {"current": 4.0, "prior": 0.05, "change_pct": 79.0, "direction": "higher_better"}
    fmt = lambda v: f"{v:.2f}x"
    out = report._delta_display(d, fmt)
    assert "%" not in out["delta"]
    assert out["delta"] == "+3.95x vs prev"
    assert out["delta_color"] == report._GOOD


def test_ordinary_moves_stay_percentages_even_with_fmt_supplied():
    d = {"current": 12.0, "prior": 10.0, "change_pct": 0.2, "direction": "lower_better"}
    out = report._delta_display(d, fmt=lambda v: f"€{v:,.2f}")
    assert out["delta"] == "+20% vs prev"


def test_slug():
    assert report.slug("Clínica Vantia!") == "cl-nica-vantia"
    assert report.slug("Solmar Hotels") == "solmar-hotels"


# --- commentary ------------------------------------------------------------

def test_move_phrase_respects_flat_band():
    assert commentary._move_phrase(0.33) == "rose 33%"
    assert commentary._move_phrase(-0.24) == "fell 24%"
    assert commentary._move_phrase(0.01) == "held roughly steady"  # inside 2% band


def test_move_phrase_caps_a_collapsed_denominator_at_the_absolute_move():
    # cost per conversion "rising 4752%" when conversions cratered to near zero
    # reads as a data error; state the euro move instead past the cap.
    phrase = commentary._move_phrase(47.4, current=484.0, prior=10.0, unit_fmt=lambda v: f"€{v:,.2f}")
    assert phrase == "rose by €474.00"
    assert "%" not in phrase


def test_headline_read_states_absolute_cpa_move_when_conversions_collapse():
    deltas = {
        "conversion_value": {"current": 343.0, "prior": 12000.0, "change_pct": -0.97},
        "spend": {"current": 3400.0, "prior": 2400.0, "change_pct": 0.42},
        "roas": {"current": 0.10, "prior": 5.0, "change_pct": -0.98},
        "conversions": {"current": 7.0, "prior": 230.0, "change_pct": -0.97},
        "cpa": {"current": 473.96, "prior": 9.79, "change_pct": 47.4},
    }
    text = commentary.headline_read(deltas, "week", comparable=True)
    assert "%" not in text.split("cost per conversion")[1]
    assert "rose by €464.17" in text


def test_what_changed_drops_movers_below_one_percent():
    movers = pd.DataFrame({
        "channel": ["Google Ads", "Meta Ads", "LinkedIn Ads"],
        "change": [13000.0, -1500.0, 3.0],
        "change_pct": [0.46, -0.24, -0.04],
    })
    lines = commentary.what_changed(movers, comparable=True, revenue_total=47000)
    assert len(lines) == 2  # the €3 LinkedIn move is below 1% of €47k
    assert lines[0].startswith("Google Ads added")


def test_what_changed_first_report():
    lines = commentary.what_changed(pd.DataFrame(), comparable=False, revenue_total=0)
    assert len(lines) == 1 and "First report" in lines[0]


def test_headline_read_not_comparable_sets_baseline():
    deltas = {
        "conversion_value": {"current": 5000.0, "change_pct": float("nan")},
        "spend": {"current": 1000.0, "change_pct": float("nan")},
        "roas": {"current": 5.0, "change_pct": float("nan")},
        "conversions": {"current": 100.0, "change_pct": float("nan")},
        "cpa": {"current": 10.0, "change_pct": float("nan")},
    }
    text = commentary.headline_read(deltas, "week", comparable=False)
    assert "baseline" in text
    assert "5.00x" in text
