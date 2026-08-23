"""
Gmail SMTP connection testing and per-user sending for the
Gmail Settings feature.
"""

import smtplib

from django.conf import settings
from django.core.mail import get_connection

from .crypto import decrypt_secret

GMAIL_SMTP_HOST = 'smtp.gmail.com'
GMAIL_SMTP_PORT = 465  # SMTP_SSL
TIMEOUT_SECONDS = 12


class SenderNotConfigured(Exception):
    """Raised when a user tries to send without a verified Gmail connection."""


def test_gmail_connection(address, app_password):
    """
    Attempt an authenticated login against Gmail's SMTP server.

    Returns (ok: bool, message: str). The password is used only for this
    call and is never logged or persisted in plaintext anywhere.
    """
    try:
        with smtplib.SMTP_SSL(GMAIL_SMTP_HOST, GMAIL_SMTP_PORT,
                              timeout=TIMEOUT_SECONDS) as server:
            server.login(address, app_password)
        return True, 'Connection successful. Gmail account is ready to send email.'
    except smtplib.SMTPAuthenticationError:
        return False, ('Gmail rejected the login. Check that the address is correct, '
                       '2-Step Verification is enabled, and you pasted a valid '
                       '16-character App Password (not your normal Gmail password).')
    except (smtplib.SMTPException, OSError) as exc:
        return False, f'Could not reach Gmail SMTP ({GMAIL_SMTP_HOST}:{GMAIL_SMTP_PORT}): {exc}'


def get_user_gmail_connection(user):
    """
    Build an SMTP connection from this user's VERIFIED Gmail settings.

    Returns (connection, gmail_address), or (None, None) when the user has
    no saved config, it is not verified, or the stored secret cannot be
    decrypted. The decrypted password lives only inside the connection
    object and is never returned or logged.
    """
    if user is None:
        return None, None
    cfg = getattr(user, 'gmail_settings', None)
    if cfg is None or not cfg.is_connected:
        return None, None
    password = decrypt_secret(cfg.app_password_encrypted)
    if not password:
        return None, None
    connection = get_connection(
        backend='django.core.mail.backends.smtp.EmailBackend',
        host=GMAIL_SMTP_HOST,
        port=GMAIL_SMTP_PORT,
        use_ssl=True,
        use_tls=False,  # SSL(465) mode; must override global EMAIL_USE_TLS
        username=cfg.gmail_address,
        password=password,
        from_email=cfg.gmail_address,
        timeout=TIMEOUT_SECONDS,
    )
    return connection, cfg.gmail_address


def resolve_sender(user):
    """
    Decide which account sends email on behalf of `user`.

    Rule: a verified per-user Gmail always wins. Otherwise ONLY the owner
    of the default env-configured account (DEFAULT_EMAIL_OWNER_USERNAME,
    e.g. kalisoftai) may send with the global credentials. Everyone else
    raises SenderNotConfigured so the UI can ask them to connect their
    own Gmail first.

    Returns (connection_or_None, from_email).
    connection is None  -> caller sends via Django's default backend.
    """
    connection, address = get_user_gmail_connection(user)
    if connection is not None:
        return connection, address

    default_from = getattr(settings, 'DEFAULT_FROM_EMAIL', '') or \
        getattr(settings, 'EMAIL_HOST_USER', '')
    display_name = getattr(settings, 'DEFAULT_FROM_NAME', '') or ''
    from_email = f"{display_name} <{default_from}>" if display_name else default_from

    username = getattr(user, 'username', None) if user is not None else None
    if username and username == getattr(settings, 'DEFAULT_EMAIL_OWNER_USERNAME', ''):
        return None, from_email

    raise SenderNotConfigured(
        'Please connect your Gmail first. Open Gmail Settings from the '
        'sidebar, add your Gmail App Password and run Test Connection until '
        'the status shows Connected. Until then, emails cannot be sent from '
        'your account.'
    )
