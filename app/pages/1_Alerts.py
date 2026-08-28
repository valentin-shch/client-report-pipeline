import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent
while not (_repo_root / "pipeline").is_dir():
    _repo_root = _repo_root.parent
sys.path[:0] = [str(_repo_root), str(_repo_root / "app")]

import streamlit as st

from lib import (
    CONFIDENCE_LEVELS,
    MOBILE_CSS,
    available_weeks,
    client_alerts,
    clients,
    filter_confidence,
    load_ads,
    week_label,
)

st.set_page_config(page_title="Alerts", layout="wide")
st.markdown(MOBILE_CSS, unsafe_allow_html=True)

st.title("Alerts")
st.caption("What the pipeline flagged for the selected week, across every client — "
           "the same checks that go into each report's “worth a look” section.")

ads = load_ads()
weeks = available_weeks(ads, clients(ads)[0])

left, right = st.columns(2)
week = left.selectbox("Week", weeks, index=len(weeks) - 1, format_func=lambda w: week_label(*w))
min_conf = right.segmented_control(
    "Minimum confidence", CONFIDENCE_LEVELS, default=CONFIDENCE_LEVELS[0], selection_mode="single"
) or CONFIDENCE_LEVELS[0]

week_end = week[1].strftime("%Y-%m-%d")
results = {c: filter_confidence(client_alerts(c, week_end), min_conf) for c in clients(ads)}

flagged = sum(1 for v in results.values() if v)
total = sum(len(v) for v in results.values())
st.markdown(
    f"**{flagged} of {len(results)} clients flagged — {total} alert"
    f"{'' if total == 1 else 's'}** for the week of {week_label(*week)}."
)

for client, alerts in results.items():
    st.subheader(client)
    if not alerts:
        st.caption("✓ Nothing flagged")
        continue
    for a in alerts:
        with st.container(border=True):
            st.markdown(f"**{a.headline}**")
            st.caption(f"{a.confidence.upper()} CONFIDENCE · {a.scope}")
            st.write(a.detail)
            st.caption(a.magnitude)

st.divider()
st.page_link("Report_Preview.py", label="Open a client's full report", icon="📄")
