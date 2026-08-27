"""
Reusable LinkedIn scraping + AI analysis pipeline.

Used by:
- scraper/views.py (interactive UI endpoints)
- scraper/management/commands/daily_keyword_scrape.py (scheduled daily job)
- the scheduler/run-now HTTP endpoints

Dependency rule: this module must NOT import from scraper.views
(views imports from here, one-directional).
"""

import json
import logging
import re
import requests
import google.generativeai as genai
from django.conf import settings
from django.utils import timezone

from dashboard.gcs import (
    upload_contact,
    upload_scrape_run,
    save_scrape_progress,
    append_scrape_stat,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SerpAPI LinkedIn helpers
# ---------------------------------------------------------------------------

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


def _serpapi_linkedin_search(query, num=10, location=None):
    """
    Search LinkedIn via SerpAPI — tries LinkedIn Profile API for full profiles,
    falls back to LinkedIn search, then to Google search.
    `location` (e.g. "USA", "Australia") is appended to the query when present
    so results are filtered to that region on the Google fallback.
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
        if location:
            params["keywords"] = location
            params["location"] = location

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
            location_val = r.get("location", "")
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
                "title": f"{name} - {position} at {company} - {location_val}" if company else name,
                "link": link,
                "snippet": about[:300] if about else headline,
                "position": position,
                "company": company,
                "location": location_val or location or "",
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
        search_query = f'site:linkedin.com/in/ "{query}"'
        if location:
            search_query += f' "{location}"'
        params = {
            "engine": "google",
            "q": search_query,
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
                "position": pos, "company": comp, "location": loc or location or "",
                "education": "", "about": "", "skills": []
            })
        return profiles
    except Exception as e:
        logger.error(f"Google search fallback failed: {e}")
        return []


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


# ---------------------------------------------------------------------------
# Gemini analysis pipeline
# ---------------------------------------------------------------------------

def _fetch_recent_posts(linkedin_url):
    """Best-effort fetch of a profile's recent LinkedIn post snippets via SerpAPI."""
    linkedin_posts = []
    if not linkedin_url:
        return linkedin_posts
    username_match = re.search(r'linkedin\.com/in/([a-zA-Z0-9\-]+)', linkedin_url)
    if not username_match:
        return linkedin_posts
    username = username_match.group(1)
    try:
        params = {
            "engine": "google",
            "q": f'site:linkedin.com/posts/ {username}',
            "api_key": settings.SERPAPI_API_KEY,
            "num": 5
        }
        response = requests.get("https://serpapi.com/search", params=params, timeout=5)
        posts_results = response.json().get('organic_results', [])
        linkedin_posts = [r.get('snippet', '') for r in posts_results if r.get('snippet')]
    except requests.exceptions.Timeout:
        logger.warning(f"SerpAPI timeout for {username} - proceeding without posts")
    except requests.exceptions.RequestException as e:
        logger.warning(f"SerpAPI request failed for {username}: {e} - proceeding without posts")
    except Exception as e:
        logger.warning(f"Failed to search LinkedIn posts: {e}")
    return linkedin_posts


def analyze_profile_record(name='', headline='', company='', location='', snippet='',
                           linkedin_url='', education='', about='', skills=None):
    """
    Run the Gemini analysis for a single profile.

    Returns the analysis dict. Raises RuntimeError on failure.
    """
    skills = skills or []

    linkedin_posts = _fetch_recent_posts(linkedin_url)
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
        raise RuntimeError(f'AI model not available: {model_error}')

    try:
        response = model.generate_content(
            prompt,
            request_options={'timeout': 30.0}
        )
    except Exception as gemini_error:
        if "timeout" in str(gemini_error).lower():
            raise RuntimeError('AI analysis timed out')
        raise RuntimeError(f'AI analysis failed: {gemini_error}')

    try:
        response_text = response.text.strip()
        if response_text.startswith('```'):
            response_text = response_text.split('```')[1]
            if response_text.startswith('json'):
                response_text = response_text[4:]
        response_text = response_text.strip()
        return json.loads(response_text)
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing Gemini response: {e}")
        raise RuntimeError('Failed to parse analysis response - invalid JSON from AI')


def build_contact_data(name='', company='', headline='', location='', linkedin_url='',
                       snippet='', analysis=None):
    """Build the GCS contact payload (same shape used by the interactive analyze view)."""
    analysis = analysis or {}
    return {
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


def _profile_uid(linkedin_url, name):
    """Stable uid for a scraped profile (same convention as the interactive view)."""
    if linkedin_url:
        return linkedin_url.rstrip('/').split('/')[-1]
    return name.replace(' ', '-').lower()


def _keyword_slug(keyword):
    """Filesystem-safe slug for a keyword."""
    slug = re.sub(r'[^a-z0-9]+', '-', keyword.lower()).strip('-')
    return slug or 'keyword'


def _save_profile_to_sheets(contact_data, saved_at):
    """
    Best-effort save of an analyzed profile to the Google spreadsheet
    (same sheet_data shape used by the interactive analyze view).
    Returns True on success, False otherwise.
    """
    if not getattr(settings, 'LINKEDIN_SHEET_ID', None):
        return False
    try:
        from .sheets_util import append_profile as sheets_append_profile
        pain_points = contact_data.get('pain_points', [])
        if isinstance(pain_points, str):
            pain_points = [pain_points]
        sheet_data = {
            'name': contact_data.get('name', ''),
            'company': contact_data.get('company', ''),
            'location': contact_data.get('location', ''),
            'linkedin_url': contact_data.get('linkedin_url', ''),
            'intent': contact_data.get('intent', ''),
            'pain_points': pain_points,
            'ai_need_score': contact_data.get('ai_need_score', 0),
            'branding_need_score': contact_data.get('branding_need_score', 0),
            'email': '',
            'phone': '',
            'pitch_linkedin': contact_data.get('linkedin_pitch', ''),
            'pitch_email': '',
            'pitch_whatsapp': '',
            'industry': contact_data.get('industry', ''),
            'seniority_level': contact_data.get('seniority_level', ''),
            'company_size': contact_data.get('company_size', ''),
            'contact_priority': 'medium',
            'created_at': saved_at,
            'updated_at': saved_at,
        }
        return bool(sheets_append_profile(settings.LINKEDIN_SHEET_ID, sheet_data))
    except Exception as e:
        logger.warning(f"Failed to save profile to Google Sheets ({contact_data.get('name')}): {e}")
        return False


def _resolve_scrape_owner(user=None):
    """
    Decide which Django user owns scraped contacts. Explicit user wins;
    otherwise the app owner (DEFAULT_EMAIL_OWNER_USERNAME, e.g. kalisoftai);
    last resort: the first user. Scheduled scrapes have no request, so this
    keeps data landing in the same user-scoped GCS folders as the dashboard.
    """
    if user is not None:
        return user
    from django.contrib.auth.models import User
    owner_name = getattr(settings, 'DEFAULT_EMAIL_OWNER_USERNAME', '')
    owner = User.objects.filter(username=owner_name).first()
    return owner or User.objects.order_by('id').first()


# ---------------------------------------------------------------------------
# Scheduled scrape runner
# ---------------------------------------------------------------------------

def scrape_keyword(keyword, num=10, save_contacts=True, on_profile_done=None, location=None, user=None):
    """
    Scrape LinkedIn for a keyword (optionally filtered to a location), analyze
    each profile with Gemini, and store the batch result in GCS
    (scraper_runs/<date>/<keyword-slug>.json or <keyword-slug>-<location-slug>.json).
    Each analyzed profile is also upserted into contacts/linkedin/ so it
    appears in Dashboard -> LinkedIn Contacts.

    on_profile_done(analyzed_count, found_total) is called after each profile
    (used for live progress reporting). Returns a per-keyword summary dict.
    """
    started = timezone.now()
    owner = _resolve_scrape_owner(user)
    summary = {
        'keyword': keyword,
        'location': location or '',
        'started_at': started.isoformat(),
        'status': 'failed',
        'profiles_found': 0,
        'profiles_analyzed': 0,
        'gcs_saved': 0,
        'sheets_saved': 0,
        'run_path': None,
        'error': None,
    }

    try:
        profiles = _serpapi_linkedin_search(keyword, num=num, location=location)
        profiles = _extract_profile_fields(profiles)
        summary['profiles_found'] = len(profiles)

        results = []
        for profile in profiles:
            linkedin_url = profile.get('link', '')
            title = profile.get('title', '')
            name = (title.split(' - ')[0].strip() if title else '') or 'Unknown'
            try:
                analysis = analyze_profile_record(
                    name=name,
                    headline=profile.get('position', ''),
                    company=profile.get('company', ''),
                    location=profile.get('location', ''),
                    snippet=profile.get('snippet', ''),
                    linkedin_url=linkedin_url,
                    education=profile.get('education', ''),
                    about=profile.get('about', ''),
                    skills=profile.get('skills', []),
                )
            except Exception as e:
                logger.warning(f"[{keyword}] Analysis failed for {name}: {e}")
                continue

            contact_data = build_contact_data(
                name=name,
                company=profile.get('company', ''),
                headline=profile.get('position', ''),
                location=profile.get('location', ''),
                linkedin_url=linkedin_url,
                snippet=profile.get('snippet', ''),
                analysis=analysis,
            )
            contact_data['source_keyword'] = keyword
            if location:
                contact_data['source_location'] = location
            contact_data['scraped_at'] = started.isoformat()

            if save_contacts:
                gcs_ok = upload_contact('linkedin', _profile_uid(linkedin_url, name), contact_data, user=owner)
                if gcs_ok:
                    summary['gcs_saved'] += 1
                else:
                    logger.warning(f"[{keyword}] GCS save returned failure for {name}")

            # Also save to the Google spreadsheet (same as the interactive scraper)
            if _save_profile_to_sheets(contact_data, started.isoformat()):
                summary['sheets_saved'] += 1

            results.append(contact_data)
            summary['profiles_analyzed'] += 1

            if on_profile_done:
                try:
                    on_profile_done(summary['profiles_analyzed'], summary['profiles_found'])
                except Exception as progress_error:
                    logger.warning(f"[{keyword}] Progress update failed: {progress_error}")

        # Store the historical batch in GCS
        date_str = started.strftime('%Y-%m-%d')
        run_stem = _keyword_slug(keyword)
        if location:
            run_stem = f"{run_stem}-{_keyword_slug(location)}"
        run_rel_path = f"{date_str}/{run_stem}.json"
        finished = timezone.now().isoformat()
        run_payload = {
            'keyword': keyword,
            'location': location or '',
            'run_at': started.isoformat(),
            'finished_at': finished,
            'profiles_found': summary['profiles_found'],
            'profiles_analyzed': summary['profiles_analyzed'],
            'sheets_saved': summary['sheets_saved'],
            'profiles': results,
        }
        if upload_scrape_run(run_rel_path, run_payload):
            summary['run_path'] = f"scraper_runs/{run_rel_path}"
            summary['status'] = 'success'
            # Record stat entry for dashboard stats/bars
            try:
                append_scrape_stat({
                    'date': date_str,
                    'keyword': keyword,
                    'location': location or '',
                    'profiles_found': summary['profiles_found'],
                    'profiles_analyzed': summary['profiles_analyzed'],
                    'run_path': summary['run_path'],
                    'finished_at': finished,
                })
            except Exception as stat_error:
                logger.warning(f"[{keyword}] Failed to record stat entry: {stat_error}")
        else:
            summary['error'] = 'Failed to upload run batch to GCS'

    except Exception as e:
        logger.error(f"[{keyword}] Scheduled scrape failed: {e}", exc_info=True)
        summary['error'] = str(e)

    logger.info(f"[{keyword}] Scrape finished: {summary['status']} — "
                f"{summary['profiles_analyzed']}/{summary['profiles_found']} analyzed, "
                f"{summary['sheets_saved']} saved to Google Sheets")
    return summary


def run_daily_scrape(keywords=None, locations=None, num=10, trigger='manual', user=None):
    """
    Run the daily scrape for all (or given) keywords × locations, persisting
    live progress to GCS (scraper_config/progress.json) so the dashboard can
    show a real-time progress bar.

    Locations act as an additional filter for each keyword (e.g. "USA",
    "Australia"). If locations is None, all active configured locations are used.

    trigger: 'command' (local cron/mgmt cmd), 'scheduler', or 'manual' (dashboard).
    Returns a list of per-(keyword, location) summary dicts.
    """
    if keywords is None:
        from dashboard.gcs import get_scrape_keywords
        keywords = [k['keyword'] for k in get_scrape_keywords() if k.get('active')]

    if locations is None:
        from dashboard.gcs import get_scrape_locations
        locations = [l['location'] for l in get_scrape_locations() if l.get('active')]

    if not keywords:
        logger.warning("No active scrape keywords configured — nothing to do.")
        return []

    # Build the ordered job list (keyword × location; empty location = no filter)
    jobs = []
    for kw in keywords:
        if locations:
            for loc in locations:
                jobs.append({'keyword': kw, 'location': loc})
        else:
            jobs.append({'keyword': kw, 'location': ''})

    started = timezone.now()
    progress = {
        'state': 'running',
        'trigger': trigger,
        'started_at': started.isoformat(),
        'updated_at': started.isoformat(),
        'finished_at': None,
        'total_keywords': len(keywords),
        'total_locations': len(locations),
        'total_jobs': len(jobs),
        'current_job_index': 0,
        'current_keyword': jobs[0]['keyword'],
        'current_location': jobs[0]['location'],
        'current_keyword_profiles_found': 0,
        'current_keyword_profiles_analyzed': 0,
        'total_profiles_analyzed': 0,
        'summaries': [],
        'error': None,
    }
    save_scrape_progress(progress)

    summaries = []
    for i, job in enumerate(jobs):
        keyword = job['keyword']
        location = job['location']
        progress['current_job_index'] = i
        progress['current_keyword'] = keyword
        progress['current_location'] = location
        progress['current_keyword_profiles_found'] = 0
        progress['current_keyword_profiles_analyzed'] = 0
        progress['updated_at'] = timezone.now().isoformat()
        save_scrape_progress(progress)

        def _on_profile_done(analyzed, found, _i=i):
            progress['current_keyword_profiles_analyzed'] = analyzed
            progress['current_keyword_profiles_found'] = found
            progress['total_profiles_analyzed'] = (
                sum(s.get('profiles_analyzed', 0) for s in summaries) + analyzed
            )
            progress['updated_at'] = timezone.now().isoformat()
            save_scrape_progress(progress)

        summaries.append(scrape_keyword(keyword, num=num, location=location or None,
                                        on_profile_done=_on_profile_done, user=user))
        progress['summaries'] = summaries

    ok = sum(1 for s in summaries if s.get('status') == 'success')
    progress['state'] = 'completed' if ok > 0 else 'failed'
    progress['finished_at'] = timezone.now().isoformat()
    progress['updated_at'] = progress['finished_at']
    progress['total_profiles_analyzed'] = sum(s.get('profiles_analyzed', 0) for s in summaries)
    if ok < len(summaries):
        progress['error'] = '; '.join(
            f"{s['keyword']}{'/' + s['location'] if s.get('location') else ''}: "
            f"{s.get('error') or 'unknown'}" for s in summaries if s.get('status') != 'success'
        ) or None
    save_scrape_progress(progress)
    return summaries
