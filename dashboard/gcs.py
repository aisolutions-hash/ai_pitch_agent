import json
import logging
from django.conf import settings
from google.cloud import storage
from google.oauth2 import service_account

logger = logging.getLogger(__name__)


def _get_gcs_client():
    """Initialize and return a GCS client."""
    try:
        if settings.GCS_KEY_PATH:
            # Use service account key file
            credentials = service_account.Credentials.from_service_account_file(
                settings.GCS_KEY_PATH
            )
            client = storage.Client(credentials=credentials)
        else:
            # Use default credentials (e.g., environment variables)
            client = storage.Client()
        return client
    except Exception as e:
        logger.error(f"Failed to initialize GCS client: {e}")
        return None


def _get_bucket():
    """Get the GCS bucket."""
    try:
        client = _get_gcs_client()
        if not client:
            return None
        bucket = client.bucket(settings.GCS_BUCKET_NAME)
        return bucket
    except Exception as e:
        logger.error(f"Failed to get bucket: {e}")
        return None


def upload_contact(category, uid, data_dict):
    """
    Upload a contact as JSON to GCS.
    
    Args:
        category (str): Category/folder name
        uid (str): Unique identifier for the contact
        data_dict (dict): Data to upload as JSON
    
    Returns:
        bool: True on success, None on error
    """
    try:
        bucket = _get_bucket()
        if not bucket:
            logger.error("Unable to get GCS bucket")
            return None
        
        blob_path = f"contacts/{category}/{uid}.json"
        blob = bucket.blob(blob_path)
        
        json_data = json.dumps(data_dict)
        blob.upload_from_string(
            json_data,
            content_type='application/json'
        )
        
        logger.info(f"Successfully uploaded contact to {blob_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to upload contact: {e}")
        return None


def list_contacts(category):
    """
    List all contacts in a category.
    
    Args:
        category (str): Category/folder name
    
    Returns:
        list: List of dicts with 'uid' and 'data' keys, None on error
    """
    try:
        bucket = _get_bucket()
        if not bucket:
            logger.error("Unable to get GCS bucket")
            return None
        
        prefix = f"contacts/{category}/"
        blobs = bucket.list_blobs(prefix=prefix)
        
        contacts = []
        for blob in blobs:
            # Skip folder-like objects
            if blob.name.endswith('/'):
                continue
            
            try:
                # Extract uid from blob name (contacts/category/uid.json -> uid)
                uid = blob.name.replace(prefix, '').replace('.json', '')
                json_data = blob.download_as_string()
                data = json.loads(json_data)
                contacts.append({
                    'uid': uid,
                    'data': data
                })
            except Exception as e:
                logger.warning(f"Failed to parse blob {blob.name}: {e}")
                continue
        
        logger.info(f"Successfully listed {len(contacts)} contacts in category {category}")
        return contacts
    except Exception as e:
        logger.error(f"Failed to list contacts: {e}")
        return None


def get_contact(category, uid):
    """
    Download and return a single contact.
    
    Args:
        category (str): Category/folder name
        uid (str): Unique identifier for the contact
    
    Returns:
        dict: Contact data, None on error
    """
    try:
        bucket = _get_bucket()
        if not bucket:
            logger.error("Unable to get GCS bucket")
            return None
        
        blob_path = f"contacts/{category}/{uid}.json"
        blob = bucket.blob(blob_path)
        
        if not blob.exists():
            logger.warning(f"Contact not found: {blob_path}")
            return None
        
        json_data = blob.download_as_string()
        data = json.loads(json_data)
        
        logger.info(f"Successfully retrieved contact from {blob_path}")
        return data
    except Exception as e:
        logger.error(f"Failed to get contact: {e}")
        return None


def delete_contact(category, uid):
    """
    Delete a contact from GCS.
    
    Args:
        category (str): Category/folder name
        uid (str): Unique identifier for the contact
    
    Returns:
        bool: True on success, None on error
    """
    try:
        bucket = _get_bucket()
        if not bucket:
            logger.error("Unable to get GCS bucket")
            return None
        
        blob_path = f"contacts/{category}/{uid}.json"
        blob = bucket.blob(blob_path)
        
        blob.delete()
        
        logger.info(f"Successfully deleted contact from {blob_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete contact: {e}")
        return None


