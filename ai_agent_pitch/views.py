# ai_agent_pitch/views.py

import csv
import io
import json
import random
import logging
import textwrap
import threading
import google.generativeai as genai
from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from .models import EmailTemplate, Campaign, Recipient
from django.core.mail import send_mail
from dashboard.gmail import resolve_sender, SenderNotConfigured
from django.http import Http404, HttpResponseForbidden
from dashboard import gcs
from .auto_campaign_service import run_auto_campaign


logger = logging.getLogger(__name__)

# Configure the Gemini AI client
# Note: We don't overwrite genai module, just track if it's configured
GEMAI_CONFIGURED = False
try:
    if hasattr(settings, 'GEMINI_API_KEY') and settings.GEMINI_API_KEY:
        genai.configure(api_key=settings.GEMINI_API_KEY)
        GEMAI_CONFIGURED = True
        logger.info("Gemini AI configured successfully")
    else:
        logger.warning("GEMINI_API_KEY not found in settings")
except Exception as e:
    logger.error(f"Failed to configure Gemini AI: {e}")
    GEMAI_CONFIGURED = False


def _parse_recipient_emails(raw_recipients):
    """Parse comma/semicolon/newline-separated emails and return valid unique addresses."""
    if not raw_recipients:
        return [], []

    normalized = raw_recipients.replace(';', ',').replace('\n', ',')
    candidates = [item.strip() for item in normalized.split(',') if item.strip()]

    valid_emails = []
    invalid_emails = []
    seen = set()

    for candidate in candidates:
        try:
            validate_email(candidate)
        except ValidationError:
            invalid_emails.append(candidate)
            continue

        lower_email = candidate.lower()
        if lower_email not in seen:
            seen.add(lower_email)
            valid_emails.append(candidate)

    return valid_emails, invalid_emails


def _find_column(headers, keywords):
    lower_headers = {h.lower().strip(): h for h in headers}
    for lh, original in lower_headers.items():
        for kw in keywords:
            if kw in lh:
                return original
    return None

def _build_template_clusters(user):
    """Group templates by the campaign they were most recently used in."""
    from collections import OrderedDict
    templates = EmailTemplate.objects.filter(user=user).order_by('name')
    cluster_map = OrderedDict()
    unassigned = []
    for template in templates:
        latest_campaign = template.campaigns.order_by('-sent_at').first()
        if latest_campaign:
            cluster_map.setdefault(latest_campaign.id, {
                'campaign': latest_campaign,
                'templates': [],
            })['templates'].append(template)
        else:
            unassigned.append(template)

    clusters = list(cluster_map.values())
    if unassigned:
        clusters.append({
            'campaign': None,
            'templates': unassigned,
        })

    return clusters


