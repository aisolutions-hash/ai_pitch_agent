import csv
import json
import logging
import os
import threading
from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.conf import settings
from datetime import datetime
import google.generativeai as genai

from dashboard.gcs import upload_contact
from dashboard import gcs
from .sheets_util import append_profile as sheets_append_profile
from .sheets_util import update_profile as sheets_update_profile
from .sheets_util import delete_profile as sheets_delete_profile
from .sheets_util import get_all_profiles as sheets_get_all_profiles
from .services import (
    _serpapi_linkedin_profile,
    _serpapi_linkedin_search,
    _parse_linkedin_title,
    _extract_profile_fields,
    fetch_linkedin_profile_by_url,
    analyze_profile_record,
    build_contact_data,
    run_daily_scrape,
)

logger = logging.getLogger(__name__)

# Configure Gemini API
genai.configure(api_key=settings.GEMINI_API_KEY)

# --- CSV Storage Configuration ---
CSV_DIR = os.path.join(settings.BASE_DIR, 'scraped_contacts')
CSV_PATH = os.path.join(CSV_DIR, 'linkedin_contacts.csv')

CSV_HEADERS = [
    'Timestamp', 'Name', 'Company', 'Headline', 'Location',
    'LinkedIn URL', 'Profile Snippet', 'Intent', 'Pain Points',
    'AI Solution Need Score', 'AI Need Reason', 'Branding Need Score',
    'Branding Need Reason', 'Pitch Angle', 'Post Insights',
    'LinkedIn Pitch', 'Email Subject', 'Email Body', 'WhatsApp Pitch'
]


def _ensure_csv():
    """Create CSV file with headers if it doesn't exist."""
    os.makedirs(CSV_DIR, exist_ok=True)
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADERS)