def upload_csv_file(category, file_obj, filename):
    """
    Upload a CSV file to GCS under contacts/{category}/.
    
    Args:
        category (str): Category/folder name
        file_obj (file-like): The CSV file object to upload
        filename (str): The name to save the file as (should end in .csv)
    
    Returns:
        str: The blob path on success, None on error
    """
    try:
        bucket = _get_bucket()
        if not bucket:
            logger.error("Unable to get GCS bucket")
            return None

        if not filename.lower().endswith('.csv'):
            filename = filename + '.csv'

        blob_path = f"contacts/{category}/{filename}"
        blob = bucket.blob(blob_path)

        file_obj.seek(0)
        blob.upload_from_string(
            file_obj.read(),
            content_type='text/csv'
        )

        logger.info(f"Successfully uploaded CSV to {blob_path}")
        return blob_path
    except Exception as e:
        logger.error(f"Failed to upload CSV: {e}")
        return None


def list_csv_files(category):
    """
    List all CSV files in a category folder.
    
    Args:
        category (str): Category/folder name
    
    Returns:
        list: List of dicts with file info (name, size, updated, blob_path)
    """
    try:
        bucket = _get_bucket()
        if not bucket:
            logger.error("Unable to get GCS bucket")
            return None

        prefix = f"contacts/{category}/"
        blobs = bucket.list_blobs(prefix=prefix)

        csv_files = []
        for blob in blobs:
            if blob.name.endswith('.csv'):
                csv_files.append({
                    'name': blob.name.replace(prefix, ''),
                    'size': blob.size,
                    'size_display': _format_size(blob.size),
                    'updated': blob.updated.isoformat() if blob.updated else None,
                    'blob_path': blob.name,
                    'category': category
                })

        csv_files.sort(key=lambda x: x['updated'] or '', reverse=True)
        return csv_files
    except Exception as e:
        logger.error(f"Failed to list CSV files: {e}")
        return None


def get_csv_file(category, filename):
    """
    Get a CSV file's content and metadata from GCS.
    
    Args:
        category (str): Category/folder name
        filename (str): CSV file name
    
    Returns:
        dict: Content and metadata, None on error
    """
    try:
        bucket = _get_bucket()
        if not bucket:
            logger.error("Unable to get GCS bucket")
            return None

        blob_path = f"contacts/{category}/{filename}"
        blob = bucket.blob(blob_path)

        if not blob.exists():
            logger.warning(f"CSV file not found: {blob_path}")
            return None

        content = blob.download_as_string()
        return {
            'name': filename,
            'content': content.decode('utf-8'),
            'size': blob.size,
            'size_display': _format_size(blob.size),
            'updated': blob.updated.isoformat() if blob.updated else None,
            'content_type': blob.content_type
        }
    except Exception as e:
        logger.error(f"Failed to get CSV file: {e}")
        return None


def delete_csv_file(category, filename):
    """
    Delete a CSV file from GCS.
    
    Args:
        category (str): Category/folder name
        filename (str): CSV file name
    
    Returns:
        bool: True on success, None on error
    """
    try:
        bucket = _get_bucket()
        if not bucket:
            logger.error("Unable to get GCS bucket")
            return None

        blob_path = f"contacts/{category}/{filename}"
        blob = bucket.blob(blob_path)

        blob.delete()
        logger.info(f"Successfully deleted CSV from {blob_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete CSV file: {e}")
        return None


def _format_size(size_bytes):
    """Format file size in human-readable format."""
    if size_bytes is None:
        return 'Unknown'
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


# ---------------------------------------------------------------------------
# Scheduled Scraper: keyword config + run history storage
# ---------------------------------------------------------------------------

RUNS_PREFIX = 'scraper_runs/'
KEYWORDS_CONFIG_PATH = 'scraper_config/keywords.json'
LOCATIONS_CONFIG_PATH = 'scraper_config/locations.json'
PROGRESS_PATH = 'scraper_config/progress.json'
STATS_PATH = 'scraper_config/stats.json'

# Default keywords seeded on first use (as requested)
DEFAULT_SCRAPE_KEYWORDS = [
    'ai automation',
    'real estate',
    'agentic ai',
    'manufacturing company',
]