def pitch_creator_view(request):
    if request.method == 'POST':
        subject = request.POST.get('subject')
        html_content = request.POST.get('html_content')
        recipient_data = {}

        if 'csv_file' in request.FILES and request.FILES['csv_file']:
            csv_file = request.FILES['csv_file']
            if not csv_file.name.endswith('.csv'):
                messages.error(request, 'Error: This is not a CSV file.')
            else:
                try:
                    decoded_file = csv_file.read().decode('utf-8-sig')
                    io_string = io.StringIO(decoded_file)
                    reader = csv.DictReader(io_string)

                    headers = [h.strip() for h in reader.fieldnames]

                    email_col = _find_column(headers, ['email', 'e-mail'])
                    company_col = _find_column(headers, ['company', 'organization', 'business', 'org'])
                    first_name_col = _find_column(headers, ['first name', 'first', 'fname'])
                    last_name_col = _find_column(headers, ['last name', 'last'])
                    full_name_col = _find_column(headers, ['name', 'contact name', 'recipient name', 'full name'])

                    if not email_col:
                        messages.error(request, 'Error: Could not find an "Email" column in the CSV file.')
                        return redirect('ai_agent_pitch:pitch_creator')

                    for row in reader:
                        email = row.get(email_col, '').strip()
                        if email and email not in recipient_data:
                            first_name = row.get(first_name_col, '').strip() if first_name_col else ''
                            last_name = row.get(last_name_col, '').strip() if last_name_col else ''
                            company = row.get(company_col, '').strip() if company_col else ''

                            if first_name and last_name:
                                name = f"{first_name} {last_name}"
                            elif first_name:
                                name = first_name.capitalize()
                            elif last_name:
                                name = last_name.capitalize()
                            else:
                                name = row.get(full_name_col, '').strip() if full_name_col else ''

                            if not name:
                                name = company if company else 'Partner'

                            recipient_data[email] = {'name': name, 'company': company}

                    if recipient_data:
                        messages.success(request, f'Success: Loaded {len(recipient_data)} unique emails from CSV.')
                    else:
                        messages.error(request, 'Error: No valid emails found in CSV.')

                except Exception as e:
                    messages.error(request, f"Error: Failed to process CSV file: {e}")
        
        elif 'recipient' in request.POST and request.POST.get('recipient'):
            raw_recipients = request.POST.get('recipient', '')
            recipient_name = request.POST.get('recipient_name', '').strip()
            valid_emails, invalid_emails = _parse_recipient_emails(raw_recipients)

            name = recipient_name if recipient_name else 'Partner'
            for recipient_email in valid_emails:
                recipient_data[recipient_email] = {'name': name}

            if valid_emails:
                messages.info(request, f'Sending to {len(valid_emails)} recipient(s).')
            if invalid_emails:
                messages.warning(request, f'Skipped invalid email(s): {", ".join(invalid_emails)}')

        # Validation logic for recipient_data, subject, etc.
        if not recipient_data:
            messages.error(request, 'Error: Please provide at least one recipient (either via CSV or manual entry).')
            return redirect('ai_agent_pitch:pitch_creator')
        
        if not subject or not html_content:
            messages.error(request, 'Error: Subject and HTML content are required.')
            return redirect('ai_agent_pitch:pitch_creator')

        try:
            template_id = request.POST.get('template_id')
            linked_template = None
            if template_id:
                try:
                    linked_template = EmailTemplate.objects.get(id=template_id, user=request.user)
                except EmailTemplate.DoesNotExist:
                    linked_template = None

            campaign = Campaign.objects.create(subject=subject, template=linked_template, body_html=html_content, user=request.user)
            sent_count = 0
            failed_count = 0

            # Per-user verified Gmail required (owner of the default account
            # excepted). Otherwise alert and stop.
            try:
                sender_connection, sender_from = resolve_sender(request.user)
            except SenderNotConfigured as exc:
                messages.error(request, str(exc))
                return redirect('ai_agent_pitch:pitch_creator')

            for email, data in recipient_data.items():
                tracking_pixel_url = f"{settings.SITE_URL}/pitch/mark-opened/{campaign.id}/{email}/"

                company = data.get('company', '')
                personalized_subject = subject.replace('[Recipient]', data['name']).replace('[Company]', company)
                personalized_content = html_content.replace('[Recipient]', data['name']).replace('[Company]', company)
                personalized_content += f'<img src="{tracking_pixel_url}" width="1" height="1" style="display:none;">'

                try:
                    send_mail(
                        subject=personalized_subject,
                        message='',
                        from_email=sender_from,
                        recipient_list=[email],
                        html_message=personalized_content,
                        fail_silently=False,
                        connection=sender_connection,
                    )
                    Recipient.objects.create(
                        campaign=campaign,
                        name=data['name'],
                        email=email,
                        status='sent',
                        user=request.user
                    )
                    sent_count += 1
                except Exception as send_error:
                    logger.error(f"Failed to send to {email}: {send_error}")
                    Recipient.objects.create(
                        campaign=campaign,
                        name=data['name'],
                        email=email,
                        status='failed',
                        user=request.user
                    )
                    failed_count += 1

            if sent_count == 0:
                campaign.delete()
                messages.error(request, f'Error: All {failed_count} emails failed to send. No campaign was saved.')
            elif failed_count > 0:
                messages.warning(request, f'Partial success: {sent_count} sent, {failed_count} failed.')
            else:
                messages.success(request, f'Success: Sent campaign to {sent_count} recipient(s)!')
        except Exception as e:
            messages.error(request, f'An error occurred: {e}')
            logger.error(f"SMTP sending error: {e}", exc_info=True)
        
        return redirect('ai_agent_pitch:pitch_creator')

    templates = EmailTemplate.objects.filter(user=request.user).order_by('name')
    context = {
        'templates': templates,
        'clusters': _build_template_clusters(request.user),
    }
    return render(request, 'ai_agent_pitch/pitch_creator.html', context)

