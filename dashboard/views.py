from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
import json
import logging
import mimetypes
from . import gcs

logger = logging.getLogger(__name__)


def home(request):
    categories = [
        {'name': 'linkedin', 'label': 'LinkedIn Contacts', 'color': 'blue'},
    ]
    combined_categories = [
        {'name': 'suppliers', 'label': 'Suppliers', 'color': 'amber'},
        {'name': 'buyers', 'label': 'Buyers', 'color': 'teal'},
        {'name': 'events', 'label': 'Events', 'color': 'purple'},
    ]
    return render(request, 'dashboard/index.html', {
        'categories': categories,
        'combined_categories': combined_categories,
    })


def contacts_list(request):
    """
    API endpoint to list contacts by category.
    GET params: category (linkedin/suppliers/buyers/events)
    Returns: JsonResponse with list of contact dicts
    """
    try:
        category = request.GET.get('category', '').lower()
        
        if not category:
            return JsonResponse({'error': 'category parameter is required'}, status=400)
        
        if category not in ['linkedin', 'suppliers', 'buyers', 'events']:
            return JsonResponse({'error': f'Invalid category: {category}'}, status=400)
        
        contacts = gcs.list_contacts(category)
        
        # If GCS is not available or returns None, return empty list instead of error
        if contacts is None:
            return JsonResponse([], safe=False)
        
        return JsonResponse(contacts, safe=False)
    except Exception as e:
        logger.error(f"Error listing contacts for {category}: {e}")
        # Return empty list on error to keep dashboard functional
        return JsonResponse([], safe=False)