# Default locations seeded on first use
DEFAULT_SCRAPE_LOCATIONS = [
    'USA',
    'Australia',
    'UAE',
    'New Zealand',
]


def upload_json_blob(blob_path, data):
    """Upload an arbitrary JSON payload to a blob path. Returns True on success."""
    try:
        bucket = _get_bucket()
        if not bucket:
            logger.error("Unable to get GCS bucket")
            return None
        blob = bucket.blob(blob_path)
        blob.upload_from_string(json.dumps(data), content_type='application/json')
        logger.info(f"Successfully uploaded JSON to {blob_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to upload JSON to {blob_path}: {e}")
        return None


def get_json_blob(blob_path):
    """Download and parse a JSON blob. Returns the parsed data or None."""
    try:
        bucket = _get_bucket()
        if not bucket:
            logger.error("Unable to get GCS bucket")
            return None
        blob = bucket.blob(blob_path)
        if not blob.exists():
            logger.warning(f"JSON blob not found: {blob_path}")
            return None
        return json.loads(blob.download_as_string())
    except Exception as e:
        logger.error(f"Failed to get JSON blob {blob_path}: {e}")
        return None


def get_scrape_keywords():
    """
    Get the configured scrape keywords from GCS.
    Seeds defaults on first use. Returns a list of dicts:
    [{'keyword': str, 'active': bool, 'created_at': str}, ...]
    """
    data = get_json_blob(KEYWORDS_CONFIG_PATH)
    if data is None:
        keywords = [
            {'keyword': kw, 'active': True, 'created_at': None}
            for kw in DEFAULT_SCRAPE_KEYWORDS
        ]
        save_scrape_keywords(keywords)
        return keywords
    return data.get('keywords', [])


def save_scrape_keywords(keywords):
    """Persist the keyword list to GCS. Returns True on success."""
    return upload_json_blob(KEYWORDS_CONFIG_PATH, {'keywords': keywords})


def get_scrape_locations():
    """
    Get the configured scrape locations from GCS.
    Seeds defaults on first use. Returns a list of dicts:
    [{'location': str, 'active': bool, 'created_at': str}, ...]
    """
    data = get_json_blob(LOCATIONS_CONFIG_PATH)
    if data is None:
        locations = [
            {'location': loc, 'active': True, 'created_at': None}
            for loc in DEFAULT_SCRAPE_LOCATIONS
        ]
        save_scrape_locations(locations)
        return locations
    return data.get('locations', [])


def save_scrape_locations(locations):
    """Persist the location list to GCS. Returns True on success."""
    return upload_json_blob(LOCATIONS_CONFIG_PATH, {'locations': locations})


def upload_scrape_run(run_path, payload):
    """Upload a scrape-run result batch. run_path is relative to RUNS_PREFIX."""
    return upload_json_blob(f"{RUNS_PREFIX}{run_path}", payload)


def list_scrape_runs(limit=200):
    """
    List historical scrape runs from GCS, newest first.
    Returns a list of dicts: {name, path, date, keyword_slug, size, size_display, updated}
    """
    try:
        bucket = _get_bucket()
        if not bucket:
            logger.error("Unable to get GCS bucket")
            return []

        blobs = bucket.list_blobs(prefix=RUNS_PREFIX)
        runs = []
        for blob in blobs:
            if not blob.name.endswith('.json'):
                continue
            rel = blob.name.replace(RUNS_PREFIX, '')
            parts = rel.split('/')
            date_str = parts[0] if len(parts) > 1 else ''
            keyword_slug = parts[-1].replace('.json', '')
            runs.append({
                'name': rel,
                'path': blob.name,
                'date': date_str,
                'keyword_slug': keyword_slug,
                'size': blob.size,
                'size_display': _format_size(blob.size),
                'updated': blob.updated.isoformat() if blob.updated else None,
            })

        runs.sort(key=lambda x: x['updated'] or '', reverse=True)
        return runs[:limit]
    except Exception as e:
        logger.error(f"Failed to list scrape runs: {e}")
        return []


