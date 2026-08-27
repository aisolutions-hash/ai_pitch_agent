from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
import json
import logging
from django.conf import settings
from . import gcs

logger = logging.getLogger(__name__)


logger = logging.getLogger(__name__)


@login_required
def csv_files_count(request):
    """API endpoint to get CSV file counts for all categories (user-scoped)."""
    try:
        categories = ['linkedin', 'suppliers', 'buyers', 'events']
        counts = {}
        total = 0
        
        for category in categories:
            try:
                files = gcs.list_csv_files(category, user=request.user)
                if files is None:
                    counts[category] = 0
                else:
                    counts[category] = len(files)
                    total += len(files)
            except Exception as e:
                logger.error(f"Error getting CSV files for {category}: {e}")
                counts[category] = 0
        
        return JsonResponse({'counts': counts, 'total': total})
    except Exception as e:
        logger.error(f"Error getting CSV file counts: {e}")
        return JsonResponse({'counts': {}, 'total': 0})


@login_required
def home(request):
    """
    Render the user-specific dashboard homepage.
    Shows only data belonging to request.user.
    """
    categories = [
        {'name': 'linkedin', 'label': 'LinkedIn Contacts', 'color': 'blue'},
    ]
    combined_categories = [
        {'name': 'suppliers', 'label': 'Suppliers', 'color': 'amber'},
        {'name': 'buyers', 'label': 'Buyers', 'color': 'teal'},
        {'name': 'events', 'label': 'Events', 'color': 'purple'},
    ]
    
    # Get user-specific contact counts
    user_contact_counts = {}
    user_total = 0
    for category in ['linkedin', 'suppliers', 'buyers', 'events']:
        try:
            contacts = gcs.list_contacts(category, user=request.user)
            if contacts is None:
                user_contact_counts[category] = 0
            else:
                user_contact_counts[category] = len(contacts)
                user_total += len(contacts)
        except Exception as e:
            logger.error(f"Error getting contact counts for {category}: {e}")
            user_contact_counts[category] = 0
    
    return render(request, 'dashboard/index.html', {
        'categories': categories,
        'combined_categories': combined_categories,
        'user_contact_counts': user_contact_counts,
        'user_total': user_total,
    })


@login_required
def contacts_list(request):
    """
    API endpoint to list contacts by category.
    GET params: category (linkedin/suppliers/buyers/events)
    Returns: JsonResponse with list of contact dicts (user-scoped)
    """
    try:
        category = request.GET.get('category', '').lower()
        
        if not category:
            return JsonResponse({'error': 'Category parameter is required'}, status=400)
        
        if category not in ['linkedin', 'suppliers', 'buyers', 'events']:
            return JsonResponse({'error': 'Invalid category'}, status=400)
        
        contacts = gcs.list_contacts(category, user=request.user)
        
        # If GCS is not available or returns None, return empty list instead of error
        if contacts is None:
            return JsonResponse([], safe=False)
        
        return JsonResponse(contacts, safe=False)
    except Exception as e:
        logger.error(f"Error listing contacts for {category}: {e}")
        # Return empty list on error to keep dashboard functional
        return JsonResponse([], safe=False)


