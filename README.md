# Client Report Pipeline

An automated client-reporting pipeline for a digital marketing agency. It turns
weekly ad and CRM data into a branded, email-ready HTML report per client —
headline KPIs against the previous period, a few charts, plain-language
commentary, and a short "what changed" summary — plus a simple anomaly-alert
layer that flags the things worth a phone call before the report goes out.

The product is the pipeline, not a dashboard. It runs from one CLI command
(`python -m reports.run --client all --period last-week`), so it drops straight
into a cron job or a scheduled GitHub Action. A thin Streamlit app is included
so the output is clickable from a cold email, but that app is the demo, not the
deliverable.

The data is synthetic. `data/generate.py` builds about 18 months of deliberately
messy ad exports (Google Ads, Meta Ads, LinkedIn Ads, Organic Search) and CRM
deals for three fictional clients — the same generator used in the marketing
dashboard project, copied across unchanged.

## Structure

    data/generate.py     synthetic data generator, seeded, reproducible
    data/raw/            generator output (messy on purpose, committed)
    pipeline/clean.py    raw exports -> clean, joined parquet
    pipeline/metrics.py  business metric calculations, pure functions
    reports/            report generator, theming, anomaly detection, CLI
    app/                Streamlit demo app
    tests/             pytest for the metric and anomaly functions

## Running it locally

    python data/generate.py

Regenerates `data/raw/` with an 18-month window ending last month, so the demo
data doesn't go stale. The seed keeps the shape of the data stable across runs —
only the calendar dates shift with the run date.

More stages (cleaning, metrics, reports, app) are added as the pipeline is built
out; this README grows with them.
