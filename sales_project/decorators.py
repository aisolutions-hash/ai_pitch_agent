"""
Role-style access control decorators.

owner_required: restricts a view to the single application owner account
(settings.DEFAULT_EMAIL_OWNER_USERNAME, default 'kalisoftai'). Everyone else
gets the friendly branded 403 response - no information about the feature is
leaked, and behavior is identical in DEBUG and production.
"""

import logging
from functools import wraps

from django.conf import settings

logger = logging.getLogger(__name__)


def is_app_owner(user):
    return bool(
        user
        and user.is_authenticated
        and user.username == getattr(settings, 'DEFAULT_EMAIL_OWNER_USERNAME', 'kalisoftai')
    )


def owner_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not is_app_owner(request.user):
            logger.warning(
                'Owner-only feature blocked for user=%r path=%s',
                getattr(request.user, 'username', None), request.path_info,
            )
            from sales_project.error_handlers import friendly_error
            return friendly_error(request, 403)
        return view_func(request, *args, **kwargs)
    return _wrapped
