"""CLI entry point for the report pipeline.

    python -m reports.run --client all --period last-week

Writes one self-contained HTML report per client to the output directory. Meant
to run unattended from cron or a scheduled GitHub Action: it takes no input
beyond flags, defaults the reporting date to the freshest data available, and
builds the whole batch before writing anything — so a bug can't leave half the
clients with a stale report and half with none.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from reports.anomalies import CONFIDENCE_LEVELS, filter_confidence
from reports.report import NoDataForPeriod, build_report, render_html, slug
from reports.theme import available_themes, load_theme

BASE_DIR = Path(__file__).resolve().parent.parent
ADS_PARQUET = BASE_DIR / "data" / "clean" / "ads.parquet"
PERIODS = ("last-week", "last-month")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m reports.run", description=__doc__.splitlines()[0])
    p.add_argument("--client", default="all",
                   help='client name, or "all" (default) for every client')
    p.add_argument("--period", default="last-week", choices=PERIODS,
                   help="reporting period (default: last-week)")
    p.add_argument("--anchor", default=None, metavar="YYYY-MM-DD",
                   help="date the period is measured back from "
                        "(default: the day after the most recent data)")
    p.add_argument("--theme", default="northlight",
                   help=f"agency theme; one of: {', '.join(available_themes())}")
    p.add_argument("--min-confidence", default="low", choices=CONFIDENCE_LEVELS,
                   help="drop alerts below this confidence (default: low, i.e. show all)")
    p.add_argument("--out", default=str(BASE_DIR / "samples"), metavar="DIR",
                   help="output directory (default: samples/)")
    p.add_argument("--list", action="store_true",
                   help="print the known clients and themes, then exit")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    if not ADS_PARQUET.exists():
        sys.exit(f"{ADS_PARQUET} not found — run pipeline/clean.py first.")
    ads = pd.read_parquet(ADS_PARQUET)
    known = sorted(ads["client"].unique())

    if args.list:
        print("clients:\n  " + "\n  ".join(known))
        print("themes:\n  " + "\n  ".join(available_themes()))
        return 0

    try:
        theme = load_theme(args.theme)
    except (FileNotFoundError, ValueError) as e:
        sys.exit(str(e))
    anchor = (pd.Timestamp(args.anchor) if args.anchor
              else ads["date"].max() + pd.Timedelta(days=1))

    if args.client == "all":
        clients = known
    elif args.client in known:
        clients = [args.client]
    else:
        sys.exit(f"unknown client {args.client!r}; known: {', '.join(known)}")

    # Build the whole batch first. A NoDataForPeriod is about the data, not the
    # code, so we note it and carry on; anything else aborts before a file is
    # written.
    built, skipped = [], []
    for client in clients:
        try:
            report = build_report(ads, client, anchor, args.period, theme.accent)
        except NoDataForPeriod as e:
            skipped.append(str(e))
            continue
        report.alerts = filter_confidence(report.alerts, args.min_confidence)
        start = report.window[0].date()
        path = Path(args.out) / f"{slug(client)}_{args.period}_{start}_{args.theme}.html"
        built.append((report, render_html(report, theme), path))

    for msg in skipped:
        print(f"skipped {msg}", file=sys.stderr)

    if not built:
        print("nothing to write", file=sys.stderr)
        return 1

    Path(args.out).mkdir(parents=True, exist_ok=True)
    for report, html, path in built:
        path.write_text(html, encoding="utf-8")
        flagged = f"{len(report.alerts)} alert(s)" if report.alerts else "no alerts"
        print(f"{report.client}: {report.period_label}, {flagged} -> {_show(path)}")

    return 0


def _show(path: Path) -> str:
    try:
        return str(path.relative_to(BASE_DIR))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