def contacts_count(request):
    """
    API endpoint to get contact counts for all categories.
    Returns: JsonResponse with counts per category and total
    """
    try:
        categories = ['linkedin', 'suppliers', 'buyers', 'events']
        counts = {}
        total = 0
        
        for category in categories:
            try:
                contacts = gcs.list_contacts(category)
                if contacts is None:
                    counts[category] = 0
                else:
                    count = len(contacts)
                    counts[category] = count
                    total += count
            except Exception as e:
                logger.error(f"Error counting contacts for {category}: {e}")
                counts[category] = 0
        
        counts['total'] = total
        return JsonResponse(counts)
    except Exception as e:
        logger.error(f"Error getting contacts count: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def delete_contact(request):
    """
    API endpoint to delete a contact.
    POST JSON: category, uid
    Returns: JsonResponse with success status
    """
    try:
        if request.method != 'POST':
            return JsonResponse({'error': 'POST method required'}, status=400)
        
        body = json.loads(request.body)
        category = body.get('category', '').lower()
        uid = body.get('uid', '').strip()
        
        if not category or not uid:
            return JsonResponse({'error': 'Both category and uid are required'}, status=400)
        
        if category not in ['linkedin', 'suppliers', 'buyers', 'events']:
            return JsonResponse({'error': f'Invalid category: {category}'}, status=400)
        
        result = gcs.delete_contact(category, uid)
        
        if result is True:
            return JsonResponse({'success': True, 'message': 'Contact deleted successfully'})
        else:
            return JsonResponse({'error': 'Failed to delete contact'}, status=500)
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing JSON: {e}")
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error deleting contact: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def add_contact(request):
    """
    API endpoint to add a single contact.
    POST JSON: category, name, company, email, phone, linkedin_url, website, tags (array), notes
    Returns: JsonResponse with success status and new contact UID
    """
    try:
        if request.method != 'POST':
            return JsonResponse({'error': 'POST method required'}, status=400)
        
        body = json.loads(request.body)
        category = body.get('category', '').lower()
        
        if not category or category not in ['linkedin', 'suppliers', 'buyers', 'events']:
            return JsonResponse({'error': f'Invalid category: {category}'}, status=400)
        
        # Get required name field
        name = body.get('name', '').strip()
        if not name:
            return JsonResponse({'error': 'Name is required'}, status=400)
        
        # Build contact data
        contact_data = {
            'name': name,
            'company': body.get('company', '').strip(),
            'email': body.get('email', '').strip(),
            'phone': body.get('phone', '').strip(),
            'linkedin_url': body.get('linkedin_url', '').strip(),
            'website': body.get('website', '').strip(),
            'tags': body.get('tags', []) if isinstance(body.get('tags'), list) else [],
            'notes': body.get('notes', '').strip()
        }
        
        # Generate UID (using email as primary, fallback to name-based)
        if contact_data['email']:
            import hashlib
            uid = hashlib.md5(contact_data['email'].encode()).hexdigest()[:16]
        else:
            import uuid
            uid = str(uuid.uuid4())[:16]
        
        # Upload to GCS
        result = gcs.upload_contact(category, uid, contact_data)
        
        if result is True:
            return JsonResponse({
                'success': True,
                'message': 'Contact added successfully',
                'uid': uid
            })
        else:
            return JsonResponse({'error': 'Failed to add contact'}, status=500)
    
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing JSON: {e}")
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error adding contact: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def upload_contacts(request):
    """
    API endpoint to upload multiple contacts from CSV.
    POST: CSV file in request.FILES['file'], category in POST data
    Also stores the original CSV file in GCS under contacts/{category}/.
    Returns: JsonResponse with success status and count of uploaded contacts
    """
    try:
        if request.method != 'POST':
            return JsonResponse({'error': 'POST method required'}, status=400)
        
        category = request.POST.get('category', '').lower()
        
        if not category or category not in ['linkedin', 'suppliers', 'buyers', 'events']:
            return JsonResponse({'error': f'Invalid category: {category}'}, status=400)
        
        if 'file' not in request.FILES:
            return JsonResponse({'error': 'CSV file is required'}, status=400)
        
        csv_file = request.FILES['file']
        
        if not csv_file.name.endswith('.csv'):
            return JsonResponse({'error': 'Only CSV files are supported'}, status=400)
        
        # Store the original CSV file in GCS
        csv_stored = gcs.upload_csv_file(category, csv_file, csv_file.name)
        
        # Parse CSV for contact extraction (no longer requires data rows)
        import csv
        import io
        
        try:
            csv_file.seek(0)
            csv_content = csv_file.read().decode('utf-8')
            csv_reader = csv.DictReader(io.StringIO(csv_content))
            
            warnings = []
            uploaded_count = 0
            errors = []
            
            if not csv_reader.fieldnames:
                warnings.append('CSV file has no header row or is empty. No contacts were extracted.')
            else:
                rows_encountered = False
                for row_index, row in enumerate(csv_reader, 1):
                    rows_encountered = True
                    try:
                        # Normalize row keys to lowercase
                        row_lower = {k.lower().strip(): v.strip() if isinstance(v, str) else v for k, v in row.items()}
                        
                        # Check for required name field
                        name = row_lower.get('name', '').strip()
                        if not name:
                            errors.append(f"Row {row_index}: Missing required 'name' field, skipped")
                            continue
                        
                        # Build contact data
                        contact_data = {
                            'name': name,
                            'company': row_lower.get('company', '').strip(),
                            'email': row_lower.get('email', '').strip(),
                            'phone': row_lower.get('phone', '').strip(),
                            'linkedin_url': row_lower.get('linkedin_url', '').strip(),
                            'website': row_lower.get('website', '').strip(),
                            'tags': row_lower.get('tags', '').split(',') if row_lower.get('tags') else [],
                            'notes': row_lower.get('notes', '').strip()
                        }
                        
                        # Generate UID
                        if contact_data['email']:
                            import hashlib
                            uid = hashlib.md5(contact_data['email'].encode()).hexdigest()[:16]
                        else:
                            import uuid
                            uid = str(uuid.uuid4())[:16]
                        
                        # Upload to GCS
                        result = gcs.upload_contact(category, uid, contact_data)
                        if result is True:
                            uploaded_count += 1
                        else:
                            errors.append(f"Row {row_index}: Failed to upload contact '{name}'")
                    
                    except Exception as e:
                        errors.append(f"Row {row_index}: {str(e)}")
                
                if not rows_encountered:
                    warnings.append('CSV file has headers only. No data rows to extract contacts from.')
            
            return JsonResponse({
                'success': True,
                'csv_stored': bool(csv_stored),
                'csv_filename': csv_file.name,
                'uploaded_count': uploaded_count,
                'warnings': warnings,
                'errors': errors,
                'message': f'CSV saved. Extracted {uploaded_count} contact(s).'
            })
        
        except Exception as e:
            logger.error(f"Error parsing CSV: {e}")
            return JsonResponse({'error': f'Failed to parse CSV: {str(e)}'}, status=400)
    
    except Exception as e:
        logger.error(f"Error uploading contacts: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def csv_files_list(request):
    """
    API endpoint to list CSV files in a category.
    GET params: category (linkedin/suppliers/buyers/events)
    Returns: JsonResponse with list of CSV file info dicts
    """
    try:
        category = request.GET.get('category', '').lower()

        if not category:
            return JsonResponse({'error': 'category parameter is required'}, status=400)

        if category not in ['linkedin', 'suppliers', 'buyers', 'events']:
            return JsonResponse({'error': f'Invalid category: {category}'}, status=400)

        csv_files = gcs.list_csv_files(category)

        if csv_files is None:
            return JsonResponse([], safe=False)

        return JsonResponse(csv_files, safe=False)
    except Exception as e:
        logger.error(f"Error listing CSV files: {e}")
        return JsonResponse([], safe=False)


@csrf_exempt
def csv_files_count(request):
    """
    API endpoint to get CSV file counts for all categories.
    Returns: JsonResponse with counts per category and total
    """
    try:
        categories = ['linkedin', 'suppliers', 'buyers', 'events']
        counts = {}
        total = 0

        for category in categories:
            try:
                csv_files = gcs.list_csv_files(category)
                if csv_files is None:
                    counts[category] = 0
                else:
                    count = len(csv_files)
                    counts[category] = count
                    total += count
            except Exception as e:
                logger.error(f"Error counting CSV files for {category}: {e}")
                counts[category] = 0

        counts['total'] = total
        return JsonResponse(counts)
    except Exception as e:
        logger.error(f"Error getting CSV files count: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def csv_file_download(request, category, filename):
    """
    API endpoint to download a CSV file.
    GET: /api/csv/download/{category}/{filename}
    Returns: CSV file as download response
    """
    try:
        import urllib.parse
        filename = urllib.parse.unquote(filename)

        if category not in ['linkedin', 'suppliers', 'buyers', 'events']:
            return JsonResponse({'error': f'Invalid category: {category}'}, status=400)

        csv_data = gcs.get_csv_file(category, filename)
        if csv_data is None:
            return JsonResponse({'error': 'CSV file not found'}, status=404)

        response = HttpResponse(csv_data['content'], content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    except Exception as e:
        logger.error(f"Error downloading CSV file: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def csv_file_delete(request):
    """
    API endpoint to delete a CSV file.
    POST JSON: category, filename
    Returns: JsonResponse with success status
    """
    try:
        if request.method != 'POST':
            return JsonResponse({'error': 'POST method required'}, status=400)

        body = json.loads(request.body)
        category = body.get('category', '').lower()
        filename = body.get('filename', '').strip()

        if not category or not filename:
            return JsonResponse({'error': 'Both category and filename are required'}, status=400)

        if category not in ['linkedin', 'suppliers', 'buyers', 'events']:
            return JsonResponse({'error': f'Invalid category: {category}'}, status=400)

        result = gcs.delete_csv_file(category, filename)

        if result is True:
            return JsonResponse({'success': True, 'message': 'CSV file deleted successfully'})
        else:
            return JsonResponse({'error': 'Failed to delete CSV file'}, status=500)
    except json.JSONDecodeError as e:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error deleting CSV file: {e}")
        return JsonResponse({'error': str(e)}, status=500)
