import sys
from pathlib import Path

# Make both `lib` (this folder) and `reports`/`pipeline` (repo root) importable
# whether Streamlit runs this from app/ or app/pages/.
_repo_root = Path(__file__).resolve().parent
while not (_repo_root / "pipeline").is_dir():
    _repo_root = _repo_root.parent
sys.path[:0] = [str(_repo_root), str(_repo_root / "app")]

import streamlit as st
import streamlit.components.v1 as components

from lib import (
    MOBILE_CSS,
    SYNTHETIC_NOTE,
    available_weeks,
    build_preview,
    clients,
    load_ads,
    theme_names,
    week_label,
)

st.set_page_config(page_title="Client report preview", layout="wide")
st.markdown(MOBILE_CSS, unsafe_allow_html=True)

st.title("Client report preview")
st.caption("Pick a client and a week to see the report the pipeline generates for them.")

st.info(
    "This page is just a viewer. The product is the pipeline — `python -m reports.run` — "
    "which builds these reports on a schedule and sends them by email. "
    + SYNTHETIC_NOTE
)

ads = load_ads()

# Controls on the page, not the sidebar: the sidebar auto-collapses on a phone
# and the page is meaningless without these.
left, right = st.columns(2)
client = left.selectbox("Client", clients(ads))
weeks = available_weeks(ads, client)
week = right.selectbox(
    "Week",
    weeks,
    index=len(weeks) - 1,
    format_func=lambda w: week_label(*w),
)

names = theme_names()
default_theme = next((n for n, stem in names.items() if stem == "northlight"), list(names)[0])
theme_display = st.segmented_control(
    "Agency theme", list(names), default=default_theme, selection_mode="single"
) or default_theme

html, alerts, period_label, height = build_preview(
    client, week[1].strftime("%Y-%m-%d"), names[theme_display]
)

status = f"⚠️ {len(alerts)} alert(s) flagged" if alerts else "✓ nothing flagged"
st.markdown(f"**{client} — week of {week_label(*week)}**  ·  {status}")
st.page_link("pages/1_Alerts.py", label="See every client's alerts for a week", icon="⚠️")

st.download_button(
    "Download this report (HTML)",
    data=html,
    file_name=f"{client.lower().replace(' ', '-')}_{week[1].date()}.html",
    mime="text/html",
)

# An iframe (not st.html) so the report renders exactly as it will in an inbox,
# base64 charts and all. Height is estimated in build_preview; scrolling covers
# the cases where the estimate runs short.
components.html(html, height=height, scrolling=True)
