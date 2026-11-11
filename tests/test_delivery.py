import base64
import smtplib
import ssl
import threading
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx
import pytest

import delivery.__main__ as cli
import runner
from delivery import send as send_module
from delivery import slack
from delivery.mailer import SmtpMailer
from delivery.send import approve, recipients_for, retry_send, send_report
from pipeline.db import connect, read_frame

SOLMAR = "Solmar Hotels"


@pytest.fixture(autouse=True)
def plain_env(monkeypatch):
    # a local .env may set these; the tests shouldn't depend on it
    monkeypatch.delenv("DEMO_RECIPIENT", raising=False)
    monkeypatch.delenv("DAILY_SEND_CAP", raising=False)


class FakeMailer:
    def __init__(self, error=None):
        self.sent, self.error = [], error

    def send(self, to, subject, html):
        if self.error:
            raise self.error
        self.sent.append((to, subject, html))


def add_report(db, status="approved", client=SOLMAR, start=date(2025, 3, 10), claimed_at=None):
    report_id = db.execute("""
        insert into reports (client, period, period_start, period_end, theme, subject, html, status, claimed_at)
        values (%s, 'last-week', %s, %s, 'northlight', 'The subject', '<p>hi</p>', %s, %s)
        returning id""", (client, start, start + timedelta(days=6), status, claimed_at)).fetchone()[0]
    db.commit()
    return report_id


def row(db, report_id):
    db.commit()
    return read_frame(db, "select * from reports where id = %s", (report_id,)).iloc[0]


def test_approve_moves_a_pending_report_on(db):
    report = add_report(db, "pending")
    assert approve(db, report) is True
    assert row(db, report)["status"] == "approved"
    assert row(db, report)["approved_at"] is not None


def test_approving_twice_does_nothing_the_second_time(db):
    report = add_report(db, "pending")
    approve(db, report)
    assert approve(db, report) is False


def test_an_approved_report_is_sent(db):
    mailer, report = FakeMailer(), add_report(db)
    assert send_report(db, report, mailer) == "sent"
    assert mailer.sent == [(["marketing@solmar.example.com"], "The subject", "<p>hi</p>")]
    r = row(db, report)
    assert r["status"] == "sent"
    assert r["sent_at"] is not None


def test_an_unapproved_report_is_never_sent(db):
    mailer, report = FakeMailer(), add_report(db, "pending")
    assert send_report(db, report, mailer) == "not_approved"
    assert mailer.sent == []


def test_sending_twice_sends_one_email(db):
    mailer, report = FakeMailer(), add_report(db)
    send_report(db, report, mailer)
    assert send_report(db, report, mailer) == "not_approved"
    assert len(mailer.sent) == 1


def test_a_missing_report_is_said_plainly(db):
    assert send_report(db, 999_999, FakeMailer()) == "not_found"


def test_two_simultaneous_sends_produce_one_email(db, pg_url):
    mailer, report = FakeMailer(), add_report(db)
    barrier, results = threading.Barrier(2), []

    def attempt():
        with connect(pg_url) as conn:
            barrier.wait()
            results.append(send_report(conn, report, mailer))

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["not_approved", "sent"]
    assert len(mailer.sent) == 1


def test_a_report_stuck_sending_is_not_sent_again(db):
    # a crash between claim and send: a late email beats a duplicate one
    mailer, report = FakeMailer(), add_report(db, "sending")
    assert send_report(db, report, mailer) == "not_approved"
    assert retry_send(db, report, mailer) == "not_approved"
    assert mailer.sent == []
    assert row(db, report)["status"] == "sending"


def test_a_smtp_failure_is_recorded_and_can_be_retried(db):
    report = add_report(db)
    assert send_report(db, report, FakeMailer(smtplib.SMTPException("relay said no"))) == "failed"
    r = row(db, report)
    assert r["status"] == "send_failed"
    assert "relay said no" in r["error"]

    mailer = FakeMailer()
    assert retry_send(db, report, mailer) == "sent"
    assert len(mailer.sent) == 1
    assert row(db, report)["error"] is None


def test_a_connection_failure_counts_as_a_failed_send(db):
    report = add_report(db)
    assert send_report(db, report, FakeMailer(OSError("no route"))) == "failed"


@pytest.mark.parametrize("error", [ValueError("bad header"), UnicodeEncodeError("ascii", "ñ", 0, 1, "no")],
                         ids=["value-error", "unicode-error"])
def test_an_unexpected_mail_error_never_leaves_a_report_stuck(db, error):
    report = add_report(db)
    assert send_report(db, report, FakeMailer(error)) == "failed"
    r = row(db, report)
    assert r["status"] == "send_failed"
    assert r["error"]
    assert retry_send(db, report, FakeMailer()) == "sent"


