import os
import json
import uuid
from google.cloud import storage
from werkzeug.utils import secure_filename
from flask import current_app

def get_storage_client():
    """
    Initializes Google Cloud Storage client with multi-environment support:
    1. Local Dev: uses service account JSON file if found on disk.
    2. Raw JSON string in env var (GCP_SERVICE_ACCOUNT_JSON).
    3. Google Cloud Run Native IAM: uses native ADC / Metadata server.
    """
    creds_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    if creds_path:
        if os.path.exists(creds_path):
            try:
                return storage.Client.from_service_account_json(creds_path)
            except Exception as e:
                print(f"WARNING: Failed to load service account file {creds_path}: {e}")
        else:
            # Clean up missing file path from environment so Google SDK
            # falls back directly to Cloud Run's native instance credentials
            os.environ.pop('GOOGLE_APPLICATION_CREDENTIALS', None)
            
    # Check for raw JSON string in environment (useful for containerized envs)
    raw_json = os.environ.get('GCP_SERVICE_ACCOUNT_JSON') or os.environ.get('GOOGLE_CREDENTIALS_JSON')
    if raw_json:
        try:
            return storage.Client.from_service_account_info(json.loads(raw_json))
        except Exception as e:
            print(f"WARNING: Failed to parse GCP_SERVICE_ACCOUNT_JSON: {e}")
            
    # Native Cloud Run ADC authentication
    project_id = os.environ.get('GCP_PROJECT_ID', 'focus-empire-483313-n6')
    try:
        return storage.Client(project=project_id)
    except Exception as e:
        print(f"WARNING: Google Cloud Storage native client init failed: {e}")
        return None

def get_bucket():
    client = get_storage_client()
    if not client:
        return None
    bucket_name = (os.environ.get('GCS_BUCKET_NAME') or 'pika-sweetscribbles').strip().lower()
    if not bucket_name:
        return None
        
    try:
        return client.bucket(bucket_name)
    except Exception as e:
        print(f"WARNING: Failed to get bucket {bucket_name}: {e}")
        return None

def upload_file(file_obj, filename, folder=""):
    """
    Uploads a file to GCS and returns the public URL.
    Gracefully falls back to local static uploads if GCS is unavailable.
    """
    safe_filename = secure_filename(filename)
    unique_filename = f"{uuid.uuid4().hex}_{safe_filename}"
    
    # Try GCS upload first
    try:
        bucket = get_bucket()
        if bucket:
            blob_path = f"{folder}/{unique_filename}" if folder else unique_filename
            blob = bucket.blob(blob_path)
            
            # Reset file pointer if needed
            if hasattr(file_obj, 'seek'):
                file_obj.seek(0)
                
            content_type = getattr(file_obj, 'content_type', None) or 'application/octet-stream'
            blob.upload_from_file(file_obj, content_type=content_type)
            
            # Make the blob public (ignore if Uniform Bucket-Level Access is enforced)
            try:
                blob.make_public()
            except Exception as e:
                pass
            
            return blob.public_url
    except Exception as e:
        print(f"WARNING: GCS upload failed, falling back to local static storage: {e}")

    # Fallback to local storage
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        upload_dir = os.path.join(base_dir, 'static', 'uploads', folder) if folder else os.path.join(base_dir, 'static', 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        
        file_path = os.path.join(upload_dir, unique_filename)
        if hasattr(file_obj, 'seek'):
            file_obj.seek(0)
            
        if hasattr(file_obj, 'save'):
            file_obj.save(file_path)
        else:
            with open(file_path, 'wb') as f:
                f.write(file_obj.read())
        
        if folder:
            return f"/static/uploads/{folder}/{unique_filename}"
        return f"/static/uploads/{unique_filename}"
    except Exception as local_err:
        print(f"ERROR: Local fallback upload failed: {local_err}")
        raise local_err
