import csv
import json
import logging
import os
import requests
import re
from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from datetime import datetime
import google.generativeai as genai

from dashboard.gcs import upload_contact
from .sheets_util import append_profile as sheets_append_profile
from .sheets_util import update_profile as sheets_update_profile
from .sheets_util import delete_profile as sheets_delete_profile
from .sheets_util import get_all_profiles as sheets_get_all_profiles

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


def _serpapi_linkedin_profile(linkedin_url):
    """
    Fetch full LinkedIn profile data using SerpAPI's LinkedIn Profile API.
    Returns structured data: name, headline, location, about, experience, education, skills.
    No cookies required — uses LinkedIn's public profile.
    """
    try:
        params = {
            "engine": "linkedin_profile",
            "url": linkedin_url,
            "api_key": settings.SERPAPI_API_KEY,
        }
        resp = requests.get("https://serpapi.com/search", params=params, timeout=15)
        data = resp.json()
        if data.get("error"):
            logger.warning(f"SerpAPI LinkedIn profile error: {data['error']}")
            return None

        profile = data.get("profile", data)
        name = profile.get("name", profile.get("title", ""))
        headline = profile.get("headline", profile.get("headline", ""))
        location = profile.get("location", "")
        about = profile.get("about", profile.get("summary", ""))
        education = profile.get("education", [])
        skills = [s.get("name", s) if isinstance(s, dict) else s for s in profile.get("skills", [])]

        experiences = profile.get("experience", []) or profile.get("positions", [])
        current_position = ""
        current_company = ""
        if experiences:
            exp = experiences[0]
            current_position = exp.get("title", exp.get("position", ""))
            current_company = exp.get("company", exp.get("company_name", ""))

        return {
            "title": f"{name} - {current_position} at {current_company} - {location}" if current_company else name,
            "link": linkedin_url,
            "snippet": about[:300] if about else headline,
            "position": current_position,
            "company": current_company,
            "location": location,
            "education": ", ".join([e.get("name", e.get("school_name", "")) if isinstance(e, dict) else str(e) for e in education]) if education else "",
            "about": about,
            "skills": skills
        }
    except Exception as e:
        logger.warning(f"SerpAPI LinkedIn profile API failed ({e})")
        return None


def _serpapi_linkedin_search(query, num=10):
    """
    Search LinkedIn via SerpAPI — tries LinkedIn Profile API for full profiles,
    falls back to LinkedIn search, then to Google search.
    """
    # Try direct profile fetch if query looks like a URL
    if "linkedin.com/in/" in query:
        profile = _serpapi_linkedin_profile(query)
        if profile:
            return [profile]

    # Attempt 1: SerpAPI LinkedIn search engine (public search, no cookies needed)
    try:
        parts = query.strip().split()
        params = {
            "engine": "linkedin",
            "api_key": settings.SERPAPI_API_KEY,
        }
        if parts:
            params["first_name"] = parts[0]
        if len(parts) > 1:
            params["last_name"] = " ".join(parts[1:])
        else:
            params["last_name"] = ""

        resp = requests.get("https://serpapi.com/search", params=params, timeout=10)
        data = resp.json()
        results = data.get('organic_results', []) or data.get('profiles', []) or data.get('people_results', [])

        profiles = []
        for r in results:
            link = r.get("profile_url", r.get("link", ""))
            if not link or "linkedin.com/in/" not in link:
                continue
            name = r.get("name", r.get("title", ""))
            headline = r.get("headline", r.get("occupation", ""))
            location = r.get("location", "")
            about = r.get("summary", r.get("about", ""))
            education = r.get("education", [])
            skills = [s.get("name", s) if isinstance(s, dict) else s for s in r.get("skills", [])]
            exp = (r.get("experience", []) or r.get("positions", []))
            position = ""
            company = ""
            if exp:
                position = exp[0].get("title", exp[0].get("position", ""))
                company = exp[0].get("company", exp[0].get("company_name", ""))

            profiles.append({
                "title": f"{name} - {position} at {company} - {location}" if company else name,
                "link": link,
                "snippet": about[:300] if about else headline,
                "position": position,
                "company": company,
                "location": location,
                "education": ", ".join([e.get("name", e.get("school_name", "")) if isinstance(e, dict) else str(e) for e in education]) if education else "",
                "about": about,
                "skills": skills
            })

        if profiles:
            logger.info(f"SerpAPI LinkedIn search returned {len(profiles)} profiles")
            return profiles
    except Exception as e:
        logger.warning(f"SerpAPI LinkedIn search failed ({e}), trying Google")

    # Attempt 2: Google search proxy (always works)
    try:
        params = {
            "engine": "google",
            "q": f'site:linkedin.com/in/ "{query}"',
            "api_key": settings.SERPAPI_API_KEY,
            "num": num
        }
        resp = requests.get("https://serpapi.com/search", params=params, timeout=10)
        results = resp.json().get('organic_results', [])
        profiles = []
        for r in results:
            link = r.get("link", "")
            if "linkedin.com/in/" not in link:
                continue
            title = r.get("title", "")
            snippet = r.get("snippet", "")
            pos, comp, loc = _parse_linkedin_title(title)
            profiles.append({
                "title": title, "link": link, "snippet": snippet,
                "position": pos, "company": comp, "location": loc,
                "education": "", "about": "", "skills": []
            })
        return profiles
    except Exception as e:
        logger.error(f"Google search fallback failed: {e}")
        return []


