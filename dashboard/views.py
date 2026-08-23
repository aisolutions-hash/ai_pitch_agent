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
    """
    if request.method == 'POST':
        try:
            import json as json_mod
            data = json_mod.loads(request.body)
            category = data.get('category', 'linkedin')
            uid = data.get('uid')
            contact_data = data.get('data')
            
            if not uid or not contact_data:
                return JsonResponse({'status': 'error', 'message': 'UID and data are required'}, status=400)
            
            result = gcs.upload_contact(category, uid, contact_data, user=request.user)
            if result:
                return JsonResponse({'status': 'success', 'message': 'Contact added successfully'})
            else:
                return JsonResponse({'status': 'error', 'message': 'Failed to add contact'}, status=500)
        except Exception as e:
            logger.error(f"Error adding contact: {e}")
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    else:
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)


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