from django.conf import settings
from django.db import models


class GmailSettings(models.Model):
    """
    Per-user Gmail SMTP configuration. The App Password is stored
    encrypted (Fernet) and is never rendered or returned in plaintext.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='gmail_settings',
    )
    gmail_address = models.EmailField()
    app_password_encrypted = models.TextField()
    is_connected = models.BooleanField(default=False)
    last_tested_at = models.DateTimeField(null=True, blank=True)
    last_test_error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Gmail settings'
        verbose_name_plural = 'Gmail settings'

    def __str__(self):
        return f'GmailSettings({self.user.username} -> {self.gmail_address})'
