import pandas as pd

from app import lib


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