def test_the_sent_content_is_what_was_claimed(db, monkeypatch):
    mailer, report = FakeMailer(), add_report(db)
    real = send_module.recipients_for

    def rebuilt_meanwhile(client):
        db.execute("update reports set html = '<p>rebuilt</p>' where id = %s", (report,))
        db.commit()
        return real(client)
    monkeypatch.setattr(send_module, "recipients_for", rebuilt_meanwhile)

    send_report(db, report, mailer)
    assert mailer.sent[0][2] == "<p>rebuilt</p>"


def test_finishing_a_send_cannot_overwrite_a_row_that_moved_on(db, pg_url):
    report = add_report(db)

    class Interrupted(FakeMailer):
        def send(self, to, subject, html):
            with connect(pg_url) as other:
                other.execute("update reports set status = 'pending' where id = %s", (report,))

    send_report(db, report, Interrupted())
    assert row(db, report)["status"] == "pending"


def test_the_cap_holds_when_sends_race(db, pg_url):
    for attempt in range(5):
        db.execute("truncate reports")
        db.commit()
        reports = [add_report(db, client=c) for c in (SOLMAR, "Nordfit Equipment", "Clinica Vantia")]
        mailer, barrier, results = FakeMailer(), threading.Barrier(3), []

        def send(report):
            with connect(pg_url) as conn:
                barrier.wait()
                results.append(send_report(conn, report, mailer, cap=1))

        threads = [threading.Thread(target=send, args=(r,)) for r in reports]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(results) == ["cap_reached", "cap_reached", "sent"]
        assert len(mailer.sent) == 1


def test_the_daily_cap_stops_sending_and_leaves_the_report_approved(db):
    now = datetime.now(timezone.utc)
    add_report(db, "sent", client="A", claimed_at=now)
    add_report(db, "sending", client="B", claimed_at=now)
    mailer, report = FakeMailer(), add_report(db)
    assert send_report(db, report, mailer, cap=2) == "cap_reached"
    assert mailer.sent == []
    assert row(db, report)["status"] == "approved"


def test_yesterdays_sends_and_failed_sends_do_not_count_towards_the_cap(db):
    add_report(db, "sent", client="A", claimed_at=datetime.now(timezone.utc) - timedelta(days=2))
    add_report(db, "send_failed", client="B", claimed_at=datetime.now(timezone.utc))
    report = add_report(db)
    assert send_report(db, report, FakeMailer(), cap=1) == "sent"


def test_the_cap_comes_from_the_environment(db, monkeypatch):
    monkeypatch.setenv("DAILY_SEND_CAP", "0")
    assert send_report(db, add_report(db), FakeMailer()) == "cap_reached"


def test_recipients_come_from_the_client_config(monkeypatch):
    monkeypatch.delenv("DEMO_RECIPIENT", raising=False)
    assert recipients_for(SOLMAR) == ["marketing@solmar.example.com"]


def test_demo_recipient_replaces_every_address(monkeypatch):
    monkeypatch.setenv("DEMO_RECIPIENT", "me@example.org")
    assert recipients_for(SOLMAR) == ["me@example.org"]


def test_an_unknown_client_is_refused_without_claiming_the_report(db):
    report = add_report(db, client="Nobody Ltd")
    assert send_report(db, report, FakeMailer()) == "no_recipients"
    assert row(db, report)["status"] == "approved"


def test_approving_what_was_previewed(db):
    report = add_report(db, "pending")
    run_id = add_run_for(db, report)
    assert approve(db, report, run_id) is True


def test_a_report_rebuilt_since_the_preview_is_not_approved(db):
    report = add_report(db, "pending")
    seen = add_run_for(db, report)
    add_run_for(db, report)  # a re-run rebuilt it after the visitor looked
    assert approve(db, report, seen) is False
    assert row(db, report)["status"] == "pending"


def add_run_for(db, report_id):
    run_id = db.execute("""
        insert into runs (client, period, anchor, period_start, period_end, trigger, status)
        values ('Solmar Hotels', 'last-week', '2025-03-19', '2025-03-10', '2025-03-16', 'manual', 'succeeded')
        returning id""").fetchone()[0]
    db.execute("update reports set run_id = %s where id = %s", (run_id, report_id))
    db.commit()
    return run_id


def test_the_app_role_can_approve_and_send(db):
    report = add_report(db, "pending")
    db.execute("set role app")
    db.commit()
    assert approve(db, report) is True
    assert send_report(db, report, FakeMailer()) == "sent"


class StubSmtp:
    calls = []
    error = None
    quit_error = None

    def __init__(self, host, port, timeout):
        StubSmtp.calls = [("connect", host, port)]

    def starttls(self, context=None):
        StubSmtp.calls.append(("starttls", context))

    def quit(self):
        StubSmtp.calls.append(("quit",))
        if StubSmtp.quit_error:
            raise StubSmtp.quit_error

    def close(self):
        StubSmtp.calls.append(("close",))

    def login(self, user, password):
        if StubSmtp.error:
            raise StubSmtp.error
        StubSmtp.calls.append(("login", user))

    def send_message(self, message):
        StubSmtp.calls.append(("send", message))