def _parse_linkedin_title(title):
    """Parse LinkedIn-style title -> (position, company, location)."""
    position = company = location = ""
    try:
        parts = title.split(" - ")
        if len(parts) >= 3:
            position = parts[1].strip()
            rest = parts[2].strip()
            if "," in rest:
                company, location = rest.split(",", 1)
                company = company.strip()
                location = location.strip()
            else:
                company = rest
    except Exception:
        pass
    return position, company, location


def _extract_profile_fields(profiles):
    """Normalize profile fields across LinkedIn engine and Google fallback results."""
    for p in profiles:
        p.setdefault("position", "")
        p.setdefault("company", "")
        p.setdefault("location", "")
        p.setdefault("education", "")
        p.setdefault("about", "")
        p.setdefault("skills", [])
        if not p.get("position") and not p.get("company"):
            pos, comp, loc = _parse_linkedin_title(p.get("title", ""))
            if not p.get("position"):
                p["position"] = pos
            if not p.get("company"):
                p["company"] = comp
            if not p.get("location"):
                p["location"] = loc
    return profiles


def fetch_linkedin_profile_by_url(linkedin_url):
    """Fetch LinkedIn profile by URL using SerpAPI LinkedIn Profile API, with fallback."""
    try:
        linkedin_url = linkedin_url.strip()
        if not linkedin_url.startswith('http'):
            linkedin_url = 'https://' + linkedin_url
        if not linkedin_url.endswith('/'):
            linkedin_url += '/'

        username_match = re.search(r'linkedin\.com/in/([a-zA-Z0-9\-]+)', linkedin_url)
        if not username_match:
            logger.warning(f"Could not extract username from LinkedIn URL: {linkedin_url}")
            return []

        username = username_match.group(1)

        # Try LinkedIn Profile API first
        profile = _serpapi_linkedin_profile(linkedin_url)
        if profile:
            return [profile]

        # Fallback to search
        profiles = _serpapi_linkedin_search(username, num=5)
        profiles = _extract_profile_fields(profiles)
        exact = [p for p in profiles if username.lower() in p.get("link", "").lower()]
        if exact:
            return exact[:1]
        if profiles:
            profiles[0]["link"] = linkedin_url
            return profiles[:1]

        return [{
            "title": f"{username.replace('-', ' ').title()} - LinkedIn Profile",
            "link": linkedin_url,
            "snippet": "LinkedIn profile accessed directly via URL",
            "position": "", "company": "", "location": "",
            "education": "", "about": "", "skills": []
        }]
    except Exception as e:
        logger.error(f"Error fetching LinkedIn profile by URL: {e}")
        return []


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
        
        # Extract username for post search
        linkedin_posts = []
        if linkedin_url:
            username_match = re.search(r'linkedin\.com/in/([a-zA-Z0-9\-]+)', linkedin_url)
            if username_match:
                username = username_match.group(1)
                try:
                    url = "https://serpapi.com/search"
                    params = {
                        "engine": "google",
                        "q": f'site:linkedin.com/posts/ {username}',
                        "api_key": settings.SERPAPI_API_KEY,
                        "num": 5
                    }
                    # Reduced timeout to 5 seconds - fail gracefully if SerpAPI is slow
                    response = requests.get(url, params=params, timeout=5)
                    posts_results = response.json().get('organic_results', [])
                    linkedin_posts = [r.get('snippet', '') for r in posts_results if r.get('snippet')]
                except requests.exceptions.Timeout:
                    logger.warning(f"SerpAPI timeout for {username} - proceeding without posts")
                except requests.exceptions.RequestException as e:
                    logger.warning(f"SerpAPI request failed for {username}: {e} - proceeding without posts")
                except Exception as e:
                    logger.warning(f"Failed to search LinkedIn posts: {e}")
        
        posts_text = '\n'.join([f"- {p}" for p in linkedin_posts]) if linkedin_posts else 'No recent posts found in search results.' 
        
        skills_text = ', '.join(skills) if skills else 'Not listed'

        prompt = f"""You are an AI sales intelligence analyst. Analyze the following LinkedIn profile and provide comprehensive insights in JSON format.

PROFILE:
Name: {name}
Headline: {headline}
Company: {company}
Location: {location}
Profile Summary: {snippet}
About Section: {about}
Education: {education}
Skills: {skills_text}

RECENT LINKEDIN POSTS:
{posts_text}

Return ONLY valid JSON with exactly these fields:
{{
    "intent": "brief description of their likely business intent and priorities",
    "pain_points": ["pain point 1", "pain point 2", "pain point 3"],
    "ai_need_score": (integer 1-10, how likely they need AI/automation solutions),
    "ai_need_reason": "one sentence explaining why they might need AI solutions",
    "branding_need_score": (integer 1-10, how likely they need branding/content solutions),
    "branding_need_reason": "one sentence explaining why they might need branding solutions",
    "pitch_angle": "recommended approach for sales pitch",
    "post_insights": "analysis of what their recent LinkedIn posts reveal about their interests, challenges, and needs",
    "linkedin_pitch": "a personalized LinkedIn outreach message under 100 words that references their profile and posts, offers a tailored solution, and has a clear call-to-action",
    "industry": "inferred industry based on their profile",
    "seniority_level": "inferred seniority (entry/mid/senior/executive/c-suite)",
    "company_size": "inferred company size range (startup/sme/enterprise)"
}}
        
Return ONLY valid JSON, no other text."""
        
        try:
            model = genai.GenerativeModel('gemini-2.5-flash')
        except Exception as model_error:
            logger.error(f"Model initialization error: {model_error}")
            return JsonResponse({'error': f'AI model not available: {str(model_error)}'}, status=500)
        
        try:
            # Reduced timeout to 30 seconds for gemini-2.5-flash (typical: 2-5 seconds)
            response = model.generate_content(
                prompt,
                request_options={'timeout': 30.0}
            )
        except Exception as gemini_error:
            logger.error(f"Gemini API error: {gemini_error}")
            if "timeout" in str(gemini_error).lower():
                return JsonResponse({'error': 'AI analysis timed out - please try again'}, status=504)
            else:
                return JsonResponse({'error': f'AI analysis failed: {str(gemini_error)}'}, status=500)
        
        # Parse response
        try:
            response_text = response.text.strip()
            # Remove markdown code blocks if present
            if response_text.startswith('```'):
                response_text = response_text.split('```')[1]
                if response_text.startswith('json'):
                    response_text = response_text[4:]
            response_text = response_text.strip()
            
            analysis = json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing Gemini response: {e}")
            logger.error(f"Raw response: {response_text[:200]}")
            return JsonResponse({'error': 'Failed to parse analysis response - invalid JSON from AI'}, status=500)
        
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
            contact_data = {
                'name': name,
                'company': company,
                'headline': headline,
                'location': location,
                'linkedin_url': linkedin_url,
                'snippet': snippet,
                'intent': analysis.get('intent', ''),
                'pain_points': analysis.get('pain_points', []),
                'ai_need_score': analysis.get('ai_need_score', 0),
                'ai_need_reason': analysis.get('ai_need_reason', ''),
                'branding_need_score': analysis.get('branding_need_score', 0),
                'branding_need_reason': analysis.get('branding_need_reason', ''),
                'pitch_angle': analysis.get('pitch_angle', ''),
                'post_insights': analysis.get('post_insights', ''),
                'linkedin_pitch': analysis.get('linkedin_pitch', ''),
                'industry': analysis.get('industry', ''),
                'seniority_level': analysis.get('seniority_level', ''),
                'company_size': analysis.get('company_size', '')
            }
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
