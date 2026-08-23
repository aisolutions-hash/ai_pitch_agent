"""
Google Sheets integration for storing and managing LinkedIn scraper data.
"""

import logging
import google.auth
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials
from google.api_core.exceptions import GoogleAPIError
import gspread
from django.conf import settings

logger = logging.getLogger(__name__)

# Scopes for Google Sheets API
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

# Column headers for LinkedIn profiles
HEADERS = [
    'Name',
    'Company Name',
    'Location',
    'LinkedIn URL',
    'Intent',
    'Pain Points',
    'AI Need Score',
    'Branding Need Score',
    'Email Address',
    'Phone Number',
    'Pitches (LinkedIn)',
    'Pitches (Email)',
    'Pitches (WhatsApp)',
    'Industry',
    'Seniority Level',
    'Company Size',
    'Contact Priority',
    'Created At',
    'Last Updated'
]


def _get_gsheet_client():
    """Initialize and return a Google Sheets client."""
    try:
        from sales_project.google_auth import default_or_loaded

        credentials = default_or_loaded(SCOPES)
        client = gspread.authorize(credentials)
        return client
    except Exception as e:
        logger.error(f"Failed to initialize Google Sheets client: {e}")
        return None


def _get_or_create_sheet(spreadsheet_id):
    """
    Get an existing spreadsheet or create a new one.
    
    Args:
        spreadsheet_id (str): Spreadsheet ID (None to create new)
    
    Returns:
        tuple: (spreadsheet, worksheet) or (None, None) on error
    """
    try:
        client = _get_gsheet_client()
        if not client:
            return None, None
        
        if spreadsheet_id:
            # Open existing spreadsheet
            spreadsheet = client.open_by_key(spreadsheet_id)
            worksheet = spreadsheet.sheet1
            logger.info(f"Opened existing spreadsheet: {spreadsheet_id}")

            # Self-heal: ensure the header row exists. Older sheets may have
            # data in row 1 instead of HEADERS, which breaks get_all_records()
            # ("header row contains duplicates") and therefore /scraper/list/.
            try:
                first_row = worksheet.row_values(1)
                if first_row[:2] != HEADERS[:2]:
                    worksheet.insert_row(HEADERS, 1)
                    logger.info("Inserted missing header row into existing spreadsheet")
            except Exception as header_error:
                logger.warning(f"Could not verify/insert header row: {header_error}")
        else:
            # Create new spreadsheet
            spreadsheet = client.create('LinkedIn Profiles')
            worksheet = spreadsheet.sheet1
            worksheet.insert_row(HEADERS, 1)
            spreadsheet_id = spreadsheet.id
            logger.info(f"Created new spreadsheet: {spreadsheet_id}")
        
        return spreadsheet, worksheet
    except GoogleAPIError as e:
        logger.error(f"Google API error: {e}")
        return None, None
    except Exception as e:
        logger.error(f"Error getting/creating sheet: {e}")
        return None, None


def _find_row_by_linkedin_url(worksheet, linkedin_url):
    """
    Find a row index by LinkedIn URL.
    
    Args:
        worksheet: gspread Worksheet object
        linkedin_url (str): LinkedIn profile URL
    
    Returns:
        int: Row index (1-based), None if not found
    """
    try:
        # LinkedIn URL is in column 4
        cell = worksheet.find(linkedin_url)
        if cell:
            return cell.row
        return None
    except Exception as e:
        logger.warning(f"Error finding row: {e}")
        return None


def append_profile(spreadsheet_id, profile_data):
    """
    Append a new LinkedIn profile to the spreadsheet.
    
    Args:
        spreadsheet_id (str): Google Sheets spreadsheet ID
        profile_data (dict): Profile data with keys matching HEADERS
    
    Returns:
        bool: True on success, False on error
    """
    try:
        spreadsheet, worksheet = _get_or_create_sheet(spreadsheet_id)
        if not spreadsheet or not worksheet:
            return False
        
        # Build row data in order of HEADERS
        row_data = [
            profile_data.get('name', ''),
            profile_data.get('company', ''),
            profile_data.get('location', ''),
            profile_data.get('linkedin_url', ''),
            profile_data.get('intent', ''),
            ', '.join(profile_data.get('pain_points', [])),
            str(profile_data.get('ai_need_score', '')),
            str(profile_data.get('branding_need_score', '')),
            profile_data.get('email', ''),
            profile_data.get('phone', ''),
            profile_data.get('pitch_linkedin', ''),
            profile_data.get('pitch_email', ''),
            profile_data.get('pitch_whatsapp', ''),
            profile_data.get('industry', ''),
            profile_data.get('seniority_level', ''),
            profile_data.get('company_size', ''),
            profile_data.get('contact_priority', ''),
            profile_data.get('created_at', ''),
            profile_data.get('updated_at', '')
        ]
        
        # Write to an explicit A:S range instead of worksheet.append_row().
        # The Sheets API table detection used by append_row() breaks when the
        # sheet contains stray data in far-right columns, causing each new row
        # to be appended shifted further to the right (columns grow endlessly).
        col_a = worksheet.col_values(1)  # trailing empties are trimmed
        next_row = len(col_a) + 1
        worksheet.batch_update([{
            'range': f'A{next_row}:S{next_row}',
            'values': [row_data],
        }])
        logger.info(f"Appended profile: {profile_data.get('name')}")
        return True
    except Exception as e:
        logger.error(f"Error appending profile: {e}")
        return False