def smtp_env(monkeypatch, **overrides):
    env = {"SMTP_HOST": "mail.test", "SMTP_PORT": "587", "SMTP_FROM": "reports@example.com",
           "SMTP_USER": "user", "SMTP_PASSWORD": "pw-secret", "SMTP_TLS": "on", **overrides}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    StubSmtp.error = StubSmtp.quit_error = None
    StubSmtp.calls = []


def sent_message():
    return next(c[1] for c in StubSmtp.calls if c[0] == "send")


def test_mailer_verifies_the_servers_certificate(monkeypatch):
    # plain starttls() accepts any certificate, and the password goes next
    smtp_env(monkeypatch)
    SmtpMailer.from_env(smtp=StubSmtp).send(["a@example.org"], "S", "<p>h</p>")
    context = next(c[1] for c in StubSmtp.calls if c[0] == "starttls")
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_mailer_sets_the_headers_mail_providers_expect(monkeypatch):
    smtp_env(monkeypatch)
    SmtpMailer.from_env(smtp=StubSmtp).send(["a@example.org"], "S", "<p>h</p>")
    message = sent_message()
    assert parsedate_to_datetime(message["Date"]) is not None
    assert message["Message-ID"].endswith("@example.com>")


@pytest.mark.parametrize("error", [smtplib.SMTPResponseException(421, b"bye"), OSError("reset")],
                         ids=["bad-reply", "dropped"])
def test_a_failure_after_the_server_took_the_message_is_not_a_failure(monkeypatch, error):
    # reporting this as failed would make a retry send the email twice
    smtp_env(monkeypatch)
    StubSmtp.quit_error = error
    SmtpMailer.from_env(smtp=StubSmtp).send(["a@example.org"], "S", "<p>h</p>")
    assert sent_message() is not None


def test_a_failure_before_sending_closes_the_connection_and_raises(monkeypatch):
    smtp_env(monkeypatch)
    StubSmtp.error = smtplib.SMTPAuthenticationError(535, b"no")
    with pytest.raises(smtplib.SMTPAuthenticationError):
        SmtpMailer.from_env(smtp=StubSmtp).send(["a@example.org"], "S", "<p>h</p>")
    assert StubSmtp.calls[-1] == ("close",)


def test_mailer_uses_tls_and_logs_in(monkeypatch):
    smtp_env(monkeypatch)
    SmtpMailer.from_env(smtp=StubSmtp).send(["a@example.org"], "Subject", "<p>hi</p>")
    assert [c[0] for c in StubSmtp.calls] == ["connect", "starttls", "login", "send", "quit"]
    message = sent_message()
    assert message["To"] == "a@example.org"
    assert message["From"] == "reports@example.com"
    assert message["Subject"] == "Subject"
    assert message.get_body(("html",)).get_content().strip() == "<p>hi</p>"
    assert "HTML" in message.get_body(("plain",)).get_content()


def test_mailer_without_tls_or_login_for_a_local_inbox(monkeypatch):
    smtp_env(monkeypatch, SMTP_TLS="off", SMTP_USER="", SMTP_PASSWORD="")
    SmtpMailer.from_env(smtp=StubSmtp).send(["a@example.org"], "S", "<p>h</p>")
    assert [c[0] for c in StubSmtp.calls] == ["connect", "send", "quit"]


def test_mailer_sends_images_as_inline_attachments(monkeypatch):
    # Gmail and Outlook don't show data: URIs, so a base64 image in the HTML
    # would arrive broken. They do show cid: attachments.
    png = base64.b64encode(b"png-one").decode()
    other = base64.b64encode(b"png-two").decode()
    html = f'<img src="data:image/png;base64,{png}" alt="a"><img alt="b" src="data:image/png;base64,{other}">'
    smtp_env(monkeypatch)
    SmtpMailer.from_env(smtp=StubSmtp).send(["a@example.org"], "S", html)

    message = sent_message()
    body = message.get_body(("html",)).get_content()
    assert "data:image" not in body
    assert body.count("cid:") == 2

    inline = [part for part in message.walk() if part.get_content_maintype() == "image"]
    assert [part.get_content() for part in inline] == [b"png-one", b"png-two"]
    for part in inline:
        assert f'cid:{part["Content-ID"].strip("<>")}' in body
        assert part.get_content_disposition() == "inline"


