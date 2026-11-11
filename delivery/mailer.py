from __future__ import annotations

import base64
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

PLAIN_FALLBACK = "This report is an HTML email. Please open it in a client that shows HTML."
DATA_IMAGE = re.compile(r'src="data:image/(\w+);base64,([^"]+)"')


def inline_images(html: str) -> tuple[str, list[tuple[str, str, bytes]]]:
    """Reports carry their images as data: URIs so the HTML is self-contained,
    but Gmail and Outlook won't show those, and they count towards Gmail's 102 KB
    clipping limit. As cid: attachments they show, and don't."""
    images = []

    def to_cid(match: re.Match) -> str:
        cid = f"image{len(images)}@report"
        images.append((cid, match[1], base64.b64decode(match[2])))
        return f'src="cid:{cid}"'
    return DATA_IMAGE.sub(to_cid, html), images


class SmtpMailer:
    def __init__(self, host: str, port: int, sender: str, user: str, password: str,
                 tls: bool, smtp=smtplib.SMTP):
        self.host, self.port, self.sender = host, port, sender
        self.user, self.password, self.tls, self.smtp = user, password, tls, smtp

    @classmethod
    def from_env(cls, smtp=smtplib.SMTP) -> "SmtpMailer":
        host, sender = os.environ.get("SMTP_HOST"), os.environ.get("SMTP_FROM")
        if not host or not sender:
            raise RuntimeError("SMTP_HOST and SMTP_FROM must both be set")
        return cls(host, int(os.environ.get("SMTP_PORT", "587")), sender,
                   os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASSWORD", ""),
                   os.environ.get("SMTP_TLS", "on") != "off", smtp)

    def send(self, to: list[str], subject: str, html: str) -> None:
        # clients.toml holds example.com addresses because the repo is public.
        # Through a real server they'd only bounce, so a deployment that forgot
        # DEMO_RECIPIENT fails here, visibly, instead.
        placeholders = [a for a in to if a.lower().endswith("example.com")]
        if placeholders and self.host not in ("127.0.0.1", "localhost"):
            raise ValueError("placeholder recipient on a real mail server; set DEMO_RECIPIENT")
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = self.sender, ", ".join(to), subject
        message["Date"] = formatdate()
        message["Message-ID"] = make_msgid(domain=self.sender.rsplit("@", 1)[-1])
        message.set_content(PLAIN_FALLBACK)
        body, images = inline_images(html)
        message.add_alternative(body, subtype="html")
        html_part = message.get_body(("html",))
        for cid, subtype, data in images:
            html_part.add_related(data, "image", subtype, cid=f"<{cid}>", disposition="inline")
        server = self.smtp(self.host, self.port, timeout=30)
        try:
            if self.tls:
                # Bare starttls() accepts any certificate, and the password is next.
                server.starttls(context=ssl.create_default_context())
            if self.user:
                server.login(self.user, self.password)
            server.send_message(message)
        except Exception:
            server.close()
            raise
        # The server has the message now. A bad goodbye mustn't read as a failed
        # send, or a retry emails it twice. (`with` would raise here.)
        try:
            server.quit()
        except (smtplib.SMTPException, OSError):
            server.close()
