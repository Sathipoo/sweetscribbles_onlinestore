import os
from google.cloud import storage
import uuid
from werkzeug.utils import secure_filename

def get_storage_client():
    creds_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    if creds_path and os.path.exists(creds_path):
        return storage.Client.from_service_account_json(creds_path)
    # Fallback to default auth
    return storage.Client()

def get_bucket():
    client = get_storage_client()
    bucket_name = os.environ.get('GCS_BUCKET_NAME', '').lower()
    if not bucket_name:
        raise ValueError("GCS_BUCKET_NAME not configured")
        
    return client.bucket(bucket_name)

def upload_file(file_obj, filename, folder=""):
    """
    Uploads a file to GCS and returns the public URL.
    """
    bucket = get_bucket()
    
    # Secure filename and add unique ID
    safe_filename = secure_filename(filename)
    unique_filename = f"{uuid.uuid4().hex}_{safe_filename}"
    blob_path = f"{folder}/{unique_filename}" if folder else unique_filename
    
    blob = bucket.blob(blob_path)
    blob.upload_from_file(file_obj, content_type=file_obj.content_type)
    
    # Make the blob public
    try:
        blob.make_public()
    except Exception as e:
        print(f"WARNING: could not make blob public (UBLA might be enabled): {e}")
    
    return blob.public_url
