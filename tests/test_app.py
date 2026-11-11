import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import lib  # noqa: E402  (the app imports its modules by bare name)


def test_week_label():
    assert lib.week_label(pd.Timestamp("2026-03-09"), pd.Timestamp("2026-03-15")) == "9–15 Mar 2026"
    assert lib.week_label(pd.Timestamp("2026-06-29"), pd.Timestamp("2026-07-05")) == "29 Jun – 5 Jul 2026"


def test_available_weeks_are_complete_mon_to_sun_and_ordered():
    dates = pd.date_range("2026-01-07", "2026-02-03", freq="D")  # a Wed to a Tue
    ads = pd.DataFrame({"client": "X", "date": dates})
    weeks = lib.available_weeks(ads, "X")

    # first complete week starts Mon 2026-01-12; last ends on or before 2026-02-03
    assert weeks[0] == (pd.Timestamp("2026-01-12"), pd.Timestamp("2026-01-18"))
    assert all(s.weekday() == 0 and e.weekday() == 6 for s, e in weeks)
    assert all((e - s).days == 6 for s, e in weeks)
    assert weeks == sorted(weeks)
    assert weeks[-1][1] <= pd.Timestamp("2026-02-03")


def flagged_ads():
    days = pd.date_range("2026-03-02", "2026-03-29", freq="D")  # four Mon-Sun weeks
    ads = pd.DataFrame({"client": "Solmar Hotels", "date": days, "channel": "Google Ads",
                        "spend": 100.0, "conversions": 5})
    other = ads.assign(client="Nordfit Equipment")
    dark = ads["date"].between("2026-03-16", "2026-03-22")
    ads.loc[dark, "conversions"] = 0  # spend carried on, conversions stopped
    return pd.concat([ads, other], ignore_index=True)


def test_default_selection_is_the_week_a_client_spent_with_no_conversions():
    assert lib.default_selection(flagged_ads()) == ("Solmar Hotels", "2026-03-16")


def test_organic_rows_never_count_as_a_dark_week():
    ads = flagged_ads()
    ads.loc[ads["conversions"] == 0, "channel"] = "Organic Search"
    ads.loc[ads["channel"] == "Organic Search", "spend"] = 0.0
    assert lib.default_selection(ads) == ("Nordfit Equipment", "2026-03-23")


def test_without_a_dark_week_it_opens_on_the_newest_week():
    ads = flagged_ads()
    ads["conversions"] = 5
    assert lib.default_selection(ads) == ("Nordfit Equipment", "2026-03-23")


def test_a_week_that_ends_today_is_not_complete_yet():
    # LinkedIn's one-day label shift puts a row on today's date
    days = pd.date_range("2026-03-02", "2026-03-15", freq="D")
    ads = pd.DataFrame({"client": "X", "date": days})
    weeks = lib.available_weeks(ads, "X", today=pd.Timestamp("2026-03-15"))
    assert weeks[-1] == (pd.Timestamp("2026-03-02"), pd.Timestamp("2026-03-08"))


def test_shared_weeks_are_the_ones_complete_for_every_client():
    a = pd.DataFrame({"client": "A", "date": pd.date_range("2026-03-02", "2026-03-22", freq="D")})
    b = pd.DataFrame({"client": "B", "date": pd.date_range("2026-03-02", "2026-03-19", freq="D")})
    weeks = lib.shared_weeks(pd.concat([a, b]), today=pd.Timestamp("2026-04-01"))
    assert weeks[-1] == (pd.Timestamp("2026-03-09"), pd.Timestamp("2026-03-15"))
