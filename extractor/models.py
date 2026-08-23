from django.db import models


class Supplier(models.Model):
    user = models.ForeignKey(
        'auth.User',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='suppliers',
        help_text='The user who owns this supplier record.'
    )
    company = models.CharField(max_length=255, default='N/A')
    email = models.EmailField(help_text='Email address of the supplier')
    name = models.CharField(max_length=255, default='N/A')
    number = models.CharField(max_length=50, blank=True, null=True, default='N/A')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('user', 'email')

    def __str__(self):
        return f"{self.company} ({self.email})"