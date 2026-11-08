import pandas as pd
import streamlit as st

from control import error_type, load_runs, stop_if_unavailable
from lib import SYNTHETIC_NOTE, week_label

st.title("Client Report Pipeline")
st.caption("What the pipeline did on its last run, and on every run before it.")
st.info(
    "An agency's weekly client reports, pulled from the ad platforms, cleaned, built and "
    "checked by an unattended pipeline every Monday. Each report waits for a person to "
    "approve it before it's emailed. " + SYNTHETIC_NOTE
)

runs = stop_if_unavailable(load_runs)
if runs.empty:
    st.markdown("No runs yet. The first one appears here once `python -m runner` has run.")
    st.stop()


def when(ts) -> str:
    ts = pd.Timestamp(ts).tz_convert("UTC")
    return f"{ts:%a} {ts.day} {ts:%b %Y, %H:%M} UTC"  # no %-d: Windows strftime lacks it


def week(run) -> str:
    return week_label(pd.Timestamp(run["period_start"]), pd.Timestamp(run["period_end"]))


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def outcome(run) -> str:
    if run["status"] == "succeeded":
        return f":green[:material/check_circle:] **{run['client']}** · report built · {plural(run['alerts'], 'alert')}"
    if run["status"] == "running":
        return f":gray[:material/pending:] **{run['client']}** · still running"
    return (f":red[:material/error:] **{run['client']}** · failed at {run['step']} "
            f"({error_type(run['error'])})")


# Shown first, so the answer to "did Monday's run work?" lands above the fold on a phone.
latest = runs[runs["batch"] == runs.iloc[0]["batch"]].sort_values("client")
ok = int((latest["status"] == "succeeded").sum())
with st.container(border=True):
    st.subheader("Last run")
    st.caption(f"{when(latest['started_at'].min())} · {latest.iloc[0]['trigger']}")
    st.markdown(f"**{ok} of {plural(len(latest), 'client')} succeeded** · "
                f"{plural(int(latest['alerts'].sum()), 'alert')} flagged")
    for _, run in latest.iterrows():
        st.markdown(outcome(run))

# The top menu folds behind a button on a phone, so the other pages are linked here too.
st.page_link("app_pages/report_preview.py", label="Report preview", icon=":material/description:")
st.page_link("app_pages/alerts.py", label="Alerts", icon=":material/warning:")

st.subheader("Run history")
st.caption("Tap a run for its steps, retries and data-quality numbers.")


def detail(run) -> None:
    steps = " → ".join(
        f"{s['step']} {s['seconds']} s" + (f" · {s['rows']:,} rows" if s["step"] == "ingest" else "")
        for s in run["steps"]
    )
    st.markdown(steps or "No steps finished.")
    facts = [plural(int(run["retries"]), "retry").replace("retrys", "retries")]
    if run["status"] == "failed":
        facts.append(f"failed at {run['step']}: {error_type(run['error'])}")
    dq = run["dq_summary"]
    if dq:
        facts += [
            f"{dq['rows_in']['raw_ads']:,} rows cleaned",
            f"{dq.get('duplicates_collapsed_at_ingest', 0)} duplicates",
            f"{dq['conversion_value_imputed']['rows_imputed']} imputed",
            f"FX {dq.get('fx_stale_days', 0)} days stale",
        ]
    st.caption(" · ".join(facts))


icons = {"succeeded": ":material/check_circle:", "failed": ":material/error:", "running": ":material/pending:"}
for batch, group in runs.groupby("batch", sort=False):
    st.markdown(f"**{when(group['started_at'].min())}** · {group.iloc[0]['trigger']}")
    for _, run in group.sort_values("client").iterrows():
        label = f"{run['client']} · week of {week(run)}"
        if run["error"] == "abandoned":
            # its finish time is when housekeeping noticed, not how long it ran
            label += " · abandoned"
        elif pd.notna(run["finished_at"]):
            label += f" · {int((run['finished_at'] - run['started_at']).total_seconds())} s"
        with st.expander(label, icon=icons.get(run["status"])):
            detail(run)
