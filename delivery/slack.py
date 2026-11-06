from __future__ import annotations

import os

import httpx


def _count(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def summary_text(results) -> str:
    ready = [r for r in results if r.status == "succeeded" and r.report in ("created", "replaced")]
    failed = [r for r in results if r.status == "failed"]
    alerts = sum(r.alerts for r in ready)
    lines = [f"{_count(len(ready), 'report')} ready · {len(failed)} failed · {_count(alerts, 'alert')}"]
    lines += [f"• {r.slug}: {(r.error or '')[:120]}" for r in failed]
    if failed:
        lines.append("Re-run with: python -m runner --retry-failed")
    return "\n".join(lines)


def post_summary(results, url: str | None = None, post=httpx.post) -> bool:
    """A failed post is logged and forgotten: the run's outcome is in the runs
    table either way, and Slack being down shouldn't turn a good run red."""
    url = url or os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        return False
    try:
        response = post(url, json={"text": summary_text(results)}, timeout=10)
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        print(f"slack post failed: {type(e).__name__}")  # the webhook URL is a secret
        return False
    if response.status_code >= 400:
        print(f"slack post failed: HTTP {response.status_code}")
        return False
    return True
