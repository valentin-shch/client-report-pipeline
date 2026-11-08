import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from delivery.mailer import SmtpMailer

ENTRY = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")
PASSCODE = "open-sesame"


class FakeMailer:
    sent = []

    def send(self, to, subject, html):
        FakeMailer.sent.append((to, subject))


@pytest.fixture
def app_env(db, monkeypatch):
    url = os.environ.get("TEST_APP_DATABASE_URL")
    if not url:
        pytest.skip("TEST_APP_DATABASE_URL is not set")
    st.cache_data.clear()
    FakeMailer.sent = []
    monkeypatch.setenv("APP_DATABASE_URL", url)
    monkeypatch.setenv("APPROVAL_PASSCODE", PASSCODE)
    monkeypatch.delenv("DEMO_RECIPIENT", raising=False)
    monkeypatch.delenv("DAILY_SEND_CAP", raising=False)
    monkeypatch.setattr(SmtpMailer, "from_env", classmethod(lambda cls: FakeMailer()))
    return url


def add_report(db, status="pending", error=None, client="Solmar Hotels"):
    run_id = db.execute("""
        insert into runs (client, period, anchor, period_start, period_end, trigger, status)
        values (%s, 'last-week', '2025-03-19', '2025-03-10', '2025-03-16', 'schedule', 'succeeded')
        returning id""", (client,)).fetchone()[0]
    report_id = db.execute("""
        insert into reports (run_id, client, period, period_start, period_end, theme, subject, html,
                             status, error, alerts)
        values (%s, %s, 'last-week', '2025-03-10', '2025-03-16', 'northlight', %s, '<p>hi</p>', %s, %s,
                '[{"headline": "x"}]')
        returning id""", (run_id, client, f"{client}: Week of 10-16 Mar 2025", status, error)).fetchone()[0]
    db.commit()
    return report_id


def status(db, report_id):
    db.commit()
    return db.execute("select status from reports where id = %s", (report_id,)).fetchone()[0]


def open_page():
    at = AppTest.from_file(ENTRY, default_timeout=60)
    at.switch_page("app_pages/approvals.py")
    return at.run()


def unlock(at, code=PASSCODE):
    at.text_input(key="passcode").input(code)
    return at.button(key="unlock").click().run()


def shown(at):
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption] + [s.value for s in at.subheader]
    for kind in (at.info, at.warning, at.error, at.success):
        parts += [e.value for e in kind]
    return "\n".join(parts)


def test_visitors_see_the_queue_but_cannot_send(db, app_env):
    report = add_report(db)
    at = open_page()
    assert not at.exception
    assert at.title[0].value == "Approvals"
    assert "Solmar Hotels: Week of 10-16 Mar 2025" in shown(at)
    assert "restricted" in shown(at)
    assert at.button(key=f"send-{report}").disabled


def test_a_wrong_passcode_is_refused_and_recorded(db, app_env):
    report = add_report(db)
    at = unlock(open_page(), "nope")
    assert "Wrong passcode" in shown(at)
    assert at.button(key=f"send-{report}").disabled
    assert db.execute("select count(*) from approval_attempts where not ok").fetchone()[0] == 1


def record_failures(db, n, hours_ago=0):
    at = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    for _ in range(n):
        db.execute("insert into approval_attempts (at, ok) values (%s, false)", (at,))
    db.commit()


def test_five_wrong_tries_lock_everyone_out_even_with_the_right_passcode(db, app_env):
    report = add_report(db)
    record_failures(db, 5)
    at = unlock(open_page())
    assert "locked" in shown(at).lower()
    assert at.button(key=f"send-{report}").disabled


def test_old_failures_do_not_lock(db, app_env):
    report = add_report(db)
    record_failures(db, 5, hours_ago=2)
    at = unlock(open_page())
    assert not at.button(key=f"send-{report}").disabled


def test_approve_and_send(db, app_env):
    report = add_report(db)
    at = unlock(open_page())
    at = at.button(key=f"send-{report}").click().run()
    assert not at.exception
    assert status(db, report) == "sent"
    assert len(FakeMailer.sent) == 1
    assert "Sent" in shown(at)


def test_a_report_rebuilt_since_it_was_opened_is_not_sent(db, app_env):
    report = add_report(db)
    at = unlock(open_page())
    newer = db.execute("""insert into runs (client, period, anchor, period_start, period_end, trigger, status)
                          values ('Solmar Hotels', 'last-week', '2025-03-19', '2025-03-10', '2025-03-16',
                                  'manual', 'succeeded') returning id""").fetchone()[0]
    db.execute("update reports set run_id = %s, html = '<p>rebuilt</p>' where id = %s", (newer, report))
    db.commit()
    at = at.button(key=f"send-{report}").click().run()
    assert "changed since you opened" in shown(at)
    assert status(db, report) == "pending"
    assert FakeMailer.sent == []


def test_a_failed_send_shows_its_type_only_and_can_be_retried(db, app_env):
    report = add_report(db, "send_failed", error="SMTPRecipientsRefused: owner@private.example refused")
    at = open_page()
    assert "SMTPRecipientsRefused" in shown(at)
    assert "owner@private.example" not in shown(at)
    at = unlock(at)
    at = at.button(key=f"retry-{report}").click().run()
    assert status(db, report) == "sent"
    assert len(FakeMailer.sent) == 1


def test_a_report_stuck_mid_send_is_explained_and_has_no_button(db, app_env):
    report = add_report(db, "sending")
    at = unlock(open_page())
    assert "check the inbox" in shown(at)
    keys = [b.key for b in at.button]
    assert f"send-{report}" not in keys and f"retry-{report}" not in keys


def test_without_mail_settings_nothing_is_approved(db, app_env, monkeypatch):
    def no_mail(cls):
        raise RuntimeError("SMTP_HOST and SMTP_FROM must both be set")
    monkeypatch.setattr(SmtpMailer, "from_env", classmethod(no_mail))
    report = add_report(db)
    at = unlock(open_page())
    at = at.button(key=f"send-{report}").click().run()
    assert "isn't set up" in shown(at)
    assert status(db, report) == "pending"


def test_without_a_passcode_configured_approvals_are_off(db, app_env, monkeypatch):
    monkeypatch.delenv("APPROVAL_PASSCODE")
    report = add_report(db)
    at = open_page()
    assert "turned off" in shown(at)
    assert not [t for t in at.text_input if t.key == "passcode"]
    assert at.button(key=f"send-{report}").disabled


def test_nothing_waiting_is_said_plainly(db, app_env):
    at = open_page()
    assert not at.exception
    assert "Nothing waiting" in shown(at)


def test_recent_shows_the_latest_send_first(db, app_env):
    first = add_report(db, "sent", client="Clinica Vantia")
    second = add_report(db, "sent", client="Nordfit Equipment")
    db.execute("update reports set sent_at = now() - interval '2 days' where id = %s", (second,))
    db.execute("update reports set sent_at = now() where id = %s", (first,))
    db.commit()
    subjects = [m.value for m in open_page().markdown if m.value.startswith("**") and "Week of" in m.value]
    assert subjects[0].startswith("**Clinica Vantia")