def update_profile(spreadsheet_id, linkedin_url, profile_data):
    """
    Update an existing LinkedIn profile in the spreadsheet.
    
    Args:
        spreadsheet_id (str): Google Sheets spreadsheet ID
        linkedin_url (str): LinkedIn profile URL to find
        profile_data (dict): Updated profile data
    
    Returns:
        bool: True on success, False on error
    """
    try:
        spreadsheet, worksheet = _get_or_create_sheet(spreadsheet_id)
        if not spreadsheet or not worksheet:
            return False
        
        # Find the row
        row_idx = _find_row_by_linkedin_url(worksheet, linkedin_url)
        if not row_idx:
            logger.warning(f"Profile not found: {linkedin_url}")
            return False
        
        # Build updated row data
        row_data = [
            profile_data.get('name', ''),
            profile_data.get('company', ''),
            profile_data.get('location', ''),
            profile_data.get('linkedin_url', ''),
            profile_data.get('intent', ''),
            ', '.join(profile_data.get('pain_points', [])),
            str(profile_data.get('ai_need_score', '')),
            str(profile_data.get('branding_need_score', '')),
            profile_data.get('email', ''),
            profile_data.get('phone', ''),
            profile_data.get('pitch_linkedin', ''),
            profile_data.get('pitch_email', ''),
            profile_data.get('pitch_whatsapp', ''),
            profile_data.get('industry', ''),
            profile_data.get('seniority_level', ''),
            profile_data.get('company_size', ''),
            profile_data.get('contact_priority', ''),
            profile_data.get('created_at', ''),
            profile_data.get('updated_at', '')
        ]
        
        # Update the row
        worksheet.delete_rows(row_idx)
        worksheet.insert_row(row_data, row_idx)
        
        logger.info(f"Updated profile: {profile_data.get('name')}")
        return True
    except Exception as e:
        logger.error(f"Error updating profile: {e}")
        return False


def delete_profile(spreadsheet_id, linkedin_url):
    """
    Delete a LinkedIn profile from the spreadsheet.
    
    Args:
        spreadsheet_id (str): Google Sheets spreadsheet ID
        linkedin_url (str): LinkedIn profile URL to delete
    
    Returns:
        bool: True on success, False on error
    """
    try:
        spreadsheet, worksheet = _get_or_create_sheet(spreadsheet_id)
        if not spreadsheet or not worksheet:
            return False
        
        # Find and delete the row
        row_idx = _find_row_by_linkedin_url(worksheet, linkedin_url)
        if not row_idx:
            logger.warning(f"Profile not found: {linkedin_url}")
            return False
        
        worksheet.delete_rows(row_idx)
        logger.info(f"Deleted profile at row: {row_idx}")
        return True
    except Exception as e:
        logger.error(f"Error deleting profile: {e}")
        return False


def get_all_profiles(spreadsheet_id):
    """
    Get all profiles from the spreadsheet.
    
    Args:
        spreadsheet_id (str): Google Sheets spreadsheet ID
    
    Returns:
        list: List of profile dicts, None on error
    """
    try:
        spreadsheet, worksheet = _get_or_create_sheet(spreadsheet_id)
        if not spreadsheet or not worksheet:
            return None
        
        # Read positionally instead of get_all_records(): the sheet may have
        # extra/junk columns beyond HEADERS, which makes gspread's header-based
        # parsing fail with "header row contains duplicates".
        all_values = worksheet.get_all_values()
        all_rows = []
        for row in all_values[1:]:  # skip the header row
            padded = (row + [''] * len(HEADERS))[:len(HEADERS)]
            if any(cell.strip() for cell in padded):
                all_rows.append(dict(zip(HEADERS, padded)))
        logger.info(f"Retrieved {len(all_rows)} profiles")
        return all_rows
    except Exception as e:
        logger.error(f"Error getting all profiles: {e}")
        return None


def search_profile_by_email(spreadsheet_id, email):
    """
    Search for a profile by email address.
    
    Args:
        spreadsheet_id (str): Google Sheets spreadsheet ID
        email (str): Email address to search
    
    Returns:
        dict: Profile data if found, None otherwise
    """
    try:
        all_profiles = get_all_profiles(spreadsheet_id)
        if not all_profiles:
            return None
        
        for profile in all_profiles:
            if profile.get('Email Address', '').lower() == email.lower():
                return profile
        
        return None
    except Exception as e:
        logger.error(f"Error searching profile by email: {e}")
        return None


def search_profile_by_name(spreadsheet_id, name):
    """
    Search for profiles by name.
    
    Args:
        spreadsheet_id (str): Google Sheets spreadsheet ID
        name (str): Name to search
    
    Returns:
        list: List of matching profiles
    """
    try:
        all_profiles = get_all_profiles(spreadsheet_id)
        if not all_profiles:
            return []
        
        matches = [p for p in all_profiles if name.lower() in p.get('Name', '').lower()]
        return matches
    except Exception as e:
        logger.error(f"Error searching profiles by name: {e}")
        return []


def export_to_csv(spreadsheet_id, filename=None):
    """
    Export spreadsheet data to CSV.
    
    Args:
        spreadsheet_id (str): Google Sheets spreadsheet ID
        filename (str): Output filename
    
    Returns:
        str: CSV content or None on error
    """
    try:
        import csv
        from io import StringIO
        
        all_profiles = get_all_profiles(spreadsheet_id)
        if not all_profiles:
            return None
        
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(all_profiles)
        
        csv_content = output.getvalue()
        
        if filename:
            with open(filename, 'w') as f:
                f.write(csv_content)
            logger.info(f"Exported to CSV: {filename}")
        
        return csv_content
    except Exception as e:
        logger.error(f"Error exporting to CSV: {e}")
        return None
