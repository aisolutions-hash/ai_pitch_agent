# ai_agent_pitch/auto_campaign_service.py
#
# Background auto-campaign engine: pulls contacts from GCS, personalizes the
# selected email template with the Gemma/AI service, sends the emails, and
# records a Campaign + Recipients while tracking progress in GCS.
#
# This runs in a daemon thread from the view layer and never touches the
# manual pitch flow.

import logging
import re
from datetime import datetime

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.utils import timezone

from dashboard import gcs
from dashboard.gmail import resolve_sender, SenderNotConfigured
from .models import EmailTemplate, Campaign, Recipient
from .gemma_service import generate_personalized_email

logger = logging.getLogger(__name__)

VALID_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _progress_payload(state, **overrides):
    base = {
        'state': state,
        'trigger': 'manual',
        'category': 'suppliers',
        'template_name': '',
        'run_id': '',
        'started_at': None,
        'total_contacts': 0,
        'processed': 0,
        'sent': 0,
        'failed': 0,
        'current_name': '',
        'current_email': '',
        'error': None,
    }
    base.update(overrides)
    return base


def _fail_progress(message):
    gcs.save_campaign_progress(_progress_payload(
        'failed',
        error=message,
        finished_at=datetime.now().isoformat(),
    ))


def run_auto_campaign(config, trigger='manual'):
    """
    Run an auto-campaign in the current thread (caller spawns a daemon thread).

    config keys:
      - category (str): contacts folder, default 'suppliers'
      - template_id (int/None): email template to use
      - subject (str): base subject line (defaults to template name)
      - daily_limit (int): max contacts to email
      - personalize_subject (bool)
      - personalize_body (bool)
    """
    category = (config.get('category') or 'suppliers').strip() or 'suppliers'
    template_id = config.get('template_id')
    base_subject = (config.get('subject') or '').strip()
    try:
        daily_limit = int(config.get('daily_limit') or 25)
    except (TypeError, ValueError):
        daily_limit = 25
    personalize_subject = bool(config.get('personalize_subject', True))
    personalize_body = bool(config.get('personalize_body', True))

    template = None
    if template_id:
        template = EmailTemplate.objects.filter(id=template_id).first()
    if not template:
        template = EmailTemplate.objects.order_by('name').first()
    if not template:
        _fail_progress('No email template available — create one in the Pitch Generator first.')
        return

    if not base_subject:
        base_subject = template.name

    owner = User.objects.filter(username=config.get('user') or '').first()
    contacts = gcs.list_contacts(category, user=owner) or []
    if not contacts:
        _fail_progress(f'No contacts found in the "{category}" category.')
        return

    # Per-user verified Gmail required; only the default-account owner may
    # send without connecting (SenderNotConfigured otherwise).
    try:
        sender_connection, sender_from = resolve_sender(owner)
    except SenderNotConfigured as exc:
        _fail_progress(str(exc))
        return
    logger.info(f"[auto-campaign] Sending via: {sender_from}")

    run_id = datetime.now().strftime('%Y%m%d-%H%M%S')
    selected = contacts[:daily_limit]

    progress = _progress_payload(
        'running',
        trigger=trigger,
        category=category,
        template_name=template.name,
        run_id=run_id,
        started_at=datetime.now().isoformat(),
        total_contacts=len(selected),
    )
    gcs.save_campaign_progress(progress)

    campaign = Campaign.objects.create(
        subject=base_subject,
        template=template,
        body_html=template.html_content,
    )

    results = []
    for contact in selected:
        data = contact.get('data') or {}
        name = (data.get('name') or 'Partner').strip() or 'Partner'
        email = (data.get('email') or '').strip()

        progress['current_name'] = name
        progress['current_email'] = email
        gcs.save_campaign_progress(progress)

        if not VALID_EMAIL_RE.match(email):
            progress['processed'] += 1
            progress['failed'] += 1
            results.append({
                'name': name,
                'email': email,
                'status': 'skipped',
                'error': 'No valid email address',
            })
            gcs.save_campaign_progress(progress)
            continue

        try:
            if personalize_subject or personalize_body:
                ai_subject, ai_body = generate_personalized_email(
                    base_subject, template.html_content, data
                )
                personalized_subject = ai_subject if personalize_subject else base_subject
                personalized_body = ai_body if personalize_body else template.html_content.replace(
                    '[Recipient]', name
                ).replace('[Company]', (data.get('company') or 'your company'))
            else:
                personalized_subject = base_subject.replace('[Recipient]', name)
                personalized_body = template.html_content.replace('[Recipient]', name)

            tracking_pixel_url = f"{settings.SITE_URL}/pitch/mark-opened/{campaign.id}/{email}/"
            personalized_body += f'<img src="{tracking_pixel_url}" width="1" height="1" style="display:none;">'

            send_mail(
                subject=personalized_subject,
                message='',
                from_email=sender_from,
                recipient_list=[email],
                html_message=personalized_body,
                fail_silently=False,
                connection=sender_connection,
            )
            Recipient.objects.create(
                campaign=campaign,
                name=name,
                email=email,
                status='sent',
            )
            progress['sent'] += 1
            results.append({'name': name, 'email': email, 'status': 'sent', 'error': None})
        except Exception as e:
            logger.error(f"[auto-campaign] Failed to send to {email}: {e}")
            Recipient.objects.create(
                campaign=campaign,
                name=name,
                email=email,
                status='failed',
            )
            progress['failed'] += 1
            results.append({'name': name, 'email': email, 'status': 'failed', 'error': str(e)})

        progress['processed'] += 1
        gcs.save_campaign_progress(progress)

    finished_at = datetime.now().isoformat()
    progress['state'] = 'completed'
    progress['finished_at'] = finished_at
    progress['current_name'] = ''
    progress['current_email'] = ''
    gcs.save_campaign_progress(progress)

    if progress['sent'] == 0:
        campaign.delete()

    gcs.upload_campaign_run(f"{run_id}.json", {
        'run_id': run_id,
        'trigger': trigger,
        'category': category,
        'template_name': template.name,
        'subject': base_subject,
        'started_at': progress['started_at'],
        'finished_at': finished_at,
        'total_contacts': len(selected),
        'sent': progress['sent'],
        'failed': progress['failed'],
        'recipients': results,
    })

    logger.info(f"[auto-campaign] Finished run {run_id}: {progress['sent']} sent, {progress['failed']} failed")