@require_POST
@csrf_exempt
def save_template_view(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            template_name = data.get('name')
            html_content = data.get('html_content')
            if not template_name or not html_content:
                return JsonResponse({'status': 'error', 'message': 'Template name and content cannot be empty.'}, status=400)
            template, created = EmailTemplate.objects.update_or_create(
                name=template_name, defaults={'html_content': html_content, 'user': request.user}
            )
            message = 'Template saved successfully!' if created else 'Template updated successfully!'
            return JsonResponse({'status': 'success', 'message': message, 'template_id': template.id, 'template_name': template.name})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    return JsonResponse({'status': 'error', 'message': 'Invalid request method.'}, status=405)

def delete_template_view(request, template_id):
    """Delete a template by ID."""
    try:
        template = get_object_or_404(EmailTemplate, id=template_id, user=request.user)
        template.delete()
        return JsonResponse({'status': 'success', 'message': 'Template deleted successfully!'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

def load_template_view(request, template_id):
    try:
        template = get_object_or_404(EmailTemplate, id=template_id, user=request.user)
        return JsonResponse({'status': 'success', 'html_content': template.html_content})
    except Exception:
        return JsonResponse({'status': 'error', 'message': 'Template not found.'}, status=404)

@require_POST
@csrf_exempt
def generate_subject_view(request):
    fallback_suggestions = [
        "A New AI-Powered Opportunity for You",
        "Exclusive Invitation: Discover Our New AI Tools",
        "Transform Your Business with AI Agents",
        "Unlock Growth: Let AI Work for You",
        "Your Competitive Edge: AI-Powered Solutions",
    ]

    context_hint = ''
    try:
        data = json.loads(request.body) if request.body else {}
        context_hint = (data.get('html_content') or '').strip()
    except Exception:
        pass

    if context_hint and hasattr(settings, 'GEMINI_API_KEY') and settings.GEMINI_API_KEY:
        try:
            genai.configure(api_key=settings.GEMINI_API_KEY)
            prompt = f"""You are an expert email marketing copywriter.
Based on the email HTML content below, generate exactly 3 compelling subject lines.

Rules:
- Each subject line on its own line, no numbering or bullets.
- Maximum 60 characters each.
- Be specific, benefit-driven, and curiosity-inducing.
- Output ONLY the 3 subject lines, nothing else.

Email Content:
{context_hint[:1000]}"""
            model = genai.GenerativeModel('gemini-2.0-flash')
            response = model.generate_content(
                prompt,
                request_options={'timeout': 120.0}
            )
            lines = [l.strip() for l in response.text.strip().split('\n') if l.strip()]
            subjects = lines[:3]
            while len(subjects) < 3:
                subjects.append(fallback_suggestions[len(subjects)])
            return JsonResponse({'status': 'success', 'subjects': subjects})
        except Exception as e:
            logger.warning(f"AI subject generation failed: {e}")

    random.shuffle(fallback_suggestions)
    return JsonResponse({'status': 'success', 'subjects': fallback_suggestions[:3]})

@require_POST
@csrf_exempt
def enhance_with_ai_view(request):
    # Check if API key is available
    if not hasattr(settings, 'GEMINI_API_KEY') or not settings.GEMINI_API_KEY:
        return JsonResponse({
            'status': 'error', 
            'message': 'AI service is not configured. Please add GEMINI_API_KEY to your .env file.'
        }, status=500)
    
    try:
        # Reconfigure genai to ensure API key is set
        try:
            genai.configure(api_key=settings.GEMINI_API_KEY)
        except Exception as config_error:
            logger.error(f"Failed to configure Gemini: {config_error}")
            return JsonResponse({
                'status': 'error',
                'message': f'Failed to initialize AI service: {str(config_error)}'
            }, status=500)
        
        data = json.loads(request.body)
        user_prompt = data.get('prompt')
        html_content = data.get('html_content')
        
        if not user_prompt:
            return JsonResponse({'status': 'error', 'message': 'Prompt cannot be empty.'}, status=400)
        
        # Get example template (optional - won't fail if not found)
        example_template = EmailTemplate.objects.filter(name__icontains='light').first()
        if not example_template:
            # Use first available template as example
            example_template = EmailTemplate.objects.first()
        
        # If still no template, proceed without example
        example_html = example_template.html_content if example_template else '<p>No example available</p>'

        if html_content:
            task_description = "Refine and improve the following HTML code based on the user's request."
            code_block = f"**ORIGINAL HTML TO REFINE:**\n```html\n{html_content}\n```"
        else:
            task_description = "Generate the complete HTML code for an email based on the user's request."
            code_block = ""

        system_instructions = textwrap.dedent(f"""
            **ROLE:** You are an expert HTML email developer named "KALI AI", specializing in modern, Gmail-compatible marketing emails.
            **TASK:** {task_description}
            **CRITICAL RULES:**
            1.  **Inline CSS ONLY:** Do not use `<style>` blocks.
            2.  **Mobile-Responsive:** Use fluid, table-based layouts.
            3.  **Modern Design:** Use clean layouts, trending colors, and good typography.
            4.  **Placeholders:** Use `https://placehold.co/` for any requested images.
            **PRIME EXAMPLE (for style and structure):**
            ```html
            {example_html}
            ```
            {code_block}
            **USER'S REQUEST:**
            "{user_prompt}"
            **YOUR RESPONSE (Raw HTML code only):**
        """).strip()
        
        # Try multiple model versions for reliability
        available_models = ['gemini-2.0-flash', 'gemini-2.5-flash', 'gemini-1.5-flash']
        
        for model_name in available_models:
            try:
                logger.info(f"Trying model: {model_name}")
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(
                    system_instructions,
                    request_options={'timeout': 120.0}
                )
                
                # Check if response is valid
                if not response or not hasattr(response, 'text'):
                    logger.warning(f"Model {model_name} returned invalid response")
                    continue
                
                # Extract HTML from response (may be wrapped in markdown)
                html_output = response.text
                if '```html' in html_output:
                    html_output = html_output.split('```html')[1].split('```')[0].strip()
                elif '```' in html_output:
                    html_output = html_output.split('```')[1].split('```')[0].strip()
                
                logger.info(f"Successfully generated content with {model_name}")
                return JsonResponse({'status': 'success', 'html_content': html_output})
            except Exception as model_error:
                logger.warning(f"Model {model_name} failed: {model_error}", exc_info=True)
                continue
        
        # If all models fail
        return JsonResponse({
            'status': 'error', 
            'message': 'All AI models are currently unavailable. Please try again later.'
        }, status=503)
    except Exception as e:
        logger.error(f"Gemini AI error: {e}", exc_info=True)
        return JsonResponse({'status': 'error', 'message': f'An error occurred with the AI service: {str(e)}'}, status=500)

def dashboard_view(request):
    campaign_list = Campaign.objects.all().order_by('-sent_at')
    paginator = Paginator(campaign_list, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    for campaign in page_obj.object_list:
        recipients = campaign.recipients.all()
        total_sent = recipients.count()
        total_opened = recipients.filter(status='opened').count()
        campaign.total_sent = total_sent
        campaign.total_opened = total_opened
        campaign.open_rate = (total_opened / total_sent * 100) if total_sent > 0 else 0
    context = {'page_obj': page_obj}
    return render(request, 'ai_agent_pitch/dashboard.html', context)


def campaign_detail_view(request, campaign_id):
    try:
        campaign = Campaign.objects.get(id=campaign_id)
        recipient_list = campaign.recipients.all().order_by('name')
        context = {
            'campaign': campaign,
            'recipients': recipient_list,
        }
        return render(request, 'ai_agent_pitch/campaign_detail.html', context)
    except Campaign.DoesNotExist:
        raise Http404("Campaign does not exist")


@require_POST
@csrf_exempt
def get_campaigns_view(request):
    try:
        if request.user.is_authenticated:
            campaigns = Campaign.objects.filter(user=request.user).order_by('-sent_at')
        else:
            campaigns = Campaign.objects.none()
        campaign_data = []
        for campaign in campaigns:
            recipients = campaign.recipients.all()
            total_sent = recipients.count()
            total_opened = recipients.filter(status='opened').count()
            campaign_data.append({
                'id': campaign.id,
                'subject': campaign.subject,
                'sent_at': campaign.sent_at.strftime('%Y-%m-%d %H:%M'),
                'total_sent': total_sent,
                'total_opened': total_opened,
            })
        return JsonResponse({'status': 'success', 'campaigns': campaign_data})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

def mark_as_opened_view(request, campaign_id, recipient_email):
    try:
        recipient = get_object_or_404(Recipient, campaign_id=campaign_id, email=recipient_email, user=request.user)
        if recipient.status != 'opened':
            recipient.status = 'opened'
            recipient.opened_at = timezone.now()
            recipient.save()
        content_type = 'image/gif'
        return HttpResponse(
            (b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff'
             b'\x00\x00\x00\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00'
             b'\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b'),
            content_type=content_type
        )
    except Recipient.DoesNotExist:
        return HttpResponse(status=404)
    except Exception as e:
        return HttpResponse(status=404)
    except Exception as e:
        logger.error(f"Error marking email as opened: {e}")
        return HttpResponse(status=500)


# ---------------------------------------------------------------------------
# AI Auto Campaign Engine (dashboard section-autocampaign)
# ---------------------------------------------------------------------------

CATEGORY_LABELS = {
    'suppliers': 'Suppliers',
    'buyers': 'Buyers',
    'events': 'Events',
    'linkedin': 'LinkedIn Contacts',
}


def campaign_engine_config_view(request):
    """GET — return the saved auto-campaign config plus options (templates, categories)."""
    try:
        config = gcs.get_campaign_config()
        if request.user.is_authenticated:
            templates = list(EmailTemplate.objects.filter(user=request.user).order_by('name').values('id', 'name'))
        else:
            templates = []
        
        category_counts = {}
        for cat, label in CATEGORY_LABELS.items():
            contacts = gcs.list_contacts(cat, user=request.user) or []
            category_counts[cat] = {'label': label, 'count': len(contacts)}

        return JsonResponse({
            'success': True,
            'config': config,
            'templates': templates,
            'categories': category_counts,
        })
    except Exception as e:
        logger.error(f"Error loading campaign engine config: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@require_POST
def campaign_engine_config_save_view(request):
    """POST JSON — persist the auto-campaign config."""
    try:
        body = json.loads(request.body)
        config = gcs.get_campaign_config()
        config['category'] = (body.get('category') or config.get('category') or 'suppliers').strip()
        config['template_id'] = body.get('template_id')
        config['subject'] = (body.get('subject') or '').strip()
        try:
            config['daily_limit'] = max(1, min(int(body.get('daily_limit') or config.get('daily_limit') or 25), 500))
        except (TypeError, ValueError):
            config['daily_limit'] = int(config.get('daily_limit') or 25)
        config['personalize_subject'] = bool(body.get('personalize_subject', True))
        config['personalize_body'] = bool(body.get('personalize_body', True))

        if not gcs.save_campaign_config(config):
            return JsonResponse({'success': False, 'error': 'Failed to save config to GCS'}, status=500)
        return JsonResponse({'success': True, 'config': config})
    except Exception as e:
        logger.error(f"Error saving campaign engine config: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def _start_background_campaign(config, trigger='manual'):
    def _target():
        try:
            run_auto_campaign(config, trigger=trigger)
        except Exception as e:
            logger.error(f"[auto-campaign] Background run failed: {e}", exc_info=True)
            gcs.save_campaign_progress({
                'state': 'failed',
                'error': str(e),
                'finished_at': timezone.now().isoformat(),
            })

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    return thread


@csrf_exempt
@require_POST
def campaign_engine_run_view(request):
    """POST — start an auto-campaign in the background using the saved config."""
    try:
        config = gcs.get_campaign_config()
        config['user'] = request.user.username
        if request.body:
            try:
                body = json.loads(request.body)
                if body:
                    config.update({
                        k: v for k, v in body.items()
                        if k in ('category', 'template_id', 'subject', 'daily_limit',
                                 'personalize_subject', 'personalize_body')
                    })
            except json.JSONDecodeError:
                pass

        if not config.get('template_id'):
            templates = EmailTemplate.objects.order_by('name').values_list('id', flat=True)
            if not templates:
                return JsonResponse({'success': False, 'error': 'Create an email template in the Pitch Generator first.'}, status=400)
            config['template_id'] = templates[0]

        # Instant alert: block the run before the background thread starts.
        try:
            resolve_sender(request.user)
        except SenderNotConfigured as exc:
            return JsonResponse({'success': False, 'error': str(exc)}, status=400)

        progress = gcs.get_campaign_progress()
        if progress and progress.get('state') == 'running':
            return JsonResponse({'success': False, 'error': 'An auto-campaign is already running.'}, status=409)

        _start_background_campaign(config, trigger='manual')
        return JsonResponse({'success': True, 'message': 'Auto-campaign started in the background.'})
    except Exception as e:
        logger.error(f"Error starting auto-campaign: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def campaign_engine_progress_view(request):
    """GET — live progress of the current/last auto-campaign run."""
    progress = gcs.get_campaign_progress()
    if progress is None:
        progress = {'state': 'idle'}
    return JsonResponse(progress)


def campaign_engine_runs_view(request):
    """GET — list historical auto-campaign runs from GCS (newest first)."""
    try:
        runs = gcs.list_campaign_runs()
        return JsonResponse({'success': True, 'runs': runs})
    except Exception as e:
        logger.error(f"Error listing campaign runs: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def campaign_engine_run_detail_view(request):
    """GET ?path=<blob_path> — fetch a single auto-campaign run batch."""
    try:
        run_path = request.GET.get('path', '')
        run = gcs.get_campaign_run(run_path)
        if run is None:
            return JsonResponse({'success': False, 'error': 'Run not found'}, status=404)
        return JsonResponse({'success': True, 'run': run})
    except Exception as e:
        logger.error(f"Error fetching campaign run detail: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
