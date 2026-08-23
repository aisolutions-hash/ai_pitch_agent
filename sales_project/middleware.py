from django.conf import settings
from django.shortcuts import redirect

import logging

logger = logging.getLogger(__name__)

# Paths reachable without authentication. Shared by the auth gate and the
# cache middleware so both always agree on what is public.
PUBLIC_PREFIXES = (
    settings.LOGIN_URL,
    '/static/',
    '/pitch/mark-opened/',   # email tracking pixel (opened by mail clients)
    '/scraper/scheduler/',   # token-protected endpoint (validated in view)
    '/signup/',
    '/password-reset/',
    '/reset/',
    '/favicon.ico',
)

NO_CACHE_HEADERS = {
    'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
    'Pragma': 'no-cache',
    'Expires': '0',
}


def _is_public(path):
    return path == '/' or path.startswith(PUBLIC_PREFIXES)


class LoginRequiredMiddleware:
    """
    Gate every non-public route behind authentication. Unauthenticated
    requests are redirected to the login page with a ?next= target so
    users land back where they started after signing in.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            path = request.path_info
            if not _is_public(path):
                response = redirect(f'{settings.LOGIN_URL}?next={path}')
                for header, value in NO_CACHE_HEADERS.items():
                    response[header] = value
                return response
        return self.get_response(request)


class CacheControlMiddleware:
    """
    Never allow authenticated content to be served from browser/proxy
    caches: every protected response is marked no-store. This is what
    makes the Back button after logout show the login page (or a safe
    redirect) instead of cached dashboard data.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not _is_public(request.path_info):
            for header, value in NO_CACHE_HEADERS.items():
                response[header] = value
        return response


class FriendlyErrorMiddleware:
    """
    Outermost safety net: any unhandled exception in the request cycle is
    logged with a full traceback (for the team) and converted into a clean,
    reassuring user-facing error - JSON for API endpoints, HTML page
    otherwise. Works identically in DEBUG and production.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            return self.get_response(request)
        except Exception:
            logger.exception('Unhandled server error on %s %s',
                             request.method, request.path_info)
            from sales_project.error_handlers import friendly_error
            return friendly_error(request, 500)
