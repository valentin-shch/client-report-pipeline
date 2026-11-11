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
    streamlit run app/streamlit_app.py

With Docker running, this is the live route: a fake ad platform API and Postgres,
pulled incrementally and cleaned per client. Copy `.env.example` to `.env` first.

    docker compose up -d --build
    set -a; . ./.env; set +a
    python -m pipeline.db init
    python -m runner

`runner` pulls and cleans every client, builds its report and records each step
in the `runs` table. One client failing doesn't stop the others, and
`python -m runner --retry-failed` re-runs whatever failed in the last week.
`--client` and `--anchor` target one client or week.

Reports wait for a person. Nothing is emailed until one is approved, and locally
the email lands in Mailpit at http://127.0.0.1:8025.

    python -m delivery list
    python -m delivery approve 12
    python -m delivery send 12
    python -m delivery retry 12

`retry` is for a send that failed. A report stuck on `sending` is left for a
person to check, because a late email beats a duplicate one.

`pytest` runs the database tests too when `TEST_DATABASE_URL` is set, and skips
them when it isn't.

`generate.py` uses an 18-month window ending last month so the data stays
current; the seed fixes the shape, only the dates move. The committed `data/`
and `samples/` were built with `CRP_DATA_END=2026-07-31` (see `.env.example`).
Set the same value to regenerate them exactly.

`reports.run` defaults to the most recent full week and writes into `samples/`.
`--anchor` pins a week, `--theme` switches agency, `--min-confidence` filters
alerts, `--list` shows the options. It builds the whole batch before writing.
The committed samples cover both themes and weeks chosen to show each alert type.

## Scheduling

`.github/workflows/pipeline.yml` runs `python -m runner --trigger schedule` every
Monday at 06:00 UTC. The Actions tab has a manual button too: one client, a
chosen week, or only what failed last time. `tests.yml` runs the tests on every
push against a real Postgres, and scans for committed secrets.

## Deploying

Four free services, each holding only the settings it needs:

- **Neon** (Postgres). Create the `pipeline` and `app` roles with `CREATE ROLE` in
  the SQL Editor, not from the dashboard: roles made there can write every table.
  Then run `python -m pipeline.db init` once with the owner's connection string.
- **Render** (the fake ad API). A Docker web service from `adsapi/Dockerfile`,
  built from the repo root, with `ADSAPI_KEY`, `FAULT_RATE` and
  `RATE_LIMIT_PER_MIN`. The free tier sleeps; the first Monday request wakes it.
- **GitHub Actions secrets**: `DATABASE_URL` (the pipeline role), `ADSAPI_URL`,
  `ADSAPI_KEY` and, optionally, `SLACK_WEBHOOK_URL`.
- **Streamlit Community Cloud**: main file `app/streamlit_app.py`, with secrets
  `APP_DATABASE_URL` (the app role), `APPROVAL_PASSCODE`, the `SMTP_` settings and
  `DEMO_RECIPIENT`, the one inbox every approved report goes to.
