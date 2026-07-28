import os
import logging
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Create or update the application user from APP_USERNAME/APP_PASSWORD env vars'

    def handle(self, *args, **options):
        username = os.getenv('APP_USERNAME', '').strip()
        password = os.getenv('APP_PASSWORD', '').strip()

        if not username or not password:
            self.stdout.write(self.style.WARNING(
                'APP_USERNAME or APP_PASSWORD not set — skipping app user creation'
            ))
            return

        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                'is_staff': False,
                'is_superuser': False,
            }
        )

        if created:
            user.set_password(password)
            user.save()
            self.stdout.write(self.style.SUCCESS(f'App user "{username}" created'))
            logger.info(f'App user "{username}" created')
        else:
            if not user.check_password(password):
                user.set_password(password)
                user.save()
                self.stdout.write(self.style.SUCCESS(f'App user "{username}" password updated'))
                logger.info(f'App user "{username}" password updated')
            else:
                self.stdout.write(f'App user "{username}" already exists — no changes needed')
