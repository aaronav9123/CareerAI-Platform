"""
mailer.py
---------
Sends verification / password-reset emails over SMTP.

If SMTP isn't configured (no SMTP_HOST in .env) nothing is sent: the message is
printed to the terminal instead so the app is fully usable on a laptop for a
demo. app.py additionally shows the link on screen in that case, but only for
requests coming from localhost.
"""

import smtplib
from email.message import EmailMessage

from config import env


def configured():
    return bool(env("SMTP_HOST"))


def send(to, subject, body):
    """Returns True if an email was actually sent, False if it was only logged."""
    if not configured():
        print(f"\n[mailer] SMTP not configured - would send to {to}\n  Subject: {subject}\n{body}\n")
        return False

    msg = EmailMessage()
    msg["From"] = env("MAIL_FROM", env("SMTP_USER", "no-reply@careerai.local"))
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    host = env("SMTP_HOST")
    port = int(env("SMTP_PORT", "587"))
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            server = smtplib.SMTP(host, port, timeout=15)
            server.starttls()
        with server:
            if env("SMTP_USER"):
                server.login(env("SMTP_USER"), env("SMTP_PASSWORD", ""))
            server.send_message(msg)
        return True
    except Exception as e:
        print("[mailer] sending failed:", e)
        return False
