import pandas as pd

import data.generate as gen
from data.generate import generate

START, END = pd.Timestamp("2025-02-01"), pd.Timestamp("2025-04-30")


def test_generate_is_repeatable():
    a, b = generate(START, END), generate(START, END)
    assert a.keys() == b.keys()
    for key in a:
        pd.testing.assert_frame_equal(a[key], b[key])


def test_generate_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "RAW_DIR", tmp_path)
    generate(START, END)
    assert list(tmp_path.iterdir()) == []


def test_generate_keeps_platform_quirks():
    out = generate(START, END)
    assert out["meta_ads"]["date"].iloc[0] == "01/02/2025"   # dd/mm/yyyy
    assert out["linkedin_ads"]["date"].min() == "2025-01-31"  # UTC one-day slip
    assert out["google_ads"].duplicated().any()               # re-export overlap


def test_break_ref_places_the_pixel_outage():
    out = generate(START, END, break_ref=pd.Timestamp("2025-03-12"))
    g = out["google_ads"]
    week = g[(g["client"] == "Solmar Hotels") & g["date"].between("2025-03-10", "2025-03-16")]
    assert len(week) and (week["conversions"] == 0).all()
