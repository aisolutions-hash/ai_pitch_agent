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
