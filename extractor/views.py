# views.py

import imaplib
import email
from email.header import decode_header
import os
import csv
import re
import io
import json
from django.shortcuts import render, redirect # --- NEW ---
from django.http import HttpResponse, JsonResponse # --- NEW ---
from django.conf import settings # --- NEW ---
from dotenv import load_dotenv
from .models import Supplier
import google.generativeai as genai

# --- NEW Google Sheet Imports ---
import google.auth
import gspread
from google.oauth2.service_account import Credentials
# --- END NEW ---

load_dotenv()

# --- Gemini API Client Setup ---
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# --- NEW Google Sheet Client Cache ---
_worksheet_cache = None
# --- END NEW ---


# --- NEW Google Sheet Helper Functions ---

def get_google_worksheet():
    """
    Connects to Google Sheets using service account and returns the first worksheet.
    Uses a simple cache to avoid re-authenticating.
    """
    global _worksheet_cache
    if _worksheet_cache:
        return _worksheet_cache

    try:
        SCOPES = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.file"
        ]

        if settings.GOOGLE_CREDENTIALS_FILE:
            creds = Credentials.from_service_account_file(
                settings.GOOGLE_CREDENTIALS_FILE, scopes=SCOPES
            )
        else:
            creds, _ = google.auth.default(scopes=SCOPES)

        client = gspread.authorize(creds)

        sheet_id = os.getenv('GOOGLE_SHEET_ID')
        spreadsheet = client.open_by_key(sheet_id)
        worksheet = spreadsheet.get_worksheet(0)

        header = ['Company Name', 'Email Address', 'Contact Name', 'Contact Number']
        if worksheet.get_all_values() == []:
             worksheet.append_row(header)

        _worksheet_cache = worksheet
        return worksheet

    except Exception as e:
        print(f"Error connecting to Google Sheets: {e}")
        return None

def sync_supplier_to_sheet(supplier_data, worksheet):
    """
    Finds a supplier by email in the sheet and updates it,
    or appends it as a new row.
    """
    if not worksheet:
        print("Google Sheet not available. Skipping sync.")
        return

    try:
        # Data to be written
        row_data = [
            supplier_data.get('company', 'N/A'),
            supplier_data.get('email', 'N/A'),
            supplier_data.get('name', 'N/A'),
            supplier_data.get('number', 'N/A')
        ]
        
        # Find cell with matching email (Column 2)
        cell = worksheet.find(supplier_data['email'], in_column=2)
        
        if cell:
            # Email found, update the row
            worksheet.update(f'A{cell.row}:D{cell.row}', [row_data])
            print(f"Updated supplier in Google Sheet: {supplier_data['email']}")
        else:
            # Email not found, append a new row
            worksheet.append_row(row_data)
            print(f"Added new supplier to Google Sheet: {supplier_data['email']}")

    except Exception as e:
        # Handle API rate limits or other errors
        print(f"Error syncing to Google Sheet: {e}")

# --- END NEW ---


# --- Helper Functions (Your existing code) ---

def get_email_body(msg):
    # ... (no changes) ...
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            cdispo = str(part.get("Content-Disposition"))
            if ctype == "text/plain" and "attachment" not in cdispo:
                try:
                    return part.get_payload(decode=True).decode('utf-8', errors='ignore')
                except Exception:
                    continue
    else:
        try:
            return msg.get_payload(decode=True).decode('utf-8', errors='ignore')
        except Exception:
            pass
    return ""

def is_request_or_purchase(subject, body):
    # ... (no changes) ...
    keywords = ['request for quotation', 'rfq', 'inquiry', 'requirement', 'purchase order', 'po']
    content = (subject + ' ' + body).lower()
    return any(keyword in content for keyword in keywords)

def is_incoming_quotation(subject, body):
    # ... (no changes) ...
    keywords = ['quotation', 'quote', 'proposal', 'estimate', 'proforma', 'offer']
    content = (subject + ' ' + body).lower()
    return any(keyword in content for keyword in keywords)

