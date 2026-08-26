import imaplib
import smtplib
from email.header import decode_header
from email.mime.text import MIMEText

from app.core.config import get_settings
from app.tools.base import ToolResult, tool


def _credentials():
    settings = get_settings()
    if not settings.email_address or not settings.email_app_password:
        raise ValueError("Email is not configured. Set EMAIL_ADDRESS and EMAIL_APP_PASSWORD.")
    return settings.email_address, settings.email_app_password


@tool(
    name="check_unread_emails",
    description="Reads the latest unread emails from the configured Gmail inbox and summarizes them.",
)
def check_unread_emails(limit: int = 5) -> ToolResult:
    try:
        addr, pwd = _credentials()
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(addr, pwd)
        mail.select("inbox")
        status, messages = mail.search(None, "UNSEEN")
        if status != "OK":
            return ToolResult(success=False, message="Could not search the inbox.")

        ids = messages[0].split()
        if not ids:
            return ToolResult(success=True, message="You have no unread emails.")

        lines = []
        for e_id in ids[-limit:]:
            _, msg_data = mail.fetch(e_id, "(BODY[HEADER.FIELDS (SUBJECT FROM)])")
            for part in msg_data:
                if isinstance(part, tuple):
                    raw = part[1]
                    subject_raw = decode_header(
                        raw.split(b"Subject: ")[-1].split(b"\r\n")[0].decode("utf-8", "ignore")
                    )
                    subject = "".join(
                        s.decode(enc or "utf-8", "ignore") if isinstance(s, bytes) else s
                        for s, enc in [subject_raw[0]]
                    )
                    from_line = raw.split(b"From: ")[1].split(b"\r\n")[0].decode("utf-8", "ignore")
                    lines.append(f"- From {from_line}: {subject}")
        mail.logout()

        if not lines:
            return ToolResult(success=True, message="You have no unread emails.")
        total = len(ids)
        return ToolResult(
            success=True,
            message=f"You have {total} unread email{'s' if total != 1 else ''}. Latest:\n" + "\n".join(lines),
        )
    except ValueError as exc:
        return ToolResult(success=False, message=str(exc))
    except Exception as exc:
        return ToolResult(success=False, message=f"Email check failed: {exc}")


@tool(
    name="send_email",
    description=(
        "Sends a plain-text email via Gmail SMTP. Requires user confirmation before sending."
    ),
    permission="CONFIRM",
    confirm_verb="send an email",
)
def send_email(to_address: str, subject: str, body: str) -> ToolResult:
    try:
        addr, pwd = _credentials()
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = addr
        msg["To"] = to_address
        msg["Subject"] = subject

        server = smtplib.SMTP("smtp.gmail.com", 587, timeout=20)
        server.starttls()
        server.login(addr, pwd)
        server.sendmail(addr, to_address, msg.as_string())
        server.quit()
        return ToolResult(success=True, message=f"Email sent to {to_address}.")
    except ValueError as exc:
        return ToolResult(success=False, message=str(exc))
    except Exception as exc:
        return ToolResult(success=False, message=f"Sending failed: {exc}")
