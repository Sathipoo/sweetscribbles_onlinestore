import os
from config import Config

class CRMConfig(Config):
    """
    Configuration for the Standalone B2B Growth CRM application.
    Uses dedicated session cookies to prevent any collisions with the storefront.
    """
    SESSION_COOKIE_NAME = 'ss_crm_session'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # CRM Sales Operations Credentials
    CRM_ACCESS_KEY = os.environ.get('CRM_ACCESS_KEY', os.environ.get('ADMIN_PASSWORD', 'sweet2026'))
    
    # Base Storefront URL for generating outreach and tracking links
    STORE_BASE_URL = os.environ.get('STORE_BASE_URL', 'https://sweetscribbles.pikachooz.com')
    
    # Standalone Port for local development
    CRM_PORT = int(os.environ.get('CRM_PORT', 5002))
