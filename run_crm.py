#!/usr/bin/env python3
"""
Sweet Scribbles B2B Growth CRM - Standalone Application Runner
Runs the CRM app independently on port 5002 while sharing the live AWS PostgreSQL database.
"""
import os
from crm.app import create_crm_app
from crm.config import CRMConfig

crm_app = create_crm_app(CRMConfig)

if __name__ == '__main__':
    port = int(os.environ.get('CRM_PORT', 5002))
    debug = os.environ.get('FLASK_DEBUG', 'True').lower() in ['true', '1', 'yes']
    print(f"================================================================")
    print(f"  SWEET SCRIBBLES B2B GROWTH CRM & SALES INTELLIGENCE DESK     ")
    print(f"  Live Radar: http://127.0.0.1:{port}/radar                    ")
    print(f"  Sales Desk: http://127.0.0.1:{port}/leads                    ")
    print(f"================================================================")
    crm_app.run(host='0.0.0.0', port=port, debug=debug)