@login_required
def diagnostics(request):
    """
    Admin health-check endpoint: reports which integration configs are present
    and whether GCS / Sheets / Gemini / DB are actually reachable.
    NEVER returns secret values - only presence booleans and short messages.
    """
    import os
    from django.conf import settings as s
    from django.contrib.auth.models import User as U

    required = ['DJANGO_SECRET_KEY', 'DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_HOST',
                'GEMINI_API_KEY', 'SERPAPI_API_KEY', 'GOOGLE_SHEET_ID', 'LINKEDIN_SHEET_ID',
                'PITCH_SHEET_ID', 'GCS_BUCKET_NAME', 'GCS_PROJECT_ID', 'GOOGLE_CREDENTIALS_JSON',
                'PITCH_EMAIL_HOST_USER', 'PITCH_GMAIL_APP_PASSWORD', 'APP_USERNAME',
                'APP_PASSWORD', 'SCHEDULER_SECRET', 'SITE_URL']
    env = {k: bool(os.getenv(k)) for k in required}

    checks = {}

    try:
        checks['database'] = {'ok': True, 'detail': f'users={U.objects.count()}'}
    except Exception as e:
        checks['database'] = {'ok': False, 'detail': str(e)[:150]}

    try:
        from dashboard import gcs
        bucket = gcs._get_bucket()
        if not bucket:
            checks['gcs'] = {'ok': False, 'detail': 'bucket client failed (credentials/permissions)'}
        else:
            n = 0
            for _ in bucket.list_blobs(prefix='contacts/user_1_linkedin/', page_size=6):
                n += 1
            checks['gcs'] = {'ok': n > 0, 'detail': f'user_1_linkedin blobs found: {n}'}
    except Exception as e:
        checks['gcs'] = {'ok': False, 'detail': str(e)[:150]}

    try:
        from sales_project.google_auth import default_or_loaded
        import gspread
        creds = default_or_loaded(['https://www.googleapis.com/auth/spreadsheets'])
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(s.GOOGLE_SHEET_ID)
        checks['sheets'] = {'ok': True, 'detail': f'opened sheet "{sh.title}"'}
    except Exception as e:
        checks['sheets'] = {'ok': False, 'detail': str(e)[:150]}

    try:
        import google.generativeai as genai
        genai.configure(api_key=s.GEMINI_API_KEY)
        models = list(genai.list_models())
        checks['gemini'] = {'ok': True, 'detail': f'{len(models)} models visible'}
    except Exception as e:
        checks['gemini'] = {'ok': False, 'detail': str(e)[:150]}

    overall = all(c['ok'] for c in checks.values())
    return JsonResponse({'overall_ok': overall, 'env': env, 'checks': checks},
                        status=200 if overall else 503)


@login_required
def contacts_count(request):
    """
    API endpoint to get contact counts for all categories.
    Returns: JsonResponse with counts per category and total (user-scoped).
    On backend failures an 'error' field is included instead of silently
    reporting zero, so issues (e.g. storage credentials) surface immediately.
    """
    categories = ['linkedin', 'suppliers', 'buyers', 'events']
    counts = {}
    total = 0
    errors = []

    for category in categories:
        try:
            contacts = gcs.list_contacts(category, user=request.user)
            if contacts is None:
                counts[category] = 0
                errors.append(f'{category}: storage backend unavailable')
            else:
                counts[category] = len(contacts)
                total += len(contacts)
        except Exception as e:
            logger.error(f"Error getting contacts for {category}: {e}")
            counts[category] = 0
            errors.append(f'{category}: {e}')

    payload = {'counts': counts, 'total': total}
    if errors:
        payload['error'] = '; '.join(errors)
        return JsonResponse(payload, status=502)
    return JsonResponse(payload)


@login_required
def add_contact(request):
    """
    API endpoint to add a contact for the authenticated user.

    Accepts the dashboard's flat payload:
        {category, name, company, email, phone, linkedin_url, website, tags, notes}
    Also remains backward compatible with the older form:
        {category, uid, data: {...}}

    uid rules: if provided -> use it; else if linkedin_url present -> profile
    slug (deterministic, so re-adding the same person updates instead of
    duplicating); else slug(name) + short random suffix.
    """
    import hashlib
    import re
    from django.utils import timezone

    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)

    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON body'}, status=400)

    category = (data.get('category') or 'linkedin').strip().lower()
    if category not in ('linkedin', 'suppliers', 'buyers', 'events'):
        return JsonResponse({'status': 'error', 'message': f'Invalid category: {category}'}, status=400)

    # Build contact_data: nested 'data' dict (legacy) OR flat fields (current UI)
    contact_data = data.get('data') if isinstance(data.get('data'), dict) else None
    if contact_data is None:
        contact_data = {
            'name': (data.get('name') or '').strip(),
            'company': (data.get('company') or '').strip(),
            'email': (data.get('email') or '').strip(),
            'phone': (data.get('phone') or '').strip(),
            'linkedin_url': (data.get('linkedin_url') or '').strip(),
            'website': (data.get('website') or '').strip(),
            'tags': data.get('tags') if isinstance(data.get('tags'), list) else [],
            'notes': (data.get('notes') or '').strip(),
        }

    if not (contact_data.get('name') or '').strip():
        return JsonResponse({'status': 'error', 'message': 'Name is required'}, status=400)

    uid = (data.get('uid') or '').strip()
    if not uid:
        linkedin_url = (contact_data.get('linkedin_url') or '').strip()
        if linkedin_url:
            uid = linkedin_url.rstrip('/').split('/')[-1]
        else:
            slug = re.sub(r'[^a-z0-9]+', '-', contact_data['name'].lower()).strip('-') or 'contact'
            uid = f"{slug}-{hashlib.md5((contact_data['name'] + timezone.now().isoformat()).encode()).hexdigest()[:6]}"

    now = timezone.now().isoformat()
    contact_data.setdefault('created_at', now)
    contact_data['updated_at'] = now

    result = gcs.upload_contact(category, uid, contact_data, user=request.user)
    if not result:
        return JsonResponse(
            {'status': 'error', 'message': 'Storage backend unavailable - contact could not be saved'},
            status=502,
        )
    return JsonResponse({
        'status': 'success',
        'message': 'Contact added successfully',
        'uid': uid,
        'category': category,
    })


