# Client Report Pipeline

Most agencies rebuild the same client report every week by hand — pull the
numbers, drop them into a branded template, write a few lines of commentary,
send it. This does that automatically: one command produces a self-contained
HTML report per client, styled for the agency, ready to drop into an email.

The focus is the recurring pipeline rather than a dashboard someone has to log
into. Each report has the headline KPIs against the previous period, a "what
changed" summary, a short plain-language read, and three charts. The HTML is
built to survive an email client on a phone: inline styles, single column,
images embedded as base64, nothing loaded from outside.

## What's in it

- **Report generator** — `python -m reports.run --client all --period last-week`.
  One HTML file per client, schedulable from cron or a GitHub Action.
- **Alerts** — a "worth a look" section on each report: spend up with no
  conversion lift, conversions down while spend held, CPC outside its normal
  range, a campaign that stopped delivering. Week-over-week percentages and a
  median/MAD z-score, nothing you can't explain in the sentence next to the
  flag. It errs toward over-flagging — every alert states a magnitude and a
  confidence so you can triage.
- **Theming** — agency name, accent colour and logo live in a TOML file under
  `reports/themes/`, so the same pipeline serves several agencies. Two examples
  ship: Northlight Media and Harbour Point Digital.
- **Cleaning pipeline** — `pipeline/clean.py` turns the messy raw exports into
  analysis-ready parquet and writes a summary of what it had to fix.
- **Metrics** — `pipeline/metrics.py`, pure functions for the KPIs, period
  comparisons, time series and anomaly maths, covered by `tests/`.
- **Preview app** — a small Streamlit viewer (`app/`): a report page (pick a
  client and week, switch agency theme, download the HTML) and an alert list
  across all clients for any week. A way to see the output without opening an
  inbox, not the product.

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

Python, pandas, matplotlib for the report charts, Jinja for the HTML, Streamlit
for the preview app. No database — data is generated to CSV, cleaned to parquet,
read from disk. No external services, no API keys.

## Structure

    data/generate.py     synthetic data generator, seeded
    data/raw/            generator output, messy on purpose, committed
    data/clean/          cleaned parquet + data-quality summary, committed
    pipeline/clean.py    raw exports -> clean, joined parquet
    pipeline/metrics.py  KPIs, period comparisons, anomaly maths — pure functions
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

`generate.py` uses an 18-month window ending last month so the data doesn't go
stale; the seed keeps the shape of the data fixed and only the dates move.

`reports.run` defaults to the most recent full week of data and writes HTML into
`samples/`. `--anchor YYYY-MM-DD` picks (and pins) a different week, `--theme`
switches agency, `--min-confidence medium` hides the noisier alerts, `--list`
prints the known clients and themes. It builds the whole batch before writing
anything, so a failure can't leave some clients updated and others not. The
committed samples cover both themes and a few weeks chosen to show each alert
type.

## Scheduling

The CLI is a single unattended command. `.github/workflows/reports.yml` runs the
whole pipeline every Monday — regenerate, clean, test, build every client's
report — and uploads the HTML as a build artifact. The same thing in cron:

    0 6 * * 1  cd /path/to/repo && python -m reports.run --client all --period last-week --out /var/reports

## Deploying

Streamlit Community Cloud runs the repo as committed — `data/raw/` and
`data/clean/` are in the repo and there's no build step. Point it at
`app/Report_Preview.py`. Nothing calls an external service, so there's nothing
to configure.
