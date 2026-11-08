import sys
from pathlib import Path

# Make `lib` and `control` (this folder) and the pipeline packages (repo root)
# importable however Streamlit was started.
_app_dir = Path(__file__).resolve().parent
sys.path[:0] = [str(_app_dir.parent), str(_app_dir)]

import streamlit as st

from lib import MOBILE_CSS

st.set_page_config(page_title="Client Report Pipeline", layout="wide")
st.markdown(MOBILE_CSS, unsafe_allow_html=True)

page = st.navigation(
    [
        st.Page("app_pages/runs.py", title="Runs", icon=":material/history:", default=True),
        st.Page("app_pages/approvals.py", title="Approvals", icon=":material/send:"),
        st.Page("app_pages/report_preview.py", title="Report preview", icon=":material/description:"),
        st.Page("app_pages/alerts.py", title="Alerts", icon=":material/warning:"),
    ],
    position="top",
)
page.run()
