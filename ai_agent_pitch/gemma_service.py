# ai_agent_pitch/gemma_service.py
#
# Lightweight AI personalization for the Auto Campaign Engine.
# Tries local/cloud Gemma models first (gemma-3-27b-it -> gemma-3-12b-it),
# then falls back to Gemini models, and finally to safe placeholder
# replacement so emails are ALWAYS sendable.

import json
import logging
import re

from django.conf import settings

logger = logging.getLogger(__name__)

# Model chain: Gemma first (as requested), Gemini as a reliability fallback.
PERSONALIZATION_MODELS = [
    'gemma-3-27b-it',
    'gemma-3-12b-it',
    'gemini-2.5-flash',
    'gemini-2.0-flash',
]


def _personalize_with_placeholders(subject, html_content, contact):
    """Safe non-AI fallback: swap [Recipient] / [Company] placeholders."""
    name = contact.get('name') or 'Partner'
    company = contact.get('company') or contact.get('headline') or 'your company'

    def _replace(text):
        return (text.replace('[Recipient]', name)
                   .replace('[Company]', company))

    return _replace(subject), _replace(html_content)


def _extract_json(text):
    """Pull a JSON object out of an AI response (handles markdown fences)."""
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith('```'):
        stripped = re.sub(r'^```[a-zA-Z]*\n?', '', stripped)
        stripped = re.sub(r'\n?```$', '', stripped).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r'\{[\s\S]*\}', stripped)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    return None


def generate_personalized_email(subject, html_content, contact):
    """
    Personalize a campaign email for a single contact using AI.

    Args:
        subject (str): Base subject line.
        html_content (str): Base HTML email body.
        contact (dict): Contact data with keys like name, company, headline,
                        location, pain_points, etc.

    Returns:
        (subject, html_body): Personalized subject and body. Guaranteed to
        return valid strings (never raises) so sends always go through.
    """
    api_key = getattr(settings, 'GEMINI_API_KEY', '')
    if not api_key:
        return _personalize_with_placeholders(subject, html_content, contact)

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
    except Exception as e:
        logger.error(f"Failed to configure AI for personalization: {e}")
        return _personalize_with_placeholders(subject, html_content, contact)

    name = contact.get('name') or 'Partner'
    company = contact.get('company') or ''
    headline = contact.get('headline') or ''
    location = contact.get('location') or ''
    pain_points = contact.get('pain_points') or []
    if isinstance(pain_points, str):
        pain_points = [pain_points]

    prompt = f"""You are a senior B2B email copywriter. Personalize the email below for ONE recipient and return ONLY a JSON object.

CONTACT:
- Name: {name}
- Company: {company or 'unknown'}
- Headline: {headline or 'unknown'}
- Location: {location or 'unknown'}
- Known pain points: {', '.join(pain_points) if pain_points else 'not provided'}

RULES:
1. Keep the overall structure, branding, and visual HTML of the template intact.
2. Replace [Recipient] with the recipient's first name, [Company] with their company.
3. Tailor the opening line and value props to the contact's company/headline/pain points.
4. Keep the subject under 60 characters and compelling.
5. Use ONLY inline CSS (email-safe), no <style> blocks.
6. Output exactly:
{{"subject": "personalized subject line", "body": "personalized HTML body"}}

BASE SUBJECT:
{subject}

BASE HTML TEMPLATE:
{html_content}
"""

    errors = []
    for model_name in PERSONALIZATION_MODELS:
        try:
            logger.info(f"[auto-campaign] Trying model: {model_name}")
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt, request_options={'timeout': 90.0})
            data = _extract_json(response.text if response else None)
            if not data or not data.get('body'):
                raise ValueError('Response did not contain a valid body')
            personalized_subject = str(data.get('subject') or subject).strip() or subject
            personalized_body = str(data.get('body')).strip()
            logger.info(f"[auto-campaign] Personalized with {model_name}")
            return personalized_subject, personalized_body
        except Exception as e:
            errors.append(f"{model_name}: {e}")
            continue

    logger.warning(f"[auto-campaign] All AI models failed, using placeholders. {errors}")
    return _personalize_with_placeholders(subject, html_content, contact)