@login_required
def delete_contact(request):
    """
    API endpoint to delete a contact for the authenticated user.
    """
    if request.method == 'POST':
        try:
            import json as json_mod
            data = json_mod.loads(request.body)
            category = data.get('category')
            uid = data.get('uid')
            
            if not uid or not category:
                return JsonResponse({'status': 'error', 'message': 'UID and category are required'}, status=400)
            
            result = gcs.delete_contact(category, uid, user=request.user)
            if result:
                return JsonResponse({'status': 'success', 'message': 'Contact deleted successfully'})
            else:
                return JsonResponse({'status': 'error', 'message': 'Failed to delete contact'}, status=500)
        except Exception as e:
            logger.error(f"Error deleting contact: {e}")
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    else:
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)


@login_required
def csv_files_list(request):
    """List CSV files in a category for the authenticated user."""
    try:
        category = request.GET.get('category', '').lower()
        if not category:
            return JsonResponse({'error': 'category parameter is required'}, status=400)
        
        files = gcs.list_csv_files(category, user=request.user)
        return JsonResponse({'files': files})
    except Exception as e:
        logger.error(f"Error listing CSV files: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def csv_file_download(request, category, filename):
    """Download a CSV file for the authenticated user."""
    try:
        data = gcs.get_csv_file(category, filename, user=request.user)
        if not data or 'content' not in data:
            return HttpResponse(status=404)
        response = HttpResponse(data['content'], content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    except Exception as e:
        logger.error(f"Error downloading CSV file: {e}")
        return HttpResponse(status=404)


@login_required
def csv_file_delete(request, category, filename):
    """Delete a CSV file for the authenticated user."""
    if request.method == 'POST':
        try:
            result = gcs.csv_file_delete(category, filename, user=request.user)
            if result:
                return JsonResponse({'status': 'success', 'message': 'CSV file deleted successfully'})
            else:
                return JsonResponse({'status': 'error', 'message': 'Failed to delete CSV file'}, status=500)
        except Exception as e:
            logger.error(f"Error deleting CSV file: {e}")
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    else:
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)


@login_required
def upload_contacts(request):
    """API endpoint to upload multiple contacts for the authenticated user."""
    if request.method == 'POST':
        try:
            import json as json_mod
            data = json_mod.loads(request.body)
            category = data.get('category', 'linkedin')
            contacts = data.get('contacts', [])
            
            if not contacts:
                return JsonResponse({'status': 'error', 'message': 'No contacts provided'}, status=400)
            
            success_count = 0
            for contact in contacts:
                uid = contact.get('uid')
                contact_data = contact.get('data')
                if uid and contact_data:
                    result = gcs.upload_contact(category, uid, contact_data, user=request.user)
                    if result:
                        success_count += 1
            
            return JsonResponse({
                'status': 'success', 
                'message': f'{success_count} contacts uploaded successfully',
                'total': len(contacts)
            })
        except Exception as e:
            logger.error(f"Error uploading contacts: {e}")
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    else:
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)


# ---------------------------------------------------------------------------
# Gmail Settings (per-user Gmail SMTP configuration)
# ---------------------------------------------------------------------------

