import streamlit as st

from lib import (
    CONFIDENCE_LEVELS,
    available_weeks,
    client_alerts,
    clients,
    default_week_start,
    filter_confidence,
    load_ads,
    remember_week_start,
    remembered_week_start,
    week_label,
)

st.title("Alerts")
st.caption("What the pipeline flagged for the selected week, across every client. "
           "The same checks that go into each report's “worth a look” section.")

ads = load_ads()
weeks = available_weeks(ads, clients(ads)[0])
want_start = remembered_week_start(weeks, default_week_start())
week_index = next(
    (i for i, w in enumerate(weeks) if w[0].strftime("%Y-%m-%d") == want_start),
    len(weeks) - 1,
)

left, right = st.columns(2)
week = left.selectbox("Week", weeks, index=week_index, format_func=lambda w: week_label(*w))
remember_week_start(week[0].strftime("%Y-%m-%d"))
min_conf = right.segmented_control(
    "Minimum confidence", CONFIDENCE_LEVELS, default=CONFIDENCE_LEVELS[0], selection_mode="single"
) or CONFIDENCE_LEVELS[0]

week_end = week[1].strftime("%Y-%m-%d")
results = {c: filter_confidence(client_alerts(c, week_end), min_conf) for c in clients(ads)}

flagged = sum(1 for v in results.values() if v)
total = sum(len(v) for v in results.values())
st.markdown(
    f"**{flagged} of {len(results)} clients flagged, {total} alert"
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
st.page_link("app_pages/report_preview.py", label="Open a client's full report", icon="📄")
