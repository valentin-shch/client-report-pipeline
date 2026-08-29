# Client Report Pipeline

**[Live demo →](https://client-report-pipeline-valentin.streamlit.app/)**

Most agencies rebuild the same client report every week by hand: pull the
numbers, drop them into a branded template, write the commentary, send it. This
does that in one command, producing a self-contained HTML report per client,
styled for the agency, ready to drop into an email.

The focus is the recurring pipeline, not a dashboard. Each report has the
headline KPIs against the previous period, a "what changed" summary, a short
plain-language read, and three charts. Inline styles, single column, base64
images, nothing loaded from outside, so it survives an email client on a phone.

## What's in it

- **Report generator.** `python -m reports.run --client all --period last-week`
  writes one HTML file per client. Schedulable from cron or a GitHub Action.
- **Alerts.** Each report gets a "worth a look" section: spend up with no
  conversion lift, conversions down while spend held, CPC out of range, a
  campaign that stopped. Week-over-week percentages and a median/MAD z-score.
  Explainable, over-flags on purpose, magnitude and confidence on every flag.
- **Theming.** Agency name, accent colour and logo live in a TOML file under
  `reports/themes/`, so the same pipeline serves several agencies. Two examples
  ship: Northlight Media and Harbour Point Digital.
- **Cleaning pipeline.** `pipeline/clean.py` turns the messy raw exports into
  analysis-ready parquet and writes a summary of what it had to fix.
- **Metrics.** `pipeline/metrics.py`, pure functions for the KPIs, period
  comparisons, time series and anomaly maths, covered by `tests/`.
- **Preview app.** A small Streamlit viewer (`app/`): a report page (pick a
  client and week, switch theme, download the HTML) and a cross-client alert
  list for any week. See the output without an inbox; not the product.

## Time saved

Assembling one client report by hand (four exports, a template, charts,
commentary, an anomaly check) runs 60 to 90 minutes. Call it 75.

    manual, weekly:   4 reports x 75 min       = 5.0 hrs / client / month
    generated:        4 reports x 5 min review = 0.3 hrs / client / month
                                                 ~4.7 hrs saved / client

The 5 minutes is a person reading the report before it goes out, not building
anything. Across a dozen clients that's about 55 hours a month.

## The data

Nothing here is real. `data/generate.py` (started from the marketing-dashboard
project's generator) builds ~18 months of synthetic ad exports and CRM deals for
three fictional clients: a hotel group, a fitness brand, a clinic. It's
deliberately messy: duplicate rows, three date formats, LinkedIn in the wrong
currency, a timezone slip, inconsistent campaign names, unmatched CRM deals, and
one week where a client's conversion pixel broke while spend carried on.
`pipeline/clean.py` fixes the export quirks; the pixel outage is a real event,
so it survives cleaning and the alert layer catches it.

## Stack

Python, pandas, matplotlib (charts), Jinja (HTML), Streamlit (preview app). No
database: CSV to parquet to disk. No external services, no API keys.

## Structure

    data/generate.py     synthetic data generator, seeded
    data/raw/            generator output, messy on purpose, committed
    data/clean/          cleaned parquet + data-quality summary, committed
    pipeline/clean.py    raw exports -> clean, joined parquet
    pipeline/metrics.py  KPIs, period comparisons, anomaly maths (pure functions)
    reports/             report generator, alerts, theming, CLI
    reports/themes/      one TOML per agency
    app/                 Streamlit preview app
    samples/             example reports, committed so you can read one without running anything
    tests/               pytest for the metrics and the alert logic

## Running it locally

    python data/generate.py
    python pipeline/clean.py
    pytest
    python -m reports.run --client all --period last-week
    streamlit run app/Report_Preview.py

`generate.py` uses an 18-month window ending last month so the data stays
current; the seed fixes the shape, only the dates move. The committed `data/`
and `samples/` were built with `CRP_DATA_END=2026-07-31` (see `.env.example`).
Set the same value to regenerate them exactly.

`reports.run` defaults to the most recent full week and writes into `samples/`.
`--anchor` pins a week, `--theme` switches agency, `--min-confidence` filters
alerts, `--list` shows the options. It builds the whole batch before writing.
The committed samples cover both themes and weeks chosen to show each alert type.

## Scheduling

The CLI is one unattended command. `.github/workflows/reports.yml` runs the whole
pipeline every Monday and uploads the reports as an artifact. In cron:

    0 6 * * 1  cd /path/to/repo && python -m reports.run --client all --period last-week --out /var/reports

## Deploying

Streamlit Community Cloud runs the repo as committed (no build step; `data/` is
in the repo). Point it at `app/Report_Preview.py`; nothing to configure.
