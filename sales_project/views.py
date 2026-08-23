from django import forms
from django.conf import settings
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import logout as django_logout
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.views.decorators.http import require_POST

from sales_project.middleware import NO_CACHE_HEADERS


class SignupForm(UserCreationForm):
    email = forms.EmailField(label='Email address', required=True)

    class Meta(UserCreationForm.Meta):
        fields = ('username', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields(['username', 'email', 'password1', 'password2'])

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError('An account with this email already exists.')
        return email


def signup(request):
    if request.method == 'POST':
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.email = form.cleaned_data['email']
            user.save()
            login(request, user)
            messages.success(request, f'Welcome to KalisoftAI, {user.username}! Your account is ready.')
            return redirect('dashboard-home')
    else:
        form = SignupForm()
    return render(request, 'registration/signup.html', {'form': form})


@require_POST
def custom_logout(request):
    """
    Log the user out with full server-side session invalidation:
    auth_logout() deletes the current session row, rotates the session
    key and clears the cookie. POST-only so a stray GET/prefetch link can
    never log someone out. The redirect itself is marked no-store.
    """
    django_logout(request)
    response = redirect(settings.LOGOUT_REDIRECT_URL or settings.LOGIN_URL)
    for header, value in NO_CACHE_HEADERS.items():
        response[header] = value
    return response
