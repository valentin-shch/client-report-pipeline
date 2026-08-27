# Client Report Pipeline

Most agencies rebuild the same client report every week by hand — pull the
numbers, drop them into a branded template, write a few lines of commentary,
send it. This does that automatically: one command produces a self-contained
HTML report per client, styled for the agency, ready to drop into an email.

It's meant to be sold as a monthly retainer, so the emphasis is on the recurring
pipeline rather than a dashboard someone has to log into. Each report has the
headline KPIs against the previous period, a "what changed" summary, a short
plain-language read, and three charts. The HTML is built to survive an email
client on a phone: inline styles, single column, images embedded as base64,
nothing loaded from outside.

## What's in it

- **Report generator** — `python -m reports.run --client all --period last-week`.
  One HTML file per client, schedulable from cron or a GitHub Action.
- **Theming** — agency name, accent colour and logo live in a TOML file under
  `reports/themes/`, so the same pipeline serves several agencies. Two examples
  ship: Northlight Media and Harbour Point Digital.
- **Cleaning pipeline** — `pipeline/clean.py` turns the messy raw exports into
  analysis-ready parquet and writes a summary of what it had to fix.
- **Metrics** — `pipeline/metrics.py`, pure functions for the KPIs, period
  comparisons, time series and anomaly maths, covered by `tests/`.

## The data

Nothing here is real. `data/generate.py` builds about 18 months of synthetic ad
exports (Google Ads, Meta Ads, LinkedIn Ads, Organic Search) and CRM deals for
three fictional clients — a hotel group, a fitness-equipment brand and a clinic.
It's the same generator as the marketing-dashboard project, copied over
unchanged, and it's deliberately messy: duplicate rows, three date formats,
LinkedIn spend in the wrong currency, a one-day timezone slip, campaign names in
three different conventions, and CRM deals that don't all match back to a
campaign. `pipeline/clean.py` sorts all of it out and shows its working in
`data/clean/data_quality_summary.json`.

## Stack

Python, pandas, matplotlib for the report charts, Jinja for the HTML. No
database — data is generated to CSV, cleaned to parquet, read from disk. No
external services, no API keys.

## Structure

    data/generate.py     synthetic data generator, seeded
    data/raw/            generator output, messy on purpose, committed
    data/clean/          cleaned parquet + data-quality summary, committed
    pipeline/clean.py    raw exports -> clean, joined parquet
    pipeline/metrics.py  KPIs, period comparisons, anomaly maths — pure functions
    reports/             report generator, theming, CLI
    reports/themes/      one TOML per agency
    samples/             example reports, committed so you can read one without running anything
    tests/               pytest for the metric functions

## Running it locally

    python data/generate.py
    python pipeline/clean.py
    pytest
    python -m reports.run --client all --period last-week

`generate.py` uses an 18-month window ending last month so the demo doesn't go
stale; the seed keeps the shape of the data fixed and only the dates move.
`reports.run` writes HTML into `samples/` — pass `--anchor YYYY-MM-DD` to pin
the period for reproducible output, `--theme` to switch agency.
