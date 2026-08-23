import os
import json
import re
import requests
import google.auth
import google.generativeai as genai
from django.conf import settings
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime

def perform_research(company_name, website_url=None):
    """
    Step 1: 'High-Level' Dual-Search Audit.
    We run TWO targeted searches to ensure we catch both Branding (Visuals)
    and Operational (AI/Support) signals.
    """
    if not settings.SERPAPI_API_KEY:
        print("❌ ERROR: SERPAPI_API_KEY is missing.")
        return "No API Key found."

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    # --- SEARCH 1: BRAND & VISIBILITY ---
    # Looks for: Instagram, LinkedIn, recent posts, visual presence
    query_brand = f"{company_name} instagram linkedin facebook social media posts"
    
    # --- SEARCH 2: OPERATIONS & REPUTATION ---
    # Looks for: Bad reviews, "slow service", customer complaints, manual hiring ads
    query_ops = f"{company_name} reviews customer service complaints slow response"

    research_text = f"--- AUDIT REPORT FOR {company_name} ---\n"

    try:
        # Execute Search 1 (Branding)
        print(f"🔍 Auditing Brand Presence: {query_brand}")
        params_brand = {
            "engine": "google",
            "q": query_brand,
            "api_key": settings.SERPAPI_API_KEY,
            "num": 4
        }
        resp_brand = requests.get("https://serpapi.com/search", params=params_brand)
        data_brand = resp_brand.json()
        
        research_text += "\n[BRANDING SIGNALS]:\n"
        if "organic_results" in data_brand:
            for res in data_brand["organic_results"][:4]:
                research_text += f"- {res.get('title', '')}: {res.get('snippet', '')}\n"

        # Execute Search 2 (Operations)
        print(f"🔍 Auditing Operations: {query_ops}")
        params_ops = {
            "engine": "google",
            "q": query_ops,
            "api_key": settings.SERPAPI_API_KEY,
            "num": 4
        }
        resp_ops = requests.get("https://serpapi.com/search", params=params_ops)
        data_ops = resp_ops.json()

        research_text += "\n[OPERATIONAL SIGNALS]:\n"
        if "organic_results" in data_ops:
            for res in data_ops["organic_results"][:4]:
                research_text += f"- {res.get('title', '')}: {res.get('snippet', '')}\n"

        return research_text

    except Exception as e:
        print(f"❌ SerpApi Exception: {e}")
        return f"Research Error: {str(e)}"

def clean_json_string(json_string):
    """
    Cleans AI output to ensure valid JSON parsing.
    """
    json_string = re.sub(r'```json\s*', '', json_string)
    json_string = re.sub(r'```\s*$', '', json_string)
    return json_string.strip()