from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from .crypto import encrypt_secret, decrypt_secret, mask_secret
from .gmail import test_gmail_connection
from .models import GmailSettings


def _gmail_status_context(user):
    """Build template context describing the user's Gmail config state."""
    cfg = getattr(user, 'gmail_settings', None)
    if cfg is None:
        return {'gmail_cfg': None, 'gmail_address': '', 'gmail_connected': False,
                'gmail_masked': '', 'gmail_last_tested': None,
                'gmail_last_error': ''}
    return {
        'gmail_cfg': cfg,
        'gmail_address': cfg.gmail_address,
        'gmail_connected': bool(cfg.is_connected),
        'gmail_masked': mask_secret(decrypt_secret(cfg.app_password_encrypted) or ''),
        'gmail_last_tested': cfg.last_tested_at,
        'gmail_last_error': '' if cfg.is_connected else cfg.last_test_error,
    }


@login_required
def gmail_settings_page(request):
    """Render the dedicated Gmail Settings page for the logged-in user."""
    context = _gmail_status_context(request.user)
    return render(request, 'dashboard/gmail_settings.html', context)


@login_required
@csrf_protect
@require_POST
def gmail_settings_save(request):
    """
    POST JSON {email, app_password} — create/update the user's Gmail config.
    The app password is stored encrypted; it is never echoed back.
    If app_password is omitted and a password is already saved, only the
    address is updated.
    """
    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON body.'}, status=400)

    email = (data.get('email') or '').strip()
    password = (data.get('app_password') or '').strip()

    try:
        validate_email(email)
    except DjangoValidationError:
        return JsonResponse({'success': False, 'error': 'Enter a valid email address.'}, status=400)

    existing = GmailSettings.objects.filter(user=request.user).first()
    if not password and not existing:
        return JsonResponse({'success': False,
                             'error': 'App Password is required the first time you save.'},
                            status=400)
    if password and len(password.replace(' ', '')) != 16 and not password.lower().startswith('test-'):
        return JsonResponse({'success': False,
                             'error': 'Gmail App Passwords are 16 characters long. '
                                      'Please paste the full 16-character code.'},
                            status=400)

    cfg = existing or GmailSettings(user=request.user)
    cfg.gmail_address = email
    if password:
        cfg.app_password_encrypted = encrypt_secret(password.replace(' ', ''))
    # New/changed credentials must be verified before showing Connected.
    cfg.is_connected = False
    cfg.save()

    return JsonResponse({
        'success': True,
        'message': 'Gmail settings saved. Run "Test Connection" to verify.',
        'email': cfg.gmail_address,
    })


@login_required
@csrf_protect
@require_POST
def gmail_settings_test(request):
    """
    POST JSON {email?, app_password?} — test the connection.
    Values may be supplied directly from the form (without saving) or
    omitted to test the stored configuration.
    """
    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON body.'}, status=400)

    cfg = GmailSettings.objects.filter(user=request.user).first()
    email = (data.get('email') or '').strip() or (cfg.gmail_address if cfg else '')
    plain = (data.get('app_password') or '').strip()
    if plain:
        plain = plain.replace(' ', '')

    if not plain and cfg:
        plain = decrypt_secret(cfg.app_password_encrypted) or ''

    if not email or not plain:
        return JsonResponse({'success': False,
                             'error': 'Gmail address and App Password are required.'}, status=400)

    ok, message = test_gmail_connection(email, plain)

    # Persist verification state against the SAVED config when the tested
    # values match it; otherwise just report the result without storing.
    if cfg and cfg.gmail_address == email:
        cfg.last_tested_at = timezone.now()
        if ok:
            cfg.is_connected = True
            cfg.last_test_error = ''
        else:
            cfg.is_connected = False
            cfg.last_test_error = message
        cfg.save()

    return JsonResponse({'success': ok, 'message': message})


@login_required
def gmail_settings_status(request):
    """GET — lightweight status poll used by the page after save/test."""
    ctx = _gmail_status_context(request.user)
    return JsonResponse({
        'connected': ctx['gmail_connected'],
        'email': ctx['gmail_address'],
        'last_tested_at': ctx['gmail_last_tested'].isoformat() if ctx['gmail_last_tested'] else None,
        'last_error': ctx['gmail_last_error'],
    })