import logging
import ssl
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from urllib.parse import urlencode

from app.core.config import get_settings


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailSendStatus:
    sent: bool
    reason: str


def send_email(to_email: str, subject: str, body: str) -> EmailSendStatus:
    settings = get_settings()
    if not settings.mail_enabled:
        logger.info("Mail disabled; skipped email to %s with subject %s.", to_email, subject)
        return EmailSendStatus(sent=False, reason="mail_disabled")

    if not settings.mail_from or not settings.mail_server:
        logger.warning("Mail enabled but MAIL_FROM or MAIL_SERVER is not configured.")
        return EmailSendStatus(sent=False, reason="missing_mail_settings")

    message = EmailMessage()
    message["From"] = settings.mail_from
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    try:
        with smtplib.SMTP(settings.mail_server, settings.mail_port, timeout=20) as smtp:
            smtp.ehlo()
            if settings.mail_use_tls:
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            if settings.mail_username and settings.mail_password:
                smtp.login(settings.mail_username, settings.mail_password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        logger.warning(
            "Failed to send email to %s with subject %s: %s",
            to_email,
            subject,
            exc.__class__.__name__,
        )
        return EmailSendStatus(sent=False, reason="send_failed")

    return EmailSendStatus(sent=True, reason="sent")


def build_verification_email(to_email: str, token: str) -> tuple[str, str]:
    settings = get_settings()
    verification_url = (
        f"{settings.frontend_base_url.rstrip('/')}/verify-email?"
        f"{urlencode({'token': token})}"
    )
    subject = "Verify your email address"
    body = (
        f"Hello,\n\n"
        f"Please verify your email address for {to_email} by opening this link:\n"
        f"{verification_url}\n\n"
        f"If you did not request this, you can ignore this email."
    )
    return subject, body


def build_password_reset_email(to_email: str, token: str) -> tuple[str, str]:
    settings = get_settings()
    reset_url = (
        f"{settings.frontend_base_url.rstrip('/')}/reset-password?"
        f"{urlencode({'token': token})}"
    )
    subject = "Reset your password"
    body = (
        f"Hello,\n\n"
        f"Please reset the password for {to_email} by opening this link:\n"
        f"{reset_url}\n\n"
        f"If you did not request this, you can ignore this email."
    )
    return subject, body
