from django.db import models
from django.utils import timezone

class EmailTemplate(models.Model):
    name = models.CharField(max_length=100, unique=True)
    html_content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class Campaign(models.Model):
    subject = models.CharField(max_length=255)
    sent_at = models.DateTimeField(auto_now_add=True)
    template = models.ForeignKey(
        EmailTemplate,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='campaigns',
        help_text='The email template this campaign was sent from.'
    )
    body_html = models.TextField(blank=True, default='', help_text='Snapshot of the HTML sent in this campaign.')

    def __str__(self):
        return f"Campaign: {self.subject} ({self.sent_at.strftime('%Y-%m-%d %H:%M')})"

class Recipient(models.Model):
    STATUS_CHOICES = [
        ('sent', 'Sent'),
        ('opened', 'Opened'),
        ('failed', 'Failed'),
    ]
    campaign = models.ForeignKey(Campaign, related_name='recipients', on_delete=models.CASCADE)
    name = models.CharField(max_length=255, blank=True)
    email = models.EmailField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='sent')
    opened_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} <{self.email}> - {self.get_status_display()}"