def _append_csv(row):
    """Append a single row to the CSV."""
    _ensure_csv()
    with open(CSV_PATH, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(row)


def _update_csv_by_url(linkedin_url, updated_row):
    """Find a row by LinkedIn URL and replace it with updated data."""
    _ensure_csv()
    rows = []
    found = False
    with open(CSV_PATH, 'r', newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        headers = next(reader, None)
        rows.append(headers or CSV_HEADERS)
        for row in reader:
            if len(row) > 5 and row[5] == linkedin_url:
                rows.append(updated_row)
                found = True
            else:
                rows.append(row)
    if not found:
        rows.append(updated_row)
    with open(CSV_PATH, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerows(rows)


# NOTE: SerpAPI/Gemini pipeline helpers live in scraper/services.py and are
# imported above (kept here as imported names for backward compatibility).


def scraper_home(request):
    """Render the scraper homepage."""
    return render(request, 'scraper/index.html', {})


def search_profile(request):
    """
    Search for LinkedIn profiles by name/query or direct LinkedIn URL using SerpAPI.
    GET param: q (search query or LinkedIn profile URL)
    Returns: JsonResponse with list of profiles (title, link, snippet, position, company, location, education, about, skills)
    """
    try:
        query = request.GET.get('q', '').strip()
        if not query:
            return JsonResponse({'error': 'Query parameter is required'}, status=400)

        if 'linkedin.com/in/' in query.lower():
            profiles = fetch_linkedin_profile_by_url(query)
            return JsonResponse({"profiles": profiles})

        profiles = _serpapi_linkedin_search(query, num=10)
        profiles = _extract_profile_fields(profiles)
        return JsonResponse({"profiles": profiles})
    except Exception as e:
        logger.error(f"Error searching profiles: {e}")
        return JsonResponse({'error': str(e)}, status=500)


def search_domain(request):
    """
    Search for LinkedIn profiles by domain and area using SerpAPI.
    GET params: domain, area
    Returns: JsonResponse with list of profiles (title, link, snippet, position, company, location, education, about, skills)
    """
    try:
        domain = request.GET.get('domain', '').strip()
        area = request.GET.get('area', '').strip()

        if not domain or not area:
            return JsonResponse({'error': 'Both domain and area parameters are required'}, status=400)

        profiles = _serpapi_linkedin_search(f'"{domain}" "{area}"', num=10)
        profiles = _extract_profile_fields(profiles)
        return JsonResponse({"profiles": profiles})
    except Exception as e:
        logger.error(f"Error searching domain profiles: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def analyze_profile(request):
    """
    Analyze a LinkedIn profile using Gemini AI, search recent posts,
    auto-generate LinkedIn pitch, and save to CSV.
    POST JSON: name, headline, company, location, snippet, link
    Returns: JsonResponse with intent analysis, post insights, LinkedIn pitch
    """
    try:
        if request.method != 'POST':
            return JsonResponse({'error': 'POST method required'}, status=400)
        
        body = json.loads(request.body)
        name = body.get('name', '')
        headline = body.get('headline', '')
        company = body.get('company', '')
        location = body.get('location', '')
        snippet = body.get('snippet', '')
        linkedin_url = body.get('link', '')
        education = body.get('education', '')
        about = body.get('about', '')
        skills = body.get('skills', [])

        # Run the shared analysis pipeline (posts fetch + Gemini + JSON parse)
        try:
            analysis = analyze_profile_record(
                name=name, headline=headline, company=company, location=location,
                snippet=snippet, linkedin_url=linkedin_url, education=education,
                about=about, skills=skills,
            )
        except RuntimeError as analysis_error:
            status = 504 if 'timed out' in str(analysis_error) else 500
            return JsonResponse({'error': str(analysis_error)}, status=status)
        
        # Auto-save to CSV
        try:
            row = [
                datetime.now().isoformat(),
                name,
                company,
                headline,
                location,
                linkedin_url,
                snippet,
                analysis.get('intent', ''),
                ', '.join(analysis.get('pain_points', [])),
                analysis.get('ai_need_score', 0),
                analysis.get('ai_need_reason', ''),
                analysis.get('branding_need_score', 0),
                analysis.get('branding_need_reason', ''),
                analysis.get('pitch_angle', ''),
                analysis.get('post_insights', ''),
                analysis.get('linkedin_pitch', ''),
                '', '', ''
            ]
            _append_csv(row)
            logger.info(f"Profile saved to CSV: {name}")
        except Exception as csv_error:
            logger.warning(f"Failed to save to CSV: {csv_error}")
        
        # Auto-save to Google Sheets if configured
        if settings.LINKEDIN_SHEET_ID:
            try:
                sheet_data = {
                    'name': name,
                    'company': company,
                    'location': location,
                    'linkedin_url': linkedin_url,
                    'intent': analysis.get('intent', ''),
                    'pain_points': analysis.get('pain_points', []),
                    'ai_need_score': analysis.get('ai_need_score', 0),
                    'branding_need_score': analysis.get('branding_need_score', 0),
                    'email': '',
                    'phone': '',
                    'pitch_linkedin': analysis.get('linkedin_pitch', ''),
                    'pitch_email': '',
                    'pitch_whatsapp': '',
                    'industry': analysis.get('industry', ''),
                    'seniority_level': analysis.get('seniority_level', ''),
                    'company_size': analysis.get('company_size', ''),
                    'contact_priority': 'medium',
                    'created_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                }
                sheets_append_profile(settings.LINKEDIN_SHEET_ID, sheet_data)
                logger.info(f"Profile saved to Google Sheets: {name}")
            except Exception as sheet_error:
                logger.warning(f"Failed to save to Google Sheets: {sheet_error}")
        
        # Auto-save to GCS so it appears in Dashboard -> LinkedIn Contacts
        try:
            uid = linkedin_url.rstrip('/').split('/')[-1] if linkedin_url else name.replace(' ', '-').lower()
            contact_data = build_contact_data(
                name=name, company=company, headline=headline, location=location,
                linkedin_url=linkedin_url, snippet=snippet, analysis=analysis,
            )
            upload_contact('linkedin', uid, contact_data)
            logger.info(f"Profile saved to GCS: {name}")
        except Exception as gcs_error:
            logger.warning(f"Failed to save to GCS: {gcs_error}")
        
        return JsonResponse(analysis)
    except Exception as e:
        logger.error(f"Error analyzing profile: {e}")
        return JsonResponse({'error': f'Analysis failed: {str(e)}'}, status=500)


@csrf_exempt
def generate_pitch(request):
    """
    Generate a sales pitch using Gemini AI.
    POST JSON: name, headline, company, intent, pain_points[], pitch_angle, channels[]
    Returns: JsonResponse with pitches for each channel
    """
    try:
        if request.method != 'POST':
            return JsonResponse({'error': 'POST method required'}, status=400)
        
        body = json.loads(request.body)
        name = body.get('name', '')
        headline = body.get('headline', '')
        company = body.get('company', '')
        intent = body.get('intent', '')
        pain_points = body.get('pain_points', [])
        pitch_angle = body.get('pitch_angle', '')
        channels = body.get('channels', ['linkedin', 'email'])
        
        pitches = {}
        
        try:
            model = genai.GenerativeModel('gemini-2.5-flash')
        except Exception as model_error:
            logger.error(f"Model initialization error: {model_error}")
            return JsonResponse({'error': f'AI model not available: {str(model_error)}'}, status=500)
        
        # Generate LinkedIn pitch
        if 'linkedin' in channels:
            linkedin_prompt = f"""Create a professional LinkedIn message pitch for:

Target: {name} ({headline} at {company})
Intent: {intent}
Pain Points: {', '.join(pain_points)}
Pitch Angle: {pitch_angle}

Write a compelling, personalized LinkedIn message that:
- Acknowledges their role and company
- References their pain points
- Offers a solution
- Has a clear call-to-action
- Is under 100 words MAXIMUM

Return ONLY the message text, no other commentary."""
            
            response = model.generate_content(
                linkedin_prompt,
                request_options={'timeout': 120.0}
            )
            pitches['linkedin'] = response.text.strip()
        
        # Generate WhatsApp pitch
        if 'whatsapp' in channels:
            whatsapp_prompt = f"""Create a brief WhatsApp message pitch for:

Target: {name}
Intent: {intent}
Pain Points: {', '.join(pain_points)}
Pitch Angle: {pitch_angle}

Write a casual but professional WhatsApp message that:
- Opens with a quick introduction
- Mentions one key pain point
- Offers a quick solution
- Invites a brief chat
- Is under 250 words MAXIMUM

Return ONLY the message text, no other commentary."""
            
            response = model.generate_content(
                whatsapp_prompt,
                request_options={'timeout': 120.0}
            )
            pitches['whatsapp'] = response.text.strip()
        
        # Generate Email pitch
        if 'email' in channels:
            email_prompt = f"""Create a professional email pitch for:

Target: {name} ({headline} at {company})
Intent: {intent}
Pain Points: {', '.join(pain_points)}
Pitch Angle: {pitch_angle}

Return a JSON object with:
{{
    "subject": "compelling email subject line",
    "body": "professional email body with HTML formatting using <p>, <strong>, <ul>, <li> tags, under 250 words MAXIMUM"
}}

Return ONLY valid JSON, no other text."""
            
            response = model.generate_content(
                email_prompt,
                request_options={'timeout': 120.0}
            )
            
            response_text = response.text.strip()
            if response_text.startswith('```'):
                response_text = response_text.split('```')[1]
                if response_text.startswith('json'):
                    response_text = response_text[4:]
            response_text = response_text.strip()
            
            email_data = json.loads(response_text)
            pitches['email'] = email_data
        
        return JsonResponse(pitches)
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing Gemini response: {e}")
        return JsonResponse({'error': 'Failed to parse pitch response - invalid JSON from AI'}, status=500)
    except Exception as e:
        logger.error(f"Error generating pitch: {e}")
        return JsonResponse({'error': f'Pitch generation failed: {str(e)}'}, status=500)


@csrf_exempt
def save_to_contacts(request):
    """
    Save a profile, analysis, and pitch to contacts in GCS and Google Sheets.
    POST JSON: profile_data, analysis, pitches
    Returns: JsonResponse with success status
    """
    try:
        if request.method != 'POST':
            return JsonResponse({'error': 'POST method required'}, status=400)
        
        body = json.loads(request.body)
        profile_data = body.get('profile_data', {})
        analysis = body.get('analysis', {})
        pitches = body.get('pitches', {})
        
        # Extract LinkedIn profile URL to generate UID
        linkedin_url = profile_data.get('link', '')
        # Use last part of LinkedIn URL as UID
        uid = linkedin_url.rstrip('/').split('/')[-1] if linkedin_url else 'contact'
        
        # Combine all data for GCS
        # Use parsed fields if available, otherwise fall back to title parsing
        contact_data = {
            'name': profile_data.get('name', profile_data.get('title', '')),
            'company': profile_data.get('company', ''),
            'headline': profile_data.get('headline', ''),
            'location': profile_data.get('location', ''),
            'linkedin_url': linkedin_url,
            'snippet': profile_data.get('snippet', ''),
            'intent': analysis.get('intent', ''),
            'pain_points': analysis.get('pain_points', []),
            'ai_need_score': analysis.get('ai_need_score', 0),
            'branding_need_score': analysis.get('branding_need_score', 0),
            'pitch_angle': analysis.get('pitch_angle', ''),
            'pitches': pitches
        }
        
        # Upload to GCS - make it optional
        gcs_result = False
        try:
            gcs_result = upload_contact('linkedin', uid, contact_data)
        except Exception as gcs_error:
            logger.warning(f"GCS upload failed (will continue with Sheets): {gcs_error}")
        
        # Also save to Google Sheets if LINKEDIN_SHEET_ID is configured
        sheet_result = False
        if settings.LINKEDIN_SHEET_ID:
            try:
                # Format data for Google Sheets (keys must match sheets_util.HEADERS)
                sheet_data = {
                    'name': profile_data.get('name', profile_data.get('title', '')),
                    'company': profile_data.get('company', ''),
                    'location': profile_data.get('location', ''),
                    'linkedin_url': linkedin_url,
                    'intent': analysis.get('intent', ''),
                    'pain_points': analysis.get('pain_points', []),
                    'ai_need_score': analysis.get('ai_need_score', 0),
                    'branding_need_score': analysis.get('branding_need_score', 0),
                    'email': profile_data.get('email', ''),
                    'phone': profile_data.get('phone', ''),
                    'pitch_linkedin': pitches.get('linkedin', ''),
                    'pitch_email': json.dumps(pitches.get('email', {})) if isinstance(pitches.get('email'), dict) else pitches.get('email', ''),
                    'pitch_whatsapp': pitches.get('whatsapp', ''),
                    'industry': analysis.get('industry', ''),
                    'seniority_level': analysis.get('seniority_level', ''),
                    'company_size': analysis.get('company_size', ''),
                    'contact_priority': 'medium',
                    'created_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                }
                
                sheet_result = sheets_append_profile(settings.LINKEDIN_SHEET_ID, sheet_data)
                logger.info(f"Profile saved to Google Sheets: {linkedin_url}")
            except Exception as e:
                logger.warning(f"Failed to save to Google Sheets: {e}")
                sheet_result = False
        
        # Also save/update CSV with complete data (including email/whatsapp pitches)
        try:
            email_data = pitches.get('email', {})
            email_subject = email_data.get('subject', '') if isinstance(email_data, dict) else ''
            email_body = email_data.get('body', '') if isinstance(email_data, dict) else ''
            csv_row = [
                datetime.now().isoformat(),
                profile_data.get('name', profile_data.get('title', '')),
                profile_data.get('company', ''),
                profile_data.get('headline', ''),
                profile_data.get('location', ''),
                linkedin_url,
                profile_data.get('snippet', ''),
                analysis.get('intent', ''),
                ', '.join(analysis.get('pain_points', [])),
                analysis.get('ai_need_score', 0),
                analysis.get('ai_need_reason', ''),
                analysis.get('branding_need_score', 0),
                analysis.get('branding_need_reason', ''),
                analysis.get('pitch_angle', ''),
                analysis.get('post_insights', ''),
                pitches.get('linkedin', analysis.get('linkedin_pitch', '')),
                email_subject,
                email_body,
                pitches.get('whatsapp', '')
            ]
            _update_csv_by_url(linkedin_url, csv_row)
            logger.info(f"CSV updated for: {profile_data.get('name')}")
        except Exception as csv_error:
            logger.warning(f"Failed to update CSV: {csv_error}")
        
        # Return success if either GCS or Sheets succeeded (prefer Sheets as primary)
        if sheet_result or gcs_result:
            message = 'Contact saved successfully'
            saved_to = []
            if sheet_result:
                saved_to.append('Google Sheets')
            if gcs_result:
                saved_to.append('GCS')
            if saved_to:
                message += f' ({", ".join(saved_to)})'
            
            return JsonResponse({'success': True, 'message': message, 'uid': uid})
        else:
            return JsonResponse({'error': 'Failed to save contact - check logs for details'}, status=500)
    except Exception as e:
        logger.error(f"Error saving contact: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def update_contact(request):
    """
    Update an existing profile in GCS and Google Sheets.
    POST JSON: linkedin_url, updated_data (analysis, pitches, etc.)
    Returns: JsonResponse with success status
    """
    try:
        if request.method != 'POST':
            return JsonResponse({'error': 'POST method required'}, status=400)
        
        body = json.loads(request.body)
        linkedin_url = body.get('linkedin_url', '')
        updated_data = body.get('updated_data', {})
        
        if not linkedin_url:
            return JsonResponse({'error': 'linkedin_url is required'}, status=400)
        
        # Extract UID from LinkedIn URL
        uid = linkedin_url.rstrip('/').split('/')[-1]
        
        # Update in Google Sheets if configured
        sheets_updated = False
        if settings.LINKEDIN_SHEET_ID:
            try:
                sheets_updated = sheets_update_profile(settings.LINKEDIN_SHEET_ID, linkedin_url, updated_data)
                logger.info(f"Profile updated in Google Sheets: {linkedin_url}")
            except Exception as e:
                logger.warning(f"Failed to update Google Sheets: {e}")
        
        return JsonResponse({
            'success': True,
            'message': f'Profile updated successfully',
            'sheets_updated': sheets_updated
        })
    except Exception as e:
        logger.error(f"Error updating profile: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def delete_contact(request):
    """
    Delete a profile from GCS and Google Sheets.
    POST JSON: linkedin_url
    Returns: JsonResponse with success status
    """
    try:
        if request.method != 'POST':
            return JsonResponse({'error': 'POST method required'}, status=400)
        
        body = json.loads(request.body)
        linkedin_url = body.get('linkedin_url', '')
        
        if not linkedin_url:
            return JsonResponse({'error': 'linkedin_url is required'}, status=400)
        
        # Extract UID from LinkedIn URL
        uid = linkedin_url.rstrip('/').split('/')[-1]
        
        # Delete from Google Sheets if configured
        sheets_deleted = False
        if settings.LINKEDIN_SHEET_ID:
            try:
                sheets_deleted = sheets_delete_profile(settings.LINKEDIN_SHEET_ID, linkedin_url)
                logger.info(f"Profile deleted from Google Sheets: {linkedin_url}")
            except Exception as e:
                logger.warning(f"Failed to delete from Google Sheets: {e}")
        
        return JsonResponse({
            'success': True,
            'message': f'Profile deleted successfully',
            'sheets_deleted': sheets_deleted
        })
    except Exception as e:
        logger.error(f"Error deleting profile: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def get_all_contacts(request):
    """
    Retrieve all saved LinkedIn profiles from Google Sheets.
    GET request
    Returns: JsonResponse with list of all profiles
    """
    try:
        if not settings.LINKEDIN_SHEET_ID:
            return JsonResponse({
                'success': False,
                'error': 'LINKEDIN_SHEET_ID not configured'
            }, status=400)
        
        profiles = sheets_get_all_profiles(settings.LINKEDIN_SHEET_ID)
        return JsonResponse({
            'success': True,
                'profiles': profiles,
            'count': len(profiles)
        })
    except Exception as e:
        logger.error(f"Error retrieving all contacts: {e}")
        return JsonResponse({'error': str(e)}, status=500)


def download_csv(request):
    """
    Download the scraped contacts CSV file.
    """
    _ensure_csv()
    if not os.path.exists(CSV_PATH):
        return JsonResponse({'error': 'No contacts data found'}, status=404)
    
    with open(CSV_PATH, 'r', encoding='utf-8') as f:
        csv_content = f.read()
    
    response = HttpResponse(csv_content, content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="linkedin_contacts_{datetime.now().strftime("%Y%m%d")}.csv"'
    return response


def check_api_status(request):
    """
    Check if required API keys are configured
    GET request
    Returns: JsonResponse with API configuration status
    """
    status = {
        'gemini_api_key': bool(settings.GEMINI_API_KEY),
        'serpapi_api_key': bool(settings.SERPAPI_API_KEY),
        'google_sheets_id': bool(settings.LINKEDIN_SHEET_ID),
        'all_keys_present': all([
            settings.GEMINI_API_KEY,
            settings.SERPAPI_API_KEY
        ])
    }
    return JsonResponse(status)


# ---------------------------------------------------------------------------
# Scheduled Scraper endpoints (keywords config, run history, manual/scheduled runs)
# ---------------------------------------------------------------------------

def scrape_keywords_list(request):
    """GET — list configured scrape keywords (from GCS config)."""
    try:
        keywords = gcs.get_scrape_keywords()
        return JsonResponse({'success': True, 'keywords': keywords})
    except Exception as e:
        logger.error(f"Error listing scrape keywords: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@require_POST
def scrape_keyword_add(request):
    """POST JSON {keyword} — add a new scrape keyword."""
    try:
        body = json.loads(request.body)
        keyword = (body.get('keyword') or '').strip()
        if not keyword:
            return JsonResponse({'success': False, 'error': 'Keyword cannot be empty'}, status=400)

        keywords = gcs.get_scrape_keywords()
        if any(k['keyword'].lower() == keyword.lower() for k in keywords):
            return JsonResponse({'success': False, 'error': 'Keyword already exists'}, status=400)

        keywords.append({
            'keyword': keyword,
            'active': True,
            'created_at': datetime.now().isoformat(),
        })
        if not gcs.save_scrape_keywords(keywords):
            return JsonResponse({'success': False, 'error': 'Failed to save keywords to GCS'}, status=500)
        return JsonResponse({'success': True, 'keywords': keywords})
    except Exception as e:
        logger.error(f"Error adding scrape keyword: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@require_POST
def scrape_keyword_toggle(request):
    """POST JSON {keyword} — toggle a keyword's active flag."""
    try:
        body = json.loads(request.body)
        keyword = (body.get('keyword') or '').strip()
        keywords = gcs.get_scrape_keywords()
        found = False
        for k in keywords:
            if k['keyword'].lower() == keyword.lower():
                k['active'] = not k.get('active', True)
                found = True
                break
        if not found:
            return JsonResponse({'success': False, 'error': 'Keyword not found'}, status=404)
        if not gcs.save_scrape_keywords(keywords):
            return JsonResponse({'success': False, 'error': 'Failed to save keywords to GCS'}, status=500)
        return JsonResponse({'success': True, 'keywords': keywords})
    except Exception as e:
        logger.error(f"Error toggling scrape keyword: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@require_POST
def scrape_keyword_delete(request):
    """POST JSON {keyword} — delete a scrape keyword."""
    try:
        body = json.loads(request.body)
        keyword = (body.get('keyword') or '').strip()
        keywords = gcs.get_scrape_keywords()
        new_keywords = [k for k in keywords if k['keyword'].lower() != keyword.lower()]
        if len(new_keywords) == len(keywords):
            return JsonResponse({'success': False, 'error': 'Keyword not found'}, status=404)
        if not gcs.save_scrape_keywords(new_keywords):
            return JsonResponse({'success': False, 'error': 'Failed to save keywords to GCS'}, status=500)
        return JsonResponse({'success': True, 'keywords': new_keywords})
    except Exception as e:
        logger.error(f"Error deleting scrape keyword: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def scrape_locations_list(request):
    """GET — list configured scrape locations (from GCS config)."""
    try:
        locations = gcs.get_scrape_locations()
        return JsonResponse({'success': True, 'locations': locations})
    except Exception as e:
        logger.error(f"Error listing scrape locations: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@require_POST
def scrape_location_add(request):
    """POST JSON {location} — add a new scrape location."""
    try:
        body = json.loads(request.body)
        location = (body.get('location') or '').strip()
        if not location:
            return JsonResponse({'success': False, 'error': 'Location cannot be empty'}, status=400)

        locations = gcs.get_scrape_locations()
        if any(l['location'].lower() == location.lower() for l in locations):
            return JsonResponse({'success': False, 'error': 'Location already exists'}, status=400)

        locations.append({
            'location': location,
            'active': True,
            'created_at': datetime.now().isoformat(),
        })
        if not gcs.save_scrape_locations(locations):
            return JsonResponse({'success': False, 'error': 'Failed to save locations to GCS'}, status=500)
        return JsonResponse({'success': True, 'locations': locations})
    except Exception as e:
        logger.error(f"Error adding scrape location: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@require_POST
def scrape_location_toggle(request):
    """POST JSON {location} — toggle a location's active flag."""
    try:
        body = json.loads(request.body)
        location = (body.get('location') or '').strip()
        locations = gcs.get_scrape_locations()
        found = False
        for l in locations:
            if l['location'].lower() == location.lower():
                l['active'] = not l.get('active', True)
                found = True
                break
        if not found:
            return JsonResponse({'success': False, 'error': 'Location not found'}, status=404)
        if not gcs.save_scrape_locations(locations):
            return JsonResponse({'success': False, 'error': 'Failed to save locations to GCS'}, status=500)
        return JsonResponse({'success': True, 'locations': locations})
    except Exception as e:
        logger.error(f"Error toggling scrape location: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@require_POST
def scrape_location_delete(request):
    """POST JSON {location} — delete a scrape location."""
    try:
        body = json.loads(request.body)
        location = (body.get('location') or '').strip()
        locations = gcs.get_scrape_locations()
        new_locations = [l for l in locations if l['location'].lower() != location.lower()]
        if len(new_locations) == len(locations):
            return JsonResponse({'success': False, 'error': 'Location not found'}, status=404)
        if not gcs.save_scrape_locations(new_locations):
            return JsonResponse({'success': False, 'error': 'Failed to save locations to GCS'}, status=500)
        return JsonResponse({'success': True, 'locations': new_locations})
    except Exception as e:
        logger.error(f"Error deleting scrape location: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def scrape_runs_list(request):
    """GET — list historical scrape runs from GCS (newest first)."""
    try:
        runs = gcs.list_scrape_runs()
        return JsonResponse({'success': True, 'runs': runs})
    except Exception as e:
        logger.error(f"Error listing scrape runs: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def scrape_run_detail(request):
    """GET ?path=<blob_path> — fetch a single scrape-run batch (profiles + messages)."""
    try:
        run_path = request.GET.get('path', '')
        run = gcs.get_scrape_run(run_path)
        if run is None:
            return JsonResponse({'success': False, 'error': 'Run not found'}, status=404)
        return JsonResponse({'success': True, 'run': run})
    except Exception as e:
        logger.error(f"Error fetching scrape run detail: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def _start_background_scrape(keywords=None, locations=None, trigger='manual'):
    """Kick off run_daily_scrape in a daemon thread and return the thread."""
    def _target():
        try:
            summaries = run_daily_scrape(keywords=keywords, locations=locations, trigger=trigger)
            ok = sum(1 for s in summaries if s.get('status') == 'success')
            logger.info(f"Background scrape finished: {ok}/{len(summaries)} jobs succeeded")
        except Exception as e:
            logger.error(f"Background scrape failed: {e}", exc_info=True)

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    return thread


@csrf_exempt
@require_POST
def run_scrape_now(request):
    """
    POST (login required) — manually trigger the daily scrape in the background.
    Optional JSON body {keyword} to run a single keyword, or {location} to
    restrict locations.
    """
    try:
        keyword = None
        location = None
        if request.body:
            try:
                body = json.loads(request.body)
                keyword = (body.get('keyword') or '').strip() or None
                location = (body.get('location') or '').strip() or None
            except json.JSONDecodeError:
                keyword = None
                location = None

        _start_background_scrape(
            keywords=[keyword] if keyword else None,
            locations=[location] if location else None,
            trigger='manual',
        )
        return JsonResponse({
            'success': True,
            'message': f"Scrape started in background{f' for: {keyword}' if keyword else ' for all active keywords'}"
                       f"{f' in {location}' if location else ' (all active locations)'}. Results will appear in Run History shortly."
        })
    except Exception as e:
        logger.error(f"Error starting manual scrape: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
def scheduler_run(request):
    """
    Scheduler endpoint (no login — exempted in middleware, token-protected).
    Called daily by Cloud Scheduler (or any cron) with the shared secret:
      - header:  X-Scheduler-Secret: <SCHEDULER_SECRET>
      - or GET param: ?token=<SCHEDULER_SECRET>
    Starts the scrape in the background and returns immediately.
    """
    secret = getattr(settings, 'SCHEDULER_SECRET', '')
    if not secret:
        return JsonResponse({'success': False, 'error': 'Scheduler is not configured (SCHEDULER_SECRET missing).'}, status=503)

    provided = request.headers.get('X-Scheduler-Secret') or request.GET.get('token', '')
    if provided != secret:
        return JsonResponse({'success': False, 'error': 'Invalid scheduler token.'}, status=403)

    _start_background_scrape(trigger='scheduler')
    return JsonResponse({'success': True, 'message': 'Daily scrape started in background.'})


def scrape_progress(request):
    """GET — live progress of the current/last scrape run (for the dashboard progress bar)."""
    progress = gcs.get_scrape_progress()
    if progress is None:
        progress = {'state': 'idle'}
    return JsonResponse(progress)


def scrape_stats(request):
    """GET — aggregated stats for the dashboard tiles and bar charts."""
    try:
        entries = gcs.get_scrape_stats()

        today = datetime.now().date()
        total_profiles = sum(e.get('profiles_analyzed', 0) for e in entries)
        today_profiles = sum(
            e.get('profiles_analyzed', 0) for e in entries
            if e.get('date') == today.isoformat()
        )

        # Daily series for the last 7 days (bar chart)
        from datetime import timedelta
        days = [today - timedelta(days=i) for i in range(6, -1, -1)]
        daily = []
        for d in days:
            ds = d.isoformat()
            count = sum(e.get('profiles_analyzed', 0) for e in entries if e.get('date') == ds)
            daily.append({'date': ds, 'label': d.strftime('%a %d'), 'count': count})

        # Per-keyword totals (horizontal bars)
        per_kw = {}
        for e in entries:
            kw = e.get('keyword', '?')
            per_kw[kw] = per_kw.get(kw, 0) + e.get('profiles_analyzed', 0)
        per_keyword = [
            {'keyword': k, 'count': v}
            for k, v in sorted(per_kw.items(), key=lambda x: -x[1])
        ]

        # Per-location totals
        per_loc = {}
        for e in entries:
            loc = e.get('location') or 'No location'
            per_loc[loc] = per_loc.get(loc, 0) + e.get('profiles_analyzed', 0)
        per_location = [
            {'location': k, 'count': v}
            for k, v in sorted(per_loc.items(), key=lambda x: -x[1])
        ]

        active_keywords = len([k for k in gcs.get_scrape_keywords() if k.get('active')])
        active_locations = len([l for l in gcs.get_scrape_locations() if l.get('active')])

        return JsonResponse({
            'success': True,
            'totals': {
                'profiles': total_profiles,
                'today_profiles': today_profiles,
                'runs': len(entries),
                'active_keywords': active_keywords,
                'active_locations': active_locations,
            },
            'daily': daily,
            'per_keyword': per_keyword,
            'per_location': per_location,
        })
    except Exception as e:
        logger.error(f"Error computing scrape stats: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
