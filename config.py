import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    if SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Engine Options to prevent timeouts on remote DB connections
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 280
    }
    
    # GCP Storage Config
    GOOGLE_APPLICATION_CREDENTIALS = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    GCS_BUCKET_NAME = os.environ.get('GCS_BUCKET_NAME')
    
    # Zoho Payments
    ZOHO_CLIENT_ID = os.environ.get('ZOHO_CLIENT_ID')
    ZOHO_CLIENT_SECRET = os.environ.get('ZOHO_CLIENT_SECRET')
    ZOHO_REFRESH_TOKEN = os.environ.get('ZOHO_REFRESH_TOKEN')
    ZOHO_BILLING_ORG_ID = os.environ.get('ZOHO_BILLING_ORG_ID')
    ZOHO_PAYMENTS_ACCOUNT_ID = os.environ.get('ZOHO_PAYMENTS_ACCOUNT_ID')
    
    # Admin
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin')