def extract_entities_with_gemini(subject, body, from_address):
    # ... (no changes) ...
    prompt = f"""
    Analyze the following email to extract supplier information.
    Prioritize details from the email signature.
    Provide the output ONLY in a valid JSON format.

    **JSON Structure:**
    {{
      "company_name": "...",
      "contact_name": "...",
      "email_address": "...",
      "contact_number": "..."
    }}

    **Rules:**
    1.  **company_name**: Find the full official company name. Avoid generic names.
    2.  **contact_name**: Extract the full name of the person. If no name, use "N/A".
    3.  **email_address**: Use the provided sender's email address: {from_address}.
    4.  **contact_number**: Find the primary contact number (Mobile or Telephone). Clean it by removing special characters like (),- and spaces. If not found, use "N/A".
    5.  If any field's information is not found in the email, strictly use "N/A" for that field.
    6.  Do not add any text or explanation outside the JSON block.

    **Example:**
    ---
    **Email Body:**
    Dear Team,

    Please find our offer attached for your review.

    Thanks & Regards,
    Priya Sharma
    Sales Manager
    Innovative Solutions Pvt. Ltd.
    Email: priya.s@innovativesolutions.com
    Web: www.innovativesolutions.com
    Mobile: +91-98765 43210 | Tel: (022) 1234 5678

    ---
    **Expected JSON Output:**
    ```json
    {{
      "company_name": "Innovative Solutions Pvt. Ltd.",
      "contact_name": "Priya Sharma",
      "email_address": "priya.s@innovativesolutions.com",
      "contact_number": "+919876543210"
    }}
    ```

    ---
    **Analyze This Real Email:**

    **Email Subject:**
    {subject}

    **Email Body:**
    {body}
    """

    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(
            prompt,
            request_options={'timeout': 120.0}
        )
        
        response_text = response.text
        json_match = re.search(r'```json\n({.*?})\n```', response_text, re.DOTALL)
        if not json_match:
            json_match = re.search(r'({.*?})', response_text, re.DOTALL)

        if json_match:
            json_str = json_match.group(1)
            data = json.loads(json_str)
            
            company = data.get('company_name', 'N/A').strip()
            contact = data.get('contact_name', 'N/A').strip()
            number = data.get('contact_number', 'N/A').strip()
            email_addr = from_address

            if company in ['N/A', '']:
                company = from_address.split('@')[1].split('.')[0].capitalize()

            return {
                'company': company,
                'name': contact if contact else 'N/A',
                'email': email_addr,
                'number': number if number else 'N/A'
            }
        else:
            raise ValueError("No valid JSON found in Gemini response")

    except Exception as e:
        print(f"Gemini extraction error: {e}. Using basic fallback.")
        return {
            'company': from_address.split('@')[1].split('.')[0].capitalize(),
            'name': 'N/A',
            'email': from_address,
            'number': 'N/A'
        }
    # --- DELETED a redundant except block here ---

def search_emails(query, user_email):
    # ... (no changes) ...
    PASSWORD = os.getenv('EMAIL_PASS')
    SERVER = os.getenv('IMAP_SERVER')
    suppliers = {}

    try:
        mail = imaplib.IMAP4_SSL(SERVER)
        mail.login(user_email, PASSWORD)
        mail.select('inbox')

        search_criteria = f'X-GM-RAW "{query}"'
        status, messages = mail.search('UTF-8', search_criteria)

        if status != 'OK':
            print(f"IMAP search failed: {messages}")
            return []

        email_ids = messages[0].split()
        for email_id in reversed(email_ids[:100]):
            try:
                _, msg_data = mail.fetch(email_id, '(RFC822)')
                for response_part in msg_data:
                    if not isinstance(response_part, tuple):
                        continue

                    msg = email.message_from_bytes(response_part[1])
                    email_body = get_email_body(msg)
                    subject_header = decode_header(msg.get("Subject", ""))[0]
                    subject = subject_header[0].decode(subject_header[1] or 'utf-8', errors='ignore') if isinstance(subject_header[0], bytes) else subject_header[0]

                    from_name, from_addr = email.utils.parseaddr(msg.get('From'))
                    
                    if user_email.lower() not in from_addr.lower():
                        if is_incoming_quotation(subject, email_body) and from_addr not in suppliers:
                            supplier_data = extract_entities_with_gemini(subject, email_body, from_addr)
                            suppliers[from_addr] = supplier_data
                    else:
                        if is_request_or_purchase(subject, email_body):
                            recipients = email.utils.getaddresses(msg.get_all('to', []) + msg.get_all('cc', []))
                            for to_name, to_addr in recipients:
                                if to_addr and user_email.lower() not in to_addr.lower() and to_addr not in suppliers:
                                    supplier_data = extract_entities_with_gemini(subject, email_body, to_addr)
                                    suppliers[to_addr] = supplier_data
            except Exception as e:
                print(f"Error processing email ID {email_id}: {e}")
                continue

        mail.logout()
    except Exception as e:
        print(f"IMAP connection error: {e}")
        return None

    return list(suppliers.values())

# --- Django Views ---

