import pandas as pd

from pipeline import clean


def test_parse_campaign_name_conventions():
    a = clean.parse_campaign_name("Google Ads", "ES_Search_Generic_2025Q3")
    assert a == {"convention": "A", "country": "ES", "type": "Search",
                 "theme": "Generic", "period": "2025Q3"}

    b = clean.parse_campaign_name("Meta Ads", "es-social-retargeting-q1")
    assert (b["convention"], b["country"], b["type"], b["theme"]) == ("B", "ES", "Social", "Retargeting")

    c = clean.parse_campaign_name("Google Ads", "Brand Search ES Q2")
    assert (c["convention"], c["theme"], c["period"]) == ("C", "Brand", "Q2")


def test_compound_theme_names_get_a_two_word_label():
    # the compound tokens read as one word after .title(); THEME_LABELS restores them,
    # and it has to work whether the source convention preserves case or not
    assert clean.parse_campaign_name("Google Ads", "ES_Shopping_BlackFriday_2025Q4")["theme"] == "Black Friday"
    assert clean.parse_campaign_name("Meta Ads", "es-social-blackfriday-q4")["theme"] == "Black Friday"
    assert clean.parse_campaign_name("Google Ads", "SummerEscape Search ES Q3")["theme"] == "Summer Escape"


def test_unrecognised_name_goes_to_unknown():
    out = clean.parse_campaign_name("Google Ads", "GYM_PROMO_OLD")
    assert out["convention"] == "unknown"
    assert out["theme"] is None


def test_clean_ads_copes_with_no_missing_values():
    # a client with nothing to impute, which DB mode's per-client scope makes possible
    ads = pd.DataFrame({
        "date": pd.to_datetime(["2025-03-03", "2025-03-04"]), "client": ["A", "A"],
        "channel": ["Google Ads", "Google Ads"], "campaign_name": ["x", "x"], "spend": [1.0, 2.0],
        "impressions": [10, 20], "clicks": [1, 2], "conversions": [1, 1], "conversion_value": [5.0, 6.0],
    })
    fx = pd.DataFrame({"date": pd.to_datetime(["2025-03-03"]), "usd_eur": [0.9]})
    out, stats = clean.clean_ads(ads, fx)
    assert stats["conversion_value_imputed"] == {"rows_imputed": 0, "value_imputed_eur": 0.0}
    assert not out["conversion_value_imputed"].any()
    assert out["conversion_value"].tolist() == [5.0, 6.0]