def test_mailer_needs_a_host_and_a_from_address(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    with pytest.raises(RuntimeError, match="SMTP_HOST"):
        SmtpMailer.from_env()


def test_a_failed_login_stores_no_password(db, monkeypatch):
    smtp_env(monkeypatch)
    StubSmtp.error = smtplib.SMTPAuthenticationError(535, b"bad credentials")
    report = add_report(db)
    assert send_report(db, report, SmtpMailer.from_env(smtp=StubSmtp)) == "failed"
    assert "pw-secret" not in row(db, report)["error"]


def good(slug="solmar-hotels", alerts=1):
    return runner.RunResult(slug, "succeeded", None, "created", alerts)


def test_summary_counts_reports_alerts_and_failures():
    text = slack.summary_text([
        good(alerts=2), good("nordfit-equipment", alerts=0),
        runner.RunResult("clinica-vantia", "failed", "PermanentError: HTTP 401"),
    ])
    assert "2 reports ready" in text
    assert "1 failed" in text
    assert "2 alerts" in text
    assert "clinica-vantia" in text and "HTTP 401" in text
    assert "--retry-failed" in text


def test_a_clean_summary_has_no_retry_hint():
    assert "--retry-failed" not in slack.summary_text([good()])


def test_no_webhook_means_no_post(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    calls = []
    assert slack.post_summary([good()], post=lambda *a, **k: calls.append(a)) is False
    assert calls == []


def test_summary_is_posted_to_the_webhook(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "http://hooks.test/x")
    seen = {}

    def post(url, json, timeout):
        seen.update(url=url, json=json)
        return httpx.Response(200, request=httpx.Request("POST", url))
    assert slack.post_summary([good()], post=post) is True
    assert seen["url"] == "http://hooks.test/x"
    assert "1 report ready" in seen["json"]["text"]


@pytest.mark.parametrize("outcome", ["http-500", "network"])
def test_a_failed_post_never_raises(monkeypatch, capsys, outcome):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "http://hooks.test/secret-path")

    def post(url, json, timeout):
        if outcome == "network":
            raise httpx.ConnectError("no route")
        return httpx.Response(500, request=httpx.Request("POST", url))
    assert slack.post_summary([good()], post=post) is False
    assert "secret-path" not in capsys.readouterr().out


def test_a_malformed_webhook_url_never_raises(monkeypatch, capsys):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "http://hooks.test/secret-path\n")
    assert slack.post_summary([good()]) is False
    assert "secret-path" not in capsys.readouterr().out


def test_runner_posts_its_summary_and_a_failed_post_changes_nothing(db, pg_url, monkeypatch):
    results = []
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setattr(runner.AdsApi, "from_env", classmethod(lambda cls: type("A", (), {"retries": 0})()))
    monkeypatch.setattr(runner, "run_all", lambda *a: [good()])
    monkeypatch.setattr(runner, "post_summary", lambda r: results.append(r) or False)
    assert runner.main(["--client", "solmar-hotels"]) == 0
    assert len(results) == 1


def test_cli_lists_approves_and_sends(db, pg_url, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", pg_url)
    mailer = FakeMailer()
    monkeypatch.setattr(cli.SmtpMailer, "from_env", classmethod(lambda cls: mailer))
    report = add_report(db, "pending")

    assert cli.main(["list"]) == 0
    assert "pending" in capsys.readouterr().out
    assert cli.main(["approve", str(report)]) == 0
    assert cli.main(["send", str(report)]) == 0
    assert cli.main(["send", str(report)]) == 1
    assert "not_approved" in capsys.readouterr().out
    assert len(mailer.sent) == 1


def test_a_real_mail_server_refuses_placeholder_addresses(monkeypatch):
    # clients.toml uses example.com because the repo is public; on a real server a
    # missing DEMO_RECIPIENT should fail loudly, not bounce
    smtp_env(monkeypatch, SMTP_HOST="smtp.resend.com")
    with pytest.raises(ValueError, match="DEMO_RECIPIENT"):
        SmtpMailer.from_env(smtp=StubSmtp).send(["marketing@solmar.example.com"], "S", "<p>h</p>")
    assert not any(c[0] == "send" for c in StubSmtp.calls)


def test_a_local_inbox_accepts_placeholder_addresses(monkeypatch):
    smtp_env(monkeypatch, SMTP_HOST="127.0.0.1", SMTP_TLS="off", SMTP_USER="", SMTP_PASSWORD="")
    SmtpMailer.from_env(smtp=StubSmtp).send(["marketing@solmar.example.com"], "S", "<p>h</p>")
    assert sent_message()["To"] == "marketing@solmar.example.com"


def test_a_refused_placeholder_send_is_recorded_as_failed(db, monkeypatch):
    smtp_env(monkeypatch, SMTP_HOST="smtp.resend.com")
    report = add_report(db)
    assert send_report(db, report, SmtpMailer.from_env(smtp=StubSmtp)) == "failed"
    assert "DEMO_RECIPIENT" in row(db, report)["error"]
