"""
Central resolver for Google service-account credentials.

Resolution order:
1. Key file on disk (settings.GOOGLE_CREDENTIALS_FILE or settings.GCS_KEY_PATH)
   - typical local development setup.
2. Raw service-account JSON from env vars GOOGLE_CREDENTIALS_JSON /
   GCS_CREDENTIALS_JSON - used in containers (Cloud Run, Docker) where key
   files are deliberately NOT baked into the image.
3. Falls back to Application Default Credentials (ADC) - e.g. Cloud Run's
   attached runtime service account.

Returns None only when nothing can be resolved; callers decide how to fail.
"""

import json
import logging
import os

from django.conf import settings

logger = logging.getLogger(__name__)

_JSON_ENV_VARS = ('GOOGLE_CREDENTIALS_JSON', 'GCS_CREDENTIALS_JSON')


def _existing_key_files():
    paths = []
    for attr in ('GOOGLE_CREDENTIALS_FILE', 'GCS_KEY_PATH'):
        path = getattr(settings, attr, '') or ''
        if path and os.path.exists(path):
            paths.append(path)
    return paths


def load_credentials(scopes=None):
    """
    Return explicit service-account Credentials, or None when no explicit
    source is available (caller should then use ADC).
    """
    from google.oauth2 import service_account

    for path in _existing_key_files():
        try:
            creds = service_account.Credentials.from_service_account_file(path)
            if scopes:
                creds = creds.with_scopes(scopes)
            logger.debug('Google credentials loaded from key file: %s', path)
            return creds
        except Exception:
            logger.exception('Could not load Google key file: %s', path)

    for var in _JSON_ENV_VARS:
        raw = os.getenv(var, '')
        if raw.strip():
            try:
                info = json.loads(raw)
                creds = service_account.Credentials.from_service_account_info(info)
                if scopes:
                    creds = creds.with_scopes(scopes)
                logger.debug('Google credentials loaded from env var: %s', var)
                return creds
            except Exception:
                logger.exception('Could not parse Google credentials from env var: %s', var)

    return None


def default_or_loaded(scopes=None):
    """
    Explicit credentials when configured, otherwise Application Default
    Credentials. Raises google.auth.exceptions.DefaultCredentialsError when
    nothing is available - same contract the call sites had before.
    """
    creds = load_credentials(scopes)
    if creds is not None:
        return creds
    import google.auth
    creds, _ = google.auth.default(scopes=scopes)
    return creds