def search_view(request):
    """Email search aur CSV upload ko handle karta hai."""
    context = {}
    user_email = os.getenv('EMAIL_USER')
    
    # --- NEW: Get the Google Sheet worksheet ---
    worksheet = get_google_worksheet()
    if not worksheet:
        # Pass an error to the template if sheet connection fails
        context['sheet_error'] = "Could not connect to Google Sheets. Check credentials and permissions."
    # --- END NEW ---

    if request.method == 'POST':
        if 'csv_file' in request.FILES:
            # CSV bulk search logic
            uploaded_file = request.FILES['csv_file']
            if not uploaded_file.name.endswith('.csv'):
                context['error'] = "Please upload a valid CSV file."
                return render(request, 'extractor/index.html', context)

            unique_suppliers = {}
            try:
                decoded_file = uploaded_file.read().decode('utf-8-sig')
                io_string = io.StringIO(decoded_file)
                reader = csv.reader(io_string)
                header = next(reader)
                try:
                    company_col_index = [h.lower().strip() for h in header].index('company name')
                except ValueError:
                    context['error'] = "CSV must have a 'Company Name' column."
                    return render(request, 'extractor/index.html', context)

                for row in reader:
                    company_name = row[company_col_index].strip()
                    if not company_name: continue

                    results = search_emails(company_name, user_email)
                    if not results: continue

                    for supplier in results:
                        if '@cummins.com' in supplier.get('email', '').lower(): continue
                        
                        if supplier['email'] not in unique_suppliers:
                            unique_suppliers[supplier['email']] = supplier
                            
                            # Save to Database
                            Supplier.objects.update_or_create(
                                email=supplier['email'],
                                defaults={
                                    'company': supplier['company'],
                                    'name': supplier['name'],
                                    'number': supplier['number']
                                }
                            )
                            
                            # --- NEW: Sync to Google Sheet ---
                            sync_supplier_to_sheet(supplier, worksheet)
                            # --- END NEW ---
                
                all_results = list(unique_suppliers.values())
                request.session['results'] = all_results
                context['results'] = all_results
                context['query'] = f"Bulk search from {uploaded_file.name}"
                context['is_bulk_search'] = True

            except Exception as e:
                context['error'] = f"Error processing CSV: {e}"
        else:
            # Single query search logic
            query = request.POST.get('query', '')
            if query and user_email:
                results = search_emails(query, user_email)
                if results is not None:
                    filtered_results = [
                        supplier for supplier in results
                        if '@cummins.com' not in supplier.get('email', '').lower()
                    ]
                    for supplier in filtered_results:
                        # Save to Database
                        Supplier.objects.update_or_create(
                            email=supplier['email'],
                            defaults={
                                'company': supplier['company'],
                                'name': supplier['name'],
                                'number': supplier['number']
                            }
                        )
                        
                        # --- NEW: Sync to Google Sheet ---
                        sync_supplier_to_sheet(supplier, worksheet)
                        # --- END NEW ---
                        
                    request.session['results'] = filtered_results
                    context['results'] = filtered_results
                    context['query'] = query
                else:
                    context['error'] = "Could not connect to email server. Check credentials and IMAP settings."

    return render(request, 'extractor/index.html', context)

def download_csv(request):
    """Supplier data ko CSV ke roop mein export karta hai."""
    results = Supplier.objects.all()
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="suppliers.csv"'

    writer = csv.writer(response)
    writer.writerow(['Company Name', 'Email Address', 'Contact Name', 'Contact Number'])

    for item in results:
        writer.writerow([
            item.company or 'N/A',
            item.email or 'N/A',
            item.name or 'N/A',
            item.number or 'N/A'
        ])

    return response

# --- NEW: Optional Full Sync View ---
# This view will sync your *entire* local database to Google Sheets at once.
# It's useful if your sheet gets out of sync.

def sync_all_to_google_sheet(request):
    """
    DANGER: This function REPLACES the entire Google Sheet
    with data from your local database.
    """
    worksheet = get_google_worksheet()
    if not worksheet:
        return JsonResponse({"status": "error", "message": "Could not connect to Google Sheet."}, status=500)

    try:
        # Get all suppliers from DB
        suppliers = Supplier.objects.all().order_by('company')
        
        # Prepare data for bulk update
        header = ['Company Name', 'Email Address', 'Contact Name', 'Contact Number']
        data_to_write = [header]
        
        for item in suppliers:
            data_to_write.append([
                item.company or 'N/A',
                item.email or 'N/A',
                item.name or 'N/A',
                item.number or 'N/A'
            ])
        
        # Clear the sheet and write all data at once
        worksheet.clear()
        worksheet.update('A1', data_to_write)
        
        return redirect('search_view') # Redirect back to main page
    
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)

# --- END NEW ---