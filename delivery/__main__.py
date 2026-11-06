"""Approve and send from the command line.

    python -m delivery list
    python -m delivery approve 12
    python -m delivery send 12
    python -m delivery retry 12
"""

from __future__ import annotations

import argparse
import sys

from delivery.mailer import SmtpMailer
from delivery.send import approve, retry_send, send_report
from pipeline.db import connect, read_frame


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m delivery")
    parser.add_argument("command", choices=["list", "approve", "send", "retry"])
    parser.add_argument("report_id", type=int, nargs="?")
    args = parser.parse_args(argv)
    if args.command != "list" and args.report_id is None:
        parser.error(f"{args.command} needs a report id")

    with connect() as conn:
        if args.command == "list":
            reports = read_frame(conn, """
                SELECT id, status, client, subject, error FROM reports ORDER BY id DESC LIMIT 20""")
            print(reports.to_string(index=False) if len(reports) else "no reports")
            return 0
        if args.command == "approve":
            ok = approve(conn, args.report_id)
            print("approved" if ok else "not pending")
            return 0 if ok else 1
        action = send_report if args.command == "send" else retry_send
        outcome = action(conn, args.report_id, SmtpMailer.from_env())
        print(outcome)
        return 0 if outcome == "sent" else 1


if __name__ == "__main__":
    sys.exit(main())
