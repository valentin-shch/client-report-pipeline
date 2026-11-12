import streamlit as st

st.title("How it works")
st.markdown("""
<style>
  @media (max-width: 999px) { .st-key-diagram-wide { display: none; } }
  @media (min-width: 1000px) { .st-key-diagram-tall { display: none; } }
  /* The step cards are a fixed width for the laptop row; on a phone, fill it.
     Streamlit fixes that width on the wrapper around each card, so that's the
     element to widen. */
  @media (max-width: 640px) {
    [data-testid="stLayoutWrapper"]:has(> [class*="st-key-step-"]) { flex: 1 1 100% !important; }
    [class*="st-key-step-"] { width: 100% !important; }
  }
  /* Side by side, each row of cards takes the height of its tallest card. */
  [data-testid="stHorizontalBlock"]:has(> [data-testid="stLayoutWrapper"] > [class*="st-key-step-"]) {
    align-items: stretch !important;
  }
  /* Streamlit sizes the wrapper around each card to its content, which stops
     the row stretching it; release that height. */
  [data-testid="stLayoutWrapper"]:has(> [class*="st-key-step-"]) {
    display: flex !important; align-self: stretch !important; height: auto !important;
  }
  [class*="st-key-step-"] { height: auto !important; }
</style>
""", unsafe_allow_html=True)
st.caption("What happens every Monday, without anyone touching it.")

st.subheader("What runs where")

ARCHITECTURE = """
    gha["GitHub Actions<br/>every Monday, 06:00"]
    api["Ad platform API<br/>a stand-in, on Render"]
    db[("Postgres, on Neon<br/>raw and clean data,<br/>reports, run history")]
    app["This app, on Streamlit"]
    resend["Resend"]
    inbox(["The client's inbox"])
    slack["Slack"]
    person(["A person"])

    gha -- "pulls the week's data" --> api
    api -- "cleaned and stored" --> db
    db -- "read by" --> app
    app -- "sends the email" --> resend
    resend --> inbox
    gha -. "run summary" .-> slack
    person -- "approves" --> app
"""

# The same diagram twice: left to right fills a laptop, top to bottom stays
# readable on a phone (a wide one shrinks to nothing at 390 px). The CSS below
# shows whichever suits the screen; the server can't tell what device it is.
with st.container(key="diagram-wide"):
    st.mermaid_chart("graph LR" + ARCHITECTURE)
with st.container(key="diagram-tall"):
    st.mermaid_chart("graph TD" + ARCHITECTURE)


st.subheader("Every Monday, step by step")

# (step, icon, what happens, where to see it in this app). No database calls on
# this page: it should explain the pipeline even while the database sleeps.
STEPS = [
    ("Every Monday", ":material/schedule:",
     "At 06:00 a scheduled job starts the run on its own. Nobody presses anything.",
     [("app_pages/runs.py", "Runs", ":material/history:")]),
    ("Pulls the week", ":material/cloud_download:",
     "It asks each ad platform for the new data, page by page. Here that's a stand-in API "
     "that fails on purpose now and then, so every request that fails is retried.",
     [("app_pages/runs.py", "Runs", ":material/history:")]),
    ("Cleans it", ":material/cleaning_services:",
     "Duplicates removed, three date formats agreed, dollars turned into euros, missing "
     "values filled and flagged. Every fix is counted.",
     [("app_pages/runs.py", "Runs", ":material/history:")]),
    ("Builds the report", ":material/description:",
     "Each client gets a branded report: the numbers against last week, three charts, a "
     "plain-language read, and anything worth a look.",
     [("app_pages/report_preview.py", "Report preview", ":material/description:"),
      ("app_pages/alerts.py", "Alerts", ":material/warning:")]),
    ("A person approves", ":material/send:",
     "Nothing is emailed until someone reads it and approves it. Then it goes out once, "
     "and a summary of the run lands in Slack.",
     [("app_pages/approvals.py", "Approvals", ":material/send:")]),
]

# Fixed-width cards in a wrapping row: one per row on a phone, a few side by side
# on a tablet, all five in a line on a laptop. 228 px is what fits five across.
with st.container(horizontal=True, gap="medium"):
    for number, (title, icon, text, links) in enumerate(STEPS, start=1):
        with st.container(border=True, width=228, height="stretch", key=f"step-{number}"):
            st.markdown(f"{icon} **{number}. {title}**")
            st.markdown(text)
            for path, label, link_icon in links:
                st.page_link(path, label=label, icon=link_icon)

st.subheader("When something breaks")
st.markdown(
    "- A request that fails is retried, waiting a little longer each time.\n"
    "- One client failing never stops the others: each is recorded and the rest carry on.\n"
    "- Whatever failed can be re-run with one button, and only that runs again."
)

st.subheader("Built with")
st.markdown("Python and pandas, Postgres, a FastAPI service, GitHub Actions on a schedule, "
            "and Streamlit for this page.")
