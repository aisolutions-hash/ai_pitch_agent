"""
Encrypted-at-rest helpers for storing secrets (e.g., Gmail App Passwords).

The Fernet key is derived from Django's SECRET_KEY, so ciphertexts stay
valid across restarts as long as SECRET_KEY is unchanged. Secrets are
never exposed by any API or template.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet():
    digest = hashlib.sha256(settings.SECRET_KEY.encode('utf-8')).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext):
    """Encrypt a string. Returns ciphertext (str)."""
    return _fernet().encrypt(plaintext.encode('utf-8')).decode('ascii')


def decrypt_secret(ciphertext):
    """
    Decrypt a stored ciphertext back to plaintext.
    Returns None if the token is invalid/corrupt (e.g., SECRET_KEY changed).
    """
    try:
        return _fernet().decrypt(ciphertext.encode('ascii')).decode('utf-8')
    except (InvalidToken, ValueError):
        return None


def mask_secret(plaintext):
    """Human-safe representation used in UI/logs — never the real value."""
    if not plaintext:
        return ''
    return '\u2022' * min(len(plaintext), 16)
