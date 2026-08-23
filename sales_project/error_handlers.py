"""
Friendly, user-facing error responses for the whole application.

Real technical details are never shown to users - they are logged
server-side so our team can investigate. Users only see a clean
reassurance that the issue will be fixed.
"""

import logging

from django.http import JsonResponse
from django.shortcuts import render

logger = logging.getLogger(__name__)

# Endpoints consumed by frontend fetch() calls -> answer with JSON so the
# existing toast/alert UI keeps working.
JSON_API_PREFIXES = (
    '/app/api/',
    '/app/scraper/',
    '/app/pitch/',
    '/app/search/',
    '/pitch/mark-opened/',
)

# Exact paths that are real HTML pages (must NOT be treated as APIs even
# though they share prefixes with endpoint groups above).
HTML_PAGE_PATHS = {
    '/',
    '/app/',
    '/app/gmail-settings/',
    '/app/scraper/',
    '/app/search/',
    '/app/pitch/',
    '/app/pitch/dashboard/',
    '/app/generator/create/',
}

MESSAGES = {
    400: {
        'title': 'Bad Request',
        'detail': 'Your browser sent a request we could not understand. '
                  'If this keeps happening, our team will be happy to help.',
    },
    403: {
        'title': 'Access Denied',
        'detail': 'You do not have permission to access this resource. '
                  'If you believe this is a mistake, please contact our team.',
    },
    404: {
        'title': 'Page Not Found',
        'detail': "We could not find the page you were looking for. "
                  "It may have been moved or no longer exists.",
    },
    500: {
        'title': 'Something Went Wrong',
        'detail': 'An unexpected error occurred on our side. Our technical '
                  'team has been notified and will resolve this issue as '
                  'soon as possible. Please try again in a little while.',
    },
}


def _wants_json(request):
    """Decide whether this client expects a JSON error payload."""
    path = request.path_info
    if path in HTML_PAGE_PATHS:
        return False
    if path.startswith(JSON_API_PREFIXES):
        return True
    headers = getattr(request, 'headers', {})
    accept = headers.get('Accept', '') or ''
    content_type = headers.get('Content-Type', '') or ''
    return 'application/json' in accept or 'application/json' in content_type


def friendly_error(request, status_code=500):
    """
    Build a branded, reassuring error response. Never leaks stack traces,
    exception names, or internal details to the end user.
    """
    meta = MESSAGES.get(status_code, MESSAGES[500])
    if _wants_json(request):
        return JsonResponse(
            {
                'success': False,
                'error': meta['detail'],
                'status_code': status_code,
            },
            status=status_code,
        )
    return render(
        request,
        'errors/friendly.html',
        {
            'status_code': status_code,
            'error_title': meta['title'],
            'error_detail': meta['detail'],
        },
        status=status_code,
    )


# --- Django standard error handler hooks ---

def bad_request(request, exception=None):
    logger.warning('Bad request at %s: %s', request.path_info, exception)
    return friendly_error(request, 400)


def permission_denied(request, exception=None):
    logger.warning('Permission denied at %s: %s', request.path_info, exception)
    return friendly_error(request, 403)


def page_not_found(request, exception=None):
    logger.info('Page not found: %s', request.path_info)
    return friendly_error(request, 404)


def server_error(request):
    logger.error('Server error at %s (handled by handler500)', request.path_info)
    return friendly_error(request, 500)