def generate_pitch_content(company_name, research_data):
    """
    Step 2: 'Dual-Threat' Strategist Logic (Branding + AI).
    """
    if not settings.GEMINI_API_KEY:
        return _get_fallback_data(company_name, "Missing API Key")

    genai.configure(api_key=settings.GEMINI_API_KEY)

    available_models = [
        'gemini-2.0-flash', 
        'gemini-2.0-flash-lite-preview-02-05', 
        'gemini-2.5-flash'
    ]
    
    # --- HIGH-LEVEL HYBRID PROMPT ---
    prompt = f"""
    You are a **Holistic Business Transformation Consultant**.
    Unlike cheap agencies that pitch one thing, you pitch a **"Growth Ecosystem"**.
    
    CONTEXT:
    Client: {company_name}
    Audit Data: 
    {research_data}
    
    ---
    ### **MISSION: THE HYBRID PITCH**
    You must identify **TWO** connected problems (Pain Points) and pitch a unified solution.
    
    **1. The Front-End Gap (Branding/Content):**
    - Look for: Inconsistent posting, outdated visuals, no video content, weak social proof.
    - Solution: "Premium Content & Branding to drive traffic."
    
    **2. The Back-End Gap (AI Agents/Efficiency):**
    - Look for: Slow replies, bad reviews, manual processes, missed leads.
    - Solution: "AI Agents to automate support & sales 24/7."
    
    ---
    ### **OUTPUT INSTRUCTIONS (JSON)**
    
    1. **pain_points**: Combine both gaps into one punchy statement. 
       (e.g., "Great product, but your social presence is quiet AND customers are complaining about slow replies.")
    
    2. **email_body_text**: 
       - **Hook:** Acknowledge their potential.
       - **The 'Gap'**: "I noticed your Instagram is quiet (Branding gap), which means you're leaving money on the table. But even if you scaled up, your current manual support (AI gap) might struggle to keep up."
       - **The 'Fix'**: "We build the Content to get you seen, AND the AI Agents to handle the new leads automatically."
    
    3. **visual_style_guide / image_prompt / video_prompt**: 
       - Create high-end visual concepts (as per previous logic) to prove we can fix the "Front-End Gap".

    ---
    ### **STRICT JSON FORMAT**
    Escape all newlines (\\n). No Markdown.
    
    {{
        "pain_points": "Dual-threat summary string",
        "email_subject": "Catchy subject line focusing on Growth + Automation",
        "email_body_text": "Hybrid pitch text",
        "email_body_html": "HTML code",
        "whatsapp_message": "Short hybrid msg",
        "call_script": "Hybrid script",
        "visual_style_guide": "3 keywords",
        "image_prompt": "Midjourney prompt",
        "video_prompt": "Runway prompt"
    }}
    """

    for model_name in available_models:
        try:
            print(f"🤖 Generating Hybrid Strategy with {model_name}...")
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(
                prompt,
                request_options={'timeout': 120.0}
            )
            
            # Robust Extraction
            json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if json_match:
                clean_json = clean_json_string(json_match.group(0))
                data = json.loads(clean_json, strict=False)
                print(f"✅ Hybrid Strategy Generated ({model_name})")
                return data
                
        except Exception as e:
            print(f"❌ Failed with {model_name}: {e}")
            continue

    return _get_fallback_data(company_name, "All AI models failed.")

def _get_fallback_data(company_name, error_msg):
    return {
        "pain_points": f"Error: {error_msg}",
        "email_subject": "Growth Strategy",
        "email_body_text": "Error generating pitch.",
        "email_body_html": "<p>Error</p>",
        "whatsapp_message": "Error.",
        "call_script": "Error.",
        "visual_style_guide": "N/A",
        "image_prompt": "N/A",
        "video_prompt": "N/A"
    }

def export_to_google_sheets(pitch_data):
    """
    Appends data to the specific PITCH_SHEET_ID.
    """
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
    
    SPREADSHEET_ID = getattr(settings, 'PITCH_SHEET_ID', None)
    if not SPREADSHEET_ID:
        print("⚠️ Google Sheets Export Skipped: PITCH_SHEET_ID missing in settings.")
        return False

    try:
        from sales_project.google_auth import default_or_loaded
        creds = default_or_loaded(SCOPES)
        service = build('sheets', 'v4', credentials=creds)

        # 4. Prepare Row Data
        # Columns: [Timestamp, Company, Website, Pain Points, Email Subject, WhatsApp, Style Guide, Image Prompt, Video Prompt]
        values = [[
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            pitch_data.get('company_name', 'N/A'),
            pitch_data.get('website_url', 'N/A'),
            pitch_data.get('pain_points', 'N/A'),
            pitch_data.get('email_subject', 'N/A'),
            pitch_data.get('email_body_text', 'N/A'),
            pitch_data.get('whatsapp_message', 'N/A'),
            pitch_data.get('visual_style_guide', 'N/A'),
            pitch_data.get('image_prompt', 'N/A'),
            pitch_data.get('video_prompt', 'N/A')
        ]]

        body = {'values': values}

        # 5. Append to Sheet
        result = service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range='Sheet1!A1',  # Appends to the first available row in Sheet1
            valueInputOption='USER_ENTERED',
            body=body
        ).execute()

        print(f"✅ Data exported to Google Sheet! ({result.get('updates').get('updatedCells')} cells updated)")
        return True

    except Exception as e:
        print(f"❌ Google Sheets Export Failed: {e}")
        return False