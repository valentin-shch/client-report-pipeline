import os
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

ENTRY = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")


@pytest.fixture
def page():
    st.cache_data.clear()
    at = AppTest.from_file(ENTRY, default_timeout=60)
    at.switch_page("app_pages/how_it_works.py")
    return at.run()


def is_diagram(value):
    # st.mermaid_chart reaches the page as a markdown element wrapping the diagram
    return "graph TD" in value or "graph LR" in value


def everything(at):
    parts = [m.value for m in at.markdown if not is_diagram(m.value)]
    parts += [c.value for c in at.caption] + [s.value for s in at.subheader]
    parts += [link.label for link in at.get("page_link")]
    return "\n".join(parts)


def test_it_needs_no_database(page, monkeypatch):
    # an explainer should load even while the database sleeps
    monkeypatch.delenv("APP_DATABASE_URL", raising=False)
    assert not page.exception
    assert page.title[0].value == "How it works"


def test_it_walks_through_the_five_monday_steps_in_order(page):
    text = everything(page)
    steps = ["Every Monday", "Pulls the week", "Cleans", "Builds", "approves"]
    positions = [text.find(s) for s in steps]
    assert all(p >= 0 for p in positions), positions
    assert positions == sorted(positions)


def test_each_step_points_at_where_to_see_it_in_the_app(page):
    links = {link.label for link in page.get("page_link")}
    assert {"Runs", "Report preview", "Alerts", "Approvals"} <= links


def test_it_explains_what_happens_when_something_breaks(page):
    text = everything(page).lower()
    assert "retried" in text
    assert "never stops the others" in text


def test_no_outside_links(page):
    assert "http" not in everything(page)


def test_the_landing_page_links_to_it():
    st.cache_data.clear()
    os.environ.pop("APP_DATABASE_URL", None)
    at = AppTest.from_file(ENTRY, default_timeout=60).run()
    assert "How it works" in [link.label for link in at.get("page_link")]


def diagram(at, direction="TD"):
    found = [m.value for m in at.markdown if f"graph {direction}" in m.value]
    return found[0][found[0].index(f"graph {direction}"):] if found else ""


def styles(at):
    return "\n".join(m.value for m in at.markdown if "<style>" in m.value)


def test_it_shows_what_runs_where(page):
    body = diagram(page)
    for part in ("GitHub Actions", "Render", "Neon", "Slack", "Streamlit", "Resend", "inbox"):
        assert part in body, part
    assert "http" not in body


def test_the_diagram_reads_top_to_bottom_for_phones(page):
    assert diagram(page).lstrip().startswith(("graph TD", "flowchart TD"))


def test_laptops_get_a_left_to_right_version_of_the_same_diagram(page):
    wide = diagram(page, "LR")
    assert wide
    for part in ("GitHub Actions", "Render", "Neon", "Slack", "Streamlit", "Resend", "inbox"):
        assert part in wide, part


def test_screen_width_decides_which_diagram_shows(page):
    css = styles(page)
    assert ".st-key-diagram-wide" in css and ".st-key-diagram-tall" in css
    assert "@media" in css


def test_step_cards_fill_a_phone_screen(page):
    css = styles(page)
    assert "st-key-step-" in css
    assert "width: 100%" in css


def test_cards_in_a_row_share_one_height(page):
    css = styles(page)
    assert "align-items: stretch" in css
