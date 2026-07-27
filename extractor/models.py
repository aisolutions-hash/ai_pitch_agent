from django.db import models

class Supplier(models.Model):
    company = models.CharField(max_length=255, default='N/A')
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=255, default='N/A')
    number = models.CharField(max_length=50, blank=True, null=True, default='N/A')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.company} ({self.email})"

    class Meta:
        ordering = ['-created_at']