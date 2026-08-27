"""Synthetic ad-platform and CRM data for three fictional agency clients.

Writes messy, per-platform raw exports to data/raw/ — the same shape and
quirks a real Google Ads / Meta / LinkedIn / CRM export would have. The
cleaning pipeline (pipeline/clean.py) is what turns this into something
analysis-ready; nothing here is pre-cleaned.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

SEED = 42
rng = np.random.default_rng(SEED)

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"

# 18-month window ending last month, so the demo doesn't visibly go stale.
_end_of_last_month = pd.Timestamp.today().normalize().replace(day=1) - pd.Timedelta(days=1)
START_DATE = _end_of_last_month.replace(day=1) - pd.DateOffset(months=17)
END_DATE = _end_of_last_month

PAID_CHANNELS = ["Google Ads", "Meta Ads", "LinkedIn Ads"]

CHANNEL_PARAMS = {
    "Google Ads": {"cpm": (7, 14), "ctr": (0.03, 0.06), "cvr": (0.02, 0.05)},
    "Meta Ads": {"cpm": (5, 11), "ctr": (0.008, 0.02), "cvr": (0.01, 0.03)},
    "LinkedIn Ads": {"cpm": (28, 48), "ctr": (0.004, 0.009), "cvr": (0.015, 0.035)},
}


# --- seasonality -----------------------------------------------------------
# Each returns a same-day multiplier on the client's baseline channel spend.

def solmar_seasonality(date: pd.Timestamp) -> float:
    doy = date.dayofyear
    peak = np.exp(-((doy - 200) / 45) ** 2)  # centred mid-July
    return 0.5 + 1.3 * peak


def nordfit_seasonality(date: pd.Timestamp) -> float:
    if (date.month == 11 and date.day >= 20) or (date.month == 12 and date.day <= 2):
        return 3.2  # Black Friday / Cyber Monday window
    if date.month == 1 and date.day <= 15:
        return 2.4  # January sale
    if date.month == 12:
        return 1.3  # pre-holiday lift
    return 1.0


def vantia_seasonality(date: pd.Timestamp) -> float:
    return 1.4 if date.month == 9 else 1.0


# --- campaign naming conventions --------------------------------------------
# Three real agencies would each have their own convention; the client roll-up
# in pipeline/clean.py has to reconcile all three plus a fallback bucket.

def name_solmar(country: str, ctype: str, theme: str, period: str) -> str:
    return f"{country}_{ctype}_{theme}_{period}"


def name_nordfit(country: str, ctype: str, theme: str, period: str) -> str:
    return f"{country}-{ctype}-{theme}-{period}".lower()


def name_vantia(country: str, ctype: str, theme: str, period: str) -> str:
    return f"{theme} {ctype} {country} {period}"


def quarter_label(date: pd.Timestamp, with_year: bool) -> str:
    q = (date.month - 1) // 3 + 1
    return f"{date.year}Q{q}" if with_year else f"Q{q}"


def in_window(date: pd.Timestamp, window: tuple | None) -> bool:
    """Window is either a (month, day, month, day) pair that recurs every
    year (seasonal promos), or a pair of actual Timestamps for a one-time
    span (e.g. a campaign retired early in the data window, never repeating).
    """
    if window is None:
        return True
    if isinstance(window[0], pd.Timestamp):
        start, end = window
        return start <= date <= end
    sm, sd, em, ed = window
    start = pd.Timestamp(year=date.year, month=sm, day=sd)
    end = pd.Timestamp(year=date.year, month=em, day=ed)
    return start <= date <= end


def slot(channel, ctype, theme, country, weight, window=None, fixed_name=None):
    return dict(
        channel=channel, ctype=ctype, theme=theme, country=country,
        weight=weight, window=window, fixed_name=fixed_name,
    )


CLIENTS = {
    "Solmar Hotels": dict(
        seasonality=solmar_seasonality,
        name_fn=name_solmar,
        year_in_name=True,
        base_spend={"Google Ads": 380, "Meta Ads": 260, "LinkedIn Ads": 45},
        # value of one ad-platform conversion (an inquiry, not a booking —
        # CRM deal_value below is the real, sales-assisted number)
        avg_value=45,
        organic_baseline=900,
        slots=[
            slot("Google Ads", "Search", "Brand", "ES", weight=0.35),
            slot("Google Ads", "Search", "Generic", "ES", weight=0.45),
            slot("Google Ads", "Search", "SummerEscape", "ES", weight=0.35, window=(4, 1, 8, 31)),
            slot("Meta Ads", "Social", "Prospecting", "ES", weight=0.5),
            slot("Meta Ads", "Social", "Retargeting", "ES", weight=0.4),
            slot("Meta Ads", "Social", "Prospecting", "PT", weight=0.3, window=(3, 1, 9, 30)),
            slot("LinkedIn Ads", "Sponsored", "Corporate", "ES", weight=1.0),
        ],
    ),
    "Nordfit Equipment": dict(
        seasonality=nordfit_seasonality,
        name_fn=name_nordfit,
        year_in_name=False,
        base_spend={"Google Ads": 220, "Meta Ads": 300, "LinkedIn Ads": 25},
        avg_value=30,
        organic_baseline=1400,
        slots=[
            slot("Google Ads", "Search", "Brand", "ES", weight=0.3),
            slot("Google Ads", "Shopping", "Generic", "ES", weight=0.4),
            slot("Google Ads", "Shopping", "BlackFriday", "ES", weight=0.6, window=(11, 20, 12, 2)),
            slot("Google Ads", "Shopping", "JanuarySale", "ES", weight=0.5, window=(1, 1, 1, 15)),
            # leftover from the client's previous agency, phased out ~6 weeks
            # into the data window once we took over — a one-time span, not
            # a recurring seasonal one, hence the explicit Timestamp window
            slot("Google Ads", "Search", "Legacy", "ES", weight=0.15,
                 window=(START_DATE, START_DATE + pd.Timedelta(days=45)), fixed_name="GYM_PROMO_OLD"),
            slot("Meta Ads", "Social", "Prospecting", "ES", weight=0.45),
            slot("Meta Ads", "Social", "Retargeting", "ES", weight=0.35),
            slot("Meta Ads", "Social", "BlackFriday", "ES", weight=0.7, window=(11, 20, 12, 2)),
            slot("Meta Ads", "Social", "JanuarySale", "ES", weight=0.5, window=(1, 1, 1, 15)),
            slot("LinkedIn Ads", "Sponsored", "Wholesale", "ES", weight=1.0),
        ],
    ),
    "Clinica Vantia": dict(
        seasonality=vantia_seasonality,
        name_fn=name_vantia,
        year_in_name=False,
        base_spend={"Google Ads": 60, "Meta Ads": 40, "LinkedIn Ads": 15},
        avg_value=40,
        organic_baseline=250,
        slots=[
            slot("Google Ads", "Search", "Brand", "ES", weight=0.4),
            slot("Google Ads", "Search", "LeadGen", "ES", weight=0.6),
            slot("Meta Ads", "Social", "Prospecting", "ES", weight=0.5),
            slot("Meta Ads", "Social", "Retargeting", "ES", weight=0.3),
            slot("LinkedIn Ads", "Sponsored", "Partnerships", "ES", weight=1.0),
        ],
    ),
}


# --- row generation ----------------------------------------------------------

def generate_paid_rows(client: str, cfg: dict, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    records = []
    for channel in PAID_CHANNELS:
        channel_slots = [s for s in cfg["slots"] if s["channel"] == channel]
        if not channel_slots:
            continue
        params = CHANNEL_PARAMS[channel]
        for date in calendar:
            active = [s for s in channel_slots if in_window(date, s["window"])]
            if not active:
                continue
            period = quarter_label(date, cfg["year_in_name"])
            total_weight = sum(s["weight"] for s in active)
            seasonality = cfg["seasonality"](date)
            dow_mult = 0.25 if channel == "LinkedIn Ads" and date.dayofweek >= 5 else 1.0
            noise = rng.lognormal(0, 0.15)
            channel_budget = cfg["base_spend"][channel] * seasonality * dow_mult * noise
            cpm = rng.uniform(*params["cpm"])
            ctr = rng.uniform(*params["ctr"])
            cvr = rng.uniform(*params["cvr"])
            for s in active:
                spend = channel_budget * (s["weight"] / total_weight)
                lam_impr = spend / cpm * 1000
                impressions = int(rng.poisson(lam_impr)) if lam_impr > 0 else 0
                clicks = int(rng.binomial(impressions, ctr)) if impressions > 0 else 0
                conversions = int(rng.binomial(clicks, cvr)) if clicks > 0 else 0
                conv_value = (
                    round(conversions * cfg["avg_value"] * rng.lognormal(0, 0.25), 2)
                    if conversions > 0 else 0.0
                )
                name = s["fixed_name"] or cfg["name_fn"](s["country"], s["ctype"], s["theme"], period)
                records.append((
                    date, client, channel, name, round(spend, 2),
                    impressions, clicks, conversions, conv_value,
                ))
    return pd.DataFrame(records, columns=[
        "date", "client", "channel", "campaign_name", "spend",
        "impressions", "clicks", "conversions", "conversion_value",
    ])


def generate_organic_rows(client: str, cfg: dict, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    records = []
    baseline = cfg["organic_baseline"]
    total_days = (calendar[-1] - calendar[0]).days
    for date in calendar:
        elapsed = (date - calendar[0]).days
        growth = 1 + 0.35 * (elapsed / total_days)  # slow organic growth from SEO work
        seasonality = cfg["seasonality"](date)
        lam_impr = baseline * seasonality * growth * rng.lognormal(0, 0.1)
        impressions = int(rng.poisson(lam_impr))
        ctr = rng.uniform(0.02, 0.045)
        clicks = int(rng.binomial(impressions, ctr)) if impressions > 0 else 0
        cvr = rng.uniform(0.02, 0.045)
        conversions = int(rng.binomial(clicks, cvr)) if clicks > 0 else 0
        conv_value = (
            round(conversions * cfg["avg_value"] * rng.lognormal(0, 0.25), 2)
            if conversions > 0 else 0.0
        )
        records.append((
            date, client, "Organic Search", "Organic Search", 0.0,
            impressions, clicks, conversions, conv_value,
        ))
    return pd.DataFrame(records, columns=[
        "date", "client", "channel", "campaign_name", "spend",
        "impressions", "clicks", "conversions", "conversion_value",
    ])


# --- deliberate messiness ----------------------------------------------------

def inject_missing_conversion_value(df: pd.DataFrame, rate: float = 0.04) -> pd.DataFrame:
    df = df.copy()
    eligible = df.index[df["conversions"] > 0]
    n = int(len(eligible) * rate)
    chosen = rng.choice(eligible, size=n, replace=False)
    df.loc[chosen, "conversion_value"] = np.nan
    return df


def inject_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """Simulate a re-export that overlapped a prior export by ~10 days per client."""
    dup_frames = [df]
    for client in df["client"].unique():
        dates = np.sort(df.loc[df["client"] == client, "date"].unique())
        start_idx = rng.integers(30, len(dates) - 40)
        window_dates = dates[start_idx:start_idx + 10]
        dup = df[(df["client"] == client) & (df["date"].isin(window_dates))].copy()
        dup_frames.append(dup)
    return pd.concat(dup_frames, ignore_index=True)


DATE_FORMATS = {
    "Google Ads": "%Y-%m-%d",
    "Meta Ads": "%d/%m/%Y",
    "LinkedIn Ads": "%Y-%m-%d",
    "Organic Search": "%Y-%m-%d",
}
FILE_NAMES = {
    "Google Ads": "google_ads.csv",
    "Meta Ads": "meta_ads.csv",
    "LinkedIn Ads": "linkedin_ads.csv",
    "Organic Search": "organic_search.csv",
}


def write_channel_files(ads_df: pd.DataFrame) -> None:
    for channel, fname in FILE_NAMES.items():
        sub = ads_df[ads_df["channel"] == channel].copy()
        sub = sub.sort_values(["client", "date"]).reset_index(drop=True)
        if channel == "LinkedIn Ads":
            # LinkedIn's export timestamps in UTC; the rest run on Europe/Madrid
            # business days. Modelled here as a flat one-day offset rather than
            # an hour-level shift — close enough to produce the same visible
            # artefact the cleaning step has to correct for.
            sub["date"] = sub["date"] - pd.Timedelta(days=1)
        sub["date"] = sub["date"].dt.strftime(DATE_FORMATS[channel])
        sub.to_csv(RAW_DIR / fname, index=False)


def generate_fx_rates() -> pd.DataFrame:
    calendar = pd.date_range(START_DATE, END_DATE, freq="D")
    weekdays = calendar[calendar.dayofweek < 5]
    rate = 0.92
    rates = []
    for _ in weekdays:
        rate = min(max(rate + rng.normal(0, 0.0015), 0.85), 0.98)
        rates.append(round(rate, 4))
    return pd.DataFrame({"date": weekdays.strftime("%Y-%m-%d"), "usd_eur": rates})


MALFORMED_SOURCES = [
    "facebook", "google ad", "referral - ask client", "walk-in", "TBD",
    "n/a", "unknown source", "instagram dm", "old campaign?", "-",
]


def corrupt_name(name: str) -> str:
    style = rng.integers(0, 3)
    if style == 0:
        return name[:max(3, len(name) // 2)]
    if style == 1:
        return name.replace("_", " ").replace("-", " ").lower() + "??"
    return name.upper() + " (COPY)"


def pick_source_campaign(pool: list[str]) -> str | None:
    r = rng.random()
    if r < 0.6:
        return rng.choice(pool)
    if r < 0.8:
        return None
    if rng.random() < 0.5:
        return rng.choice(MALFORMED_SOURCES)
    return corrupt_name(rng.choice(pool))


DEAL_RATES = {"Solmar Hotels": 0.9, "Nordfit Equipment": 0.6, "Clinica Vantia": 0.3}
DEAL_VALUE_RANGE = {
    "Solmar Hotels": (150, 3000),
    "Nordfit Equipment": (200, 5000),
    "Clinica Vantia": (400, 4000),
}


def generate_crm_deals(ads_df: pd.DataFrame) -> pd.DataFrame:
    # (first-seen date, name) per client, so a deal can only cite a campaign
    # that had actually launched by the time the deal was created.
    first_seen = (
        ads_df.groupby(["client", "campaign_name"])["date"].min()
        .reset_index().sort_values("date")
    )
    campaign_timeline = {
        client: list(zip(sub["date"], sub["campaign_name"]))
        for client, sub in first_seen.groupby("client")
    }

    calendar = pd.date_range(START_DATE, END_DATE, freq="D")
    rows = []
    deal_num = 1
    for client, cfg in CLIENTS.items():
        rate = DEAL_RATES[client]
        lo, hi = DEAL_VALUE_RANGE[client]
        timeline = campaign_timeline[client]
        for date in calendar:
            lam = rate * cfg["seasonality"](date)
            for _ in range(int(rng.poisson(lam))):
                deal_id = f"DEAL-{deal_num:05d}"
                deal_num += 1
                # TODO: uniform within range per client; a real CRM's deal sizes
                # are probably long-tailed rather than flat.
                deal_value = round(float(rng.uniform(lo, hi)), 2)
                days_to_end = (END_DATE - date).days
                if days_to_end < 14:
                    stage = rng.choice(["New", "Qualified"], p=[0.6, 0.4])
                    closed_date = pd.NaT
                else:
                    outcome = rng.choice(["Won", "Lost", "Open"], p=[0.5, 0.25, 0.25])
                    if outcome == "Open":
                        stage = rng.choice(["New", "Qualified"])
                        closed_date = pd.NaT
                    else:
                        stage = outcome
                        delay = int(rng.integers(3, min(60, max(days_to_end, 4))))
                        closed_date = date + pd.Timedelta(days=delay)
                pool = [name for seen, name in timeline if seen <= date]
                source_campaign = pick_source_campaign(pool)
                rows.append((deal_id, client, date, closed_date, stage, deal_value, source_campaign))
    return pd.DataFrame(rows, columns=[
        "deal_id", "client", "created_date", "closed_date", "stage", "deal_value", "source_campaign",
    ])


def print_sample(ads_df: pd.DataFrame, crm_df: pd.DataFrame) -> None:
    for fname in list(FILE_NAMES.values()) + ["fx_rates.csv", "crm_deals.csv"]:
        sample = pd.read_csv(RAW_DIR / fname)
        print(f"\n{fname}  ({len(sample)} rows)")
        print(sample.head(5).to_string(index=False))

    dup_rate = ads_df.duplicated(keep="first").sum() / len(ads_df) * 100
    missing_rate = (
        ads_df.loc[ads_df["conversions"] > 0, "conversion_value"].isna().sum()
        / (ads_df["conversions"] > 0).sum() * 100
    )
    all_names = set(ads_df["campaign_name"].unique())
    matched = crm_df["source_campaign"].isin(all_names).mean() * 100
    null = crm_df["source_campaign"].isna().mean() * 100
    malformed = 100 - matched - null

    print("\n--- messiness check ---")
    print(f"ads rows: {len(ads_df)}  |  duplicate rate: {dup_rate:.1f}%")
    print(f"conversion_value missing (of rows with conversions>0): {missing_rate:.1f}%")
    print(f"CRM deals: {len(crm_df)}  |  source_campaign matched: {matched:.1f}%  "
          f"null: {null:.1f}%  malformed: {malformed:.1f}%")


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    calendar = pd.date_range(START_DATE, END_DATE, freq="D")

    frames = []
    for client, cfg in CLIENTS.items():
        frames.append(generate_paid_rows(client, cfg, calendar))
        frames.append(generate_organic_rows(client, cfg, calendar))
    ads_df = pd.concat(frames, ignore_index=True)

    ads_df = inject_missing_conversion_value(ads_df)
    ads_df = inject_duplicates(ads_df)

    write_channel_files(ads_df)
    generate_fx_rates().to_csv(RAW_DIR / "fx_rates.csv", index=False)

    crm_df = generate_crm_deals(ads_df)
    crm_out = crm_df.copy()
    crm_out["created_date"] = crm_out["created_date"].dt.strftime("%Y-%m-%d")
    crm_out["closed_date"] = crm_out["closed_date"].dt.strftime("%Y-%m-%d")
    crm_out.to_csv(RAW_DIR / "crm_deals.csv", index=False)

    print_sample(ads_df, crm_df)


if __name__ == "__main__":
    main()
