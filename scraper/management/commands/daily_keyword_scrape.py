"""
Daily scheduled LinkedIn keyword scrape.

Usage:
    python manage.py daily_keyword_scrape                  # all active keywords × locations
    python manage.py daily_keyword_scrape --keyword "ai automation"
    python manage.py daily_keyword_scrape --location USA   # restrict to one location
    python manage.py daily_keyword_scrape --num 5          # profiles per keyword
    python manage.py daily_keyword_scrape --dry-run        # show plan, no network calls

Wire it to a scheduler (any one of):
  - Cloud Scheduler  -> POST https://<service>/scraper/scheduler/run/
                        with header  X-Scheduler-Secret: <SCHEDULER_SECRET>
  - Cloud Run Jobs   -> run this command on a schedule
  - Local cron/Task Scheduler -> run this command daily
"""

from django.core.management.base import BaseCommand

from scraper.services import run_daily_scrape
from dashboard.gcs import get_scrape_keywords, get_scrape_locations


class Command(BaseCommand):
    help = 'Scrape LinkedIn daily for the configured keywords (filtered by locations), analyze with Gemini, and store results in GCS.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--keyword',
            type=str,
            default=None,
            help='Run only for this single keyword (default: all active keywords).',
        )
        parser.add_argument(
            '--location',
            type=str,
            default=None,
            help='Run only for this single location (default: all active locations).',
        )
        parser.add_argument(
            '--num',
            type=int,
            default=10,
            help='Number of profiles to fetch per keyword (default: 10).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would run without calling SerpAPI/Gemini/GCS.',
        )

    def handle(self, *args, **options):
        keyword = options['keyword']
        location = options['location']
        num = options['num']
        dry_run = options['dry_run']

        if keyword:
            keywords = [keyword]
        else:
            keywords = [k['keyword'] for k in get_scrape_keywords() if k.get('active')]

        if location:
            locations = [location]
        else:
            locations = [l['location'] for l in get_scrape_locations() if l.get('active')]

        if not keywords:
            self.stdout.write(self.style.WARNING('No active scrape keywords configured.'))
            return

        self.stdout.write(f"Keywords to scrape ({len(keywords)}): {', '.join(keywords)}")
        self.stdout.write(f"Locations to filter ({len(locations)}): {', '.join(locations)}")
        self.stdout.write(f"Profiles per keyword: {num}")

        if dry_run:
            self.stdout.write(self.style.SUCCESS('Dry run — no scraping performed.'))
            return

        summaries = run_daily_scrape(keywords=keywords, locations=locations, num=num, trigger='command')

        self.stdout.write('')
        ok = 0
        for s in summaries:
            label = f"{s['keyword']}"
            if s.get('location'):
                label += f" [{s['location']}]"
            if s.get('status') == 'success':
                ok += 1
                self.stdout.write(self.style.SUCCESS(
                    f"[OK] {label}: {s['profiles_analyzed']}/{s['profiles_found']} "
                    f"profiles analyzed -> {s.get('run_path')}"
                ))
            else:
                self.stdout.write(self.style.ERROR(
                    f"[FAIL] {label}: {s.get('error') or 'unknown error'}"
                ))

        self.stdout.write('')
        if ok == len(summaries):
            self.stdout.write(self.style.SUCCESS(f'Daily scrape complete: {ok}/{len(summaries)} jobs succeeded.'))
        else:
            self.stdout.write(self.style.WARNING(f'Daily scrape complete: {ok}/{len(summaries)} jobs succeeded.'))
