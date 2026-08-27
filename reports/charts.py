"""Report charts, rendered to base64 PNG data URIs.

PNG rather than SVG because Gmail and Outlook strip inline SVG. Sizes and fonts
are tuned for a chart shown a few hundred pixels wide on a phone — the report
is opened from a cold email more often on a phone than a laptop — not for
matplotlib's screen defaults.
"""

from __future__ import annotations

import base64
import io

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd

plt.rcParams.update({
    "font.family": "DejaVu Sans",  # bundled with matplotlib, so it's there on Streamlit Cloud too
    "font.size": 13,
    "axes.titlesize": 15,
    "axes.titleweight": "bold",
    "axes.edgecolor": "#c9ced6",
    "axes.grid": True,
    "grid.color": "#eceef1",
    "figure.dpi": 100,
    "savefig.dpi": 100,
})

_PRIOR_GREY = "#c9ced6"
_INK = "#33383f"
_EUR = mticker.FuncFormatter(lambda x, _: f"€{x:,.0f}")


def _finish(fig, alt: str) -> dict:
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white", bbox_inches="tight")
    plt.close(fig)
    uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    return {"uri": uri, "alt": alt}


def spend_revenue_by_day(daily: pd.DataFrame, accent: str) -> dict:
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    ax.bar(daily["date"], daily["spend"], width=0.8, color=accent, label="Spend")
    ax.set_ylabel("Spend")
    ax.yaxis.set_major_formatter(_EUR)

    ax2 = ax.twinx()
    ax2.plot(daily["date"], daily["conversion_value"], color=_INK, marker="o",
             markersize=4, linewidth=2, label="Revenue")
    ax2.set_ylabel("Revenue")
    ax2.yaxis.set_major_formatter(_EUR)
    ax2.grid(False)
    ax2.set_ylim(bottom=0)

    ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=8))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    for lbl in ax.get_xticklabels():
        lbl.set_rotation(30)
        lbl.set_ha("right")

    ax.set_title("Spend and revenue by day", loc="left")
    lines = ax.get_legend_handles_labels()[0] + ax2.get_legend_handles_labels()[0]
    labels = ["Spend", "Revenue"]
    ax.legend(lines, labels, loc="upper left", frameon=False, fontsize=12)
    return _finish(fig, "Bar chart of daily spend with a line for daily revenue over the period.")


def spend_by_channel(channel_df: pd.DataFrame, accent: str) -> dict:
    cb = channel_df.sort_values("spend")
    fig, ax = plt.subplots(figsize=(6.4, 2.9))
    ax.barh(cb["channel"], cb["spend"], color=accent)
    ax.xaxis.set_major_formatter(_EUR)
    ax.grid(axis="y")
    ax.margins(x=0.18)
    for i, v in enumerate(cb["spend"]):
        ax.text(v, i, f"  €{v:,.0f}", va="center", fontsize=11, color=_INK)
    ax.set_title("Spend by channel", loc="left")
    return _finish(fig, "Horizontal bar chart of total spend per channel for the period.")


def roas_by_channel(current_cb: pd.DataFrame, prior_cb: pd.DataFrame, accent: str) -> dict:
    # Organic has no spend, so ROAS is undefined for it — paid channels only.
    cur = current_cb[current_cb["spend"] > 0][["channel", "roas"]]
    merged = cur.merge(
        prior_cb[["channel", "roas"]], on="channel", how="left", suffixes=("_cur", "_prior")
    ).sort_values("roas_cur")

    y = range(len(merged))
    bar_h = 0.38
    fig, ax = plt.subplots(figsize=(6.4, 2.9))
    ax.barh([i + bar_h / 2 for i in y], merged["roas_cur"], height=bar_h,
            color=accent, label="This period")
    ax.barh([i - bar_h / 2 for i in y], merged["roas_prior"].fillna(0.0), height=bar_h,
            color=_PRIOR_GREY, label="Previous")
    ax.set_yticks(list(y))
    ax.set_yticklabels(merged["channel"])
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.1f}x"))
    ax.grid(axis="y")
    ax.margins(x=0.12)
    ax.set_title("ROAS by channel vs previous period", loc="left")
    ax.legend(loc="lower right", frameon=False, fontsize=12)
    return _finish(fig, "Horizontal bar chart comparing ROAS per channel this period against the previous one.")