def get_scrape_run(run_path):
    """
    Fetch a single scrape-run batch by full blob path.
    Validates the path stays under RUNS_PREFIX to prevent path traversal.
    """
    if not run_path or not run_path.startswith(RUNS_PREFIX) or '..' in run_path:
        logger.warning(f"Invalid scrape run path requested: {run_path}")
        return None
    return get_json_blob(run_path)


def get_scrape_progress():
    """
    Get the current/last scrape run's progress state.
    Returns a dict or None if no run has been recorded yet.
    """
    return get_json_blob(PROGRESS_PATH)


def save_scrape_progress(data):
    """Persist scrape run progress (called by the running scrape job)."""
    return upload_json_blob(PROGRESS_PATH, data)


def get_scrape_stats():
    """Get the list of per-keyword run stat entries (newest last)."""
    data = get_json_blob(STATS_PATH)
    if not data:
        return []
    return data.get('entries', [])


def append_scrape_stat(entry, cap=1000):
    """Append a per-keyword run stat entry (keeps the last `cap` entries)."""
    entries = get_scrape_stats()
    entries.append(entry)
    entries = entries[-cap:]
    return upload_json_blob(STATS_PATH, {'entries': entries})


# ---------------------------------------------------------------------------
# Auto Campaign Engine: config + run history storage
# ---------------------------------------------------------------------------

CAMPAIGN_CONFIG_PATH = 'campaign_config/config.json'
CAMPAIGN_PROGRESS_PATH = 'campaign_config/progress.json'
CAMPAIGN_RUNS_PREFIX = 'campaign_runs/'


def get_campaign_config():
    """
    Get the configured auto-campaign settings from GCS.
    Returns a dict or a default config when nothing is saved yet.
    """
    data = get_json_blob(CAMPAIGN_CONFIG_PATH)
    if not data:
        return {
            'category': 'suppliers',
            'template_id': None,
            'daily_limit': 25,
            'personalize_subject': True,
            'personalize_body': True,
        }
    return data


def save_campaign_config(config):
    """Persist the auto-campaign config to GCS. Returns True on success."""
    return upload_json_blob(CAMPAIGN_CONFIG_PATH, config)


def get_campaign_progress():
    """
    Get the current/last auto-campaign run's progress state.
    Returns a dict or None if no run has been recorded yet.
    """
    return get_json_blob(CAMPAIGN_PROGRESS_PATH)


def save_campaign_progress(data):
    """Persist auto-campaign run progress (called by the running campaign job)."""
    return upload_json_blob(CAMPAIGN_PROGRESS_PATH, data)


def upload_campaign_run(run_path, payload):
    """Upload a campaign-run result batch. run_path is relative to CAMPAIGN_RUNS_PREFIX."""
    return upload_json_blob(f"{CAMPAIGN_RUNS_PREFIX}{run_path}", payload)


def list_campaign_runs(limit=100):
    """
    List historical auto-campaign runs from GCS, newest first.
    Returns a list of dicts: {name, path, date, size, size_display, updated}
    """
    try:
        bucket = _get_bucket()
        if not bucket:
            logger.error("Unable to get GCS bucket")
            return []

        blobs = bucket.list_blobs(prefix=CAMPAIGN_RUNS_PREFIX)
        runs = []
        for blob in blobs:
            if not blob.name.endswith('.json'):
                continue
            rel = blob.name.replace(CAMPAIGN_RUNS_PREFIX, '')
            runs.append({
                'name': rel,
                'path': blob.name,
                'size': blob.size,
                'size_display': _format_size(blob.size),
                'updated': blob.updated.isoformat() if blob.updated else None,
            })

        runs.sort(key=lambda x: x['updated'] or '', reverse=True)
        return runs[:limit]
    except Exception as e:
        logger.error(f"Failed to list campaign runs: {e}")
        return []


def get_campaign_run(run_path):
    """
    Fetch a single auto-campaign run batch by full blob path.
    Validates the path stays under CAMPAIGN_RUNS_PREFIX to prevent path traversal.
    """
    if not run_path or not run_path.startswith(CAMPAIGN_RUNS_PREFIX) or '..' in run_path:
        logger.warning(f"Invalid campaign run path requested: {run_path}")
        return None
    return get_json_blob(run_path)
