import streamlit as st

from control import load_clean_ads, stop_if_unavailable
from lib import (
    SYNTHETIC_NOTE,
    available_weeks,
    build_preview,
    clients,
    default_selection,
    remember_week_start,
    remembered_week_start,
    report_frame,
    theme_names,
    week_label,
)

st.title("Client Report Pipeline")
st.caption("Pick a client and a week to see the report the pipeline generates for them.")

st.info(
    "This page is just a viewer. The product is the pipeline (`python -m runner`), which "
    "builds these reports every Monday; a person approves each one before it's emailed. "
    + SYNTHETIC_NOTE
)

ads = stop_if_unavailable(load_clean_ads)
if not any(available_weeks(ads, c) for c in clients(ads)):
    st.markdown("No data yet. Reports appear here once the pipeline has a full week to show.")
    st.stop()
default_client, default_monday = default_selection(ads)

# Controls on the page, not the sidebar: the sidebar auto-collapses on a phone
# and the page is meaningless without these. First load opens on the week the
# pipeline flags something interesting, so the page isn't blank of alerts.
left, right = st.columns(2)
client = left.selectbox(
    "Client", clients(ads), index=clients(ads).index(default_client), key="client"
)
weeks = available_weeks(ads, client)
if not weeks:
    st.markdown(f"No full week for {client} yet.")
    st.stop()
want_start = remembered_week_start(weeks, default_monday)
week_index = next(
    (i for i, w in enumerate(weeks) if w[0].strftime("%Y-%m-%d") == want_start),
    len(weeks) - 1,
)
week = right.selectbox(
    "Week", weeks, index=week_index, format_func=lambda w: week_label(*w)
)
remember_week_start(week[0].strftime("%Y-%m-%d"))

names = theme_names()
default_theme = next((n for n, stem in names.items() if stem == "northlight"), list(names)[0])
theme_display = st.segmented_control(
    "Agency theme", list(names), default=default_theme, selection_mode="single"
) or default_theme

html, alerts, period_label = stop_if_unavailable(
    build_preview, client, week[1].strftime("%Y-%m-%d"), names[theme_display]
)

status = f"⚠️ {len(alerts)} alert(s) flagged" if alerts else "✓ nothing flagged"
st.markdown(f"**{client}, week of {week_label(*week)}**  ·  {status}")
st.page_link("app_pages/alerts.py", label="See every client's alerts for a week", icon="⚠️")

st.download_button(
    "Download this report (HTML)",
    data=html,
    file_name=f"{client.lower().replace(' ', '-')}_{week[1].date()}.html",
    mime="text/html",
)

# Rendered in an iframe so it looks exactly as it will in an inbox, base64
# charts and all; the report_frame component measures its own height so there's
# no fixed guess and no leftover whitespace.
report_frame(html)
