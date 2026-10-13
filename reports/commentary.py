"""Turn the period deltas into the report's plain-language sections.

Everything here is deterministic text assembly, no templates of opinion, just
the numbers stated in sentences a client can act on. The one judgement call is
the 2% flat band (from pipeline.metrics.trend_label): a move smaller than that
is called "steady" rather than up or down, and the report says so in a footnote
so the wording always matches the figures.
"""

from __future__ import annotations

import pandas as pd

from pipeline.metrics import PCT_DISPLAY_CAP, trend_label

FLAT_BAND = 0.02
THRESHOLD_NOTE = (
    "“Rose” and “fell” describe a move of more than 2% against the "
    "previous period; anything smaller is called steady."
)


def _move_phrase(change_pct: float, current: float = None, prior: float = None,
                 unit_fmt=None, up: str = "rose", down: str = "fell",
                 flat: str = "held roughly steady") -> str:
    """`unit_fmt` is only needed for ratio metrics (ROAS, cost/conversion): past
    PCT_DISPLAY_CAP their percentage move is almost always a collapsed
    denominator rather than real news, so the sentence states the absolute move
    instead of a four-digit percentage."""
    label = trend_label(change_pct, FLAT_BAND)
    if label == "flat":
        return flat
    word = up if label == "up" else down
    if unit_fmt is not None and abs(change_pct) >= PCT_DISPLAY_CAP:
        return f"{word} by {unit_fmt(abs(current - prior))}"
    return f"{word} {abs(round(change_pct * 100))}%"


def headline_read(deltas: dict, period_word: str, comparable: bool) -> str:
    rev, spend = deltas["conversion_value"], deltas["spend"]
    roas, conv, cpa = deltas["roas"], deltas["conversions"], deltas["cpa"]

    if not comparable:
        return (
            f"Revenue for the {period_word} was €{rev['current']:,.0f} from "
            f"€{spend['current']:,.0f} of spend, a {roas['current']:.2f}x return. "
            f"There is no comparable earlier {period_word} in the data yet, so this "
            f"report sets the baseline rather than measuring a change."
        )

    s1 = (f"Revenue {_move_phrase(rev['change_pct'])} against the previous {period_word}, "
          f"to €{rev['current']:,.0f}.")

    roas_move = _move_phrase(roas["change_pct"], roas["current"], roas["prior"],
                             lambda v: f"{v:.2f}x")
    eff = trend_label(roas["change_pct"], FLAT_BAND)
    if eff == "up":
        s2 = f"Spend worked harder for it: ROAS {roas_move} to {roas['current']:.2f}x."
    elif eff == "down":
        s2 = f"Spend worked less hard, though. ROAS {roas_move} to {roas['current']:.2f}x."
    else:
        s2 = f"Efficiency was stable, with ROAS around {roas['current']:.2f}x."

    cpa_move = _move_phrase(cpa["change_pct"], cpa["current"], cpa["prior"],
                            lambda v: f"€{v:,.2f}")
    s3 = (f"Conversions {_move_phrase(conv['change_pct'])} to {conv['current']:,.0f}, and "
          f"cost per conversion {cpa_move} to €{cpa['current']:,.2f}.")
    return " ".join([s1, s2, s3])


def what_changed(movers_df: pd.DataFrame, comparable: bool, revenue_total: float) -> list[str]:
    if not comparable:
        return ["First report for this client, so there is nothing to compare against yet."]

    # Ignore movers worth less than 1% of the period's revenue; otherwise a
    # tiny channel's few-euro wobble shows up next to the ones that mattered.
    floor = max(1.0, 0.01 * revenue_total)

    lines = []
    for _, r in movers_df.iterrows():
        if abs(r["change"]) < floor:
            continue
        verb = "added" if r["change"] >= 0 else "lost"
        pct = f" ({r['change_pct'] * 100:+.0f}%)" if pd.notna(r["change_pct"]) else ""
        lines.append(f"{r['channel']} {verb} €{abs(r['change']):,.0f} in revenue{pct}.")

    if not lines:
        lines.append("No channel moved revenue by more than 1% of the period total.")
    return lines
