"""CLI entry point for the report pipeline.

    python -m reports.run --client all --period last-week

Writes one self-contained HTML report per client to the output directory. Built
to be run unattended from cron or a scheduled GitHub Action, so it takes no
input beyond flags and fails loudly rather than half-producing a batch.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from reports.anomalies import CONFIDENCE_LEVELS, filter_confidence
from reports.report import build_report, render_html, slug
from reports.theme import available_themes, load_theme

BASE_DIR = Path(__file__).resolve().parent.parent
ADS_PARQUET = BASE_DIR / "data" / "clean" / "ads.parquet"
PERIODS = ("last-week", "last-month")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m reports.run", description=__doc__.splitlines()[0])
    p.add_argument("--client", default="all",
                   help='client name, or "all" (default) for every client')
    p.add_argument("--period", default="last-week", choices=PERIODS,
                   help="reporting period relative to the anchor date (default: last-week)")
    p.add_argument("--anchor", default=None, metavar="YYYY-MM-DD",
                   help="date the period is measured back from (default: today). "
                        "Pin it for reproducible output.")
    p.add_argument("--theme", default="northlight",
                   help=f"agency theme; one of: {', '.join(available_themes())}")
    p.add_argument("--min-confidence", default="low", choices=CONFIDENCE_LEVELS,
                   help="drop alerts below this confidence (default: low, i.e. show all)")
    p.add_argument("--out", default=str(BASE_DIR / "samples"), metavar="DIR",
                   help="output directory (default: samples/)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    if not ADS_PARQUET.exists():
        sys.exit(f"{ADS_PARQUET} not found — run pipeline/clean.py first.")

    ads = pd.read_parquet(ADS_PARQUET)
    anchor = pd.Timestamp(args.anchor) if args.anchor else pd.Timestamp.today().normalize()
    theme = load_theme(args.theme)

    known = sorted(ads["client"].unique())
    if args.client == "all":
        clients = known
    elif args.client in known:
        clients = [args.client]
    else:
        sys.exit(f"unknown client {args.client!r}; known: {', '.join(known)}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    for client in clients:
        report = build_report(ads, client, anchor, args.period, theme.accent)
        report.alerts = filter_confidence(report.alerts, args.min_confidence)
        html = render_html(report, theme)
        start = report.window[0].date()
        path = out_dir / f"{slug(client)}_{args.period}_{start}_{args.theme}.html"
        path.write_text(html, encoding="utf-8")
        flagged = f"{len(report.alerts)} alert(s)" if report.alerts else "no alerts"
        print(f"{client}: {report.period_label}, {flagged} -> {path.relative_to(BASE_DIR)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
