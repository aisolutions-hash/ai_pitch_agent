from django.shortcuts import redirect
from django.conf import settings


class LoginRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            path = request.path_info
            allowed_prefixes = (
                settings.LOGIN_URL,
                '/static/',
                '/pitch/mark-opened/',
            )
            if not path.startswith(allowed_prefixes):
                return redirect(f'{settings.LOGIN_URL}?next={path}')
        return self.get_response(request)
