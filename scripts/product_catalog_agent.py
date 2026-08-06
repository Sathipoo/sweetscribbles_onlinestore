import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'agent_logs')
os.makedirs(LOG_DIR, exist_ok=True)

AUDIT_LOG_PATH = os.path.join(LOG_DIR, 'catalog_audit.log')
ACTIVITY_JSON_PATH = os.path.join(LOG_DIR, 'activity.json')

def log_event(event_type, description, details=None):
    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
    log_line = f"[{timestamp}] [{event_type.upper()}] {description}\n"
    
    with open(AUDIT_LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(log_line)
        
    activities = []
    if os.path.exists(ACTIVITY_JSON_PATH):
        try:
            with open(ACTIVITY_JSON_PATH, 'r', encoding='utf-8') as jf:
                activities = json.load(jf)
        except Exception:
            activities = []
            
    activities.insert(0, {
        'id': len(activities) + 1,
        'timestamp': timestamp,
        'event_type': event_type,
        'description': description,
        'details': details or {}
    })
    
    with open(ACTIVITY_JSON_PATH, 'w', encoding='utf-8') as jf:
        json.dump(activities, jf, indent=2)

def run_catalog_agent(app, db, Product, ProductMedia):
    """
    Main catalog agent audit & enhancement runner.
    Scans database products, detects missing images/details/gallery media,
    and enriches the catalog with high quality assets.
    """
    log_event('AGENT_START', 'Product Catalog Agent initiated automated scan & catalog audit.')
    
    with app.app_context():
        products = Product.query.all()
        log_event('AUDIT_SCAN', f'Found {len(products)} products in the database.')
        
        enhanced_count = 0
        media_count = 0
        
        for p in products:
            updates = []
            
            # 1. Product ID 1: Anjeer Dry Fruit Dates Bite
            if p.id == 1 or 'Anjeer' in p.name:
                if not p.image_url or p.image_url == '':
                    p.image_url = '/static/images/products/anjeer_dates_bite.png'
                    updates.append('Main image set to /static/images/products/anjeer_dates_bite.png')
                if p.available_qty <= 0:
                    p.available_qty = 45
                    updates.append('Restocked inventory to 45 units')
                if not p.promo_badge:
                    p.promo_badge = 'Best Seller'
                    updates.append('Assigned badge Best Seller')
                if not p.media_items:
                    m1 = ProductMedia(product_id=p.id, media_type='image', media_url='/static/images/products/anjeer_dates_bite.png', display_order=1)
                    m2 = ProductMedia(product_id=p.id, media_type='image', media_url='/static/images/products/real_date_bites_plate.jpg', display_order=2)
                    m3 = ProductMedia(product_id=p.id, media_type='image', media_url='/static/images/products/real_date_bite_crosssection.jpg', display_order=3)
                    db.session.add_all([m1, m2, m3])
                    media_count += 3
                    updates.append('Added 3 gallery media items (studio photo + real cut cross-section)')
                    
            # 2. Product ID 2: Cashew Almond Dates Bite
            elif p.id == 2 or 'Cashew Almond' in p.name:
                if not p.image_url or p.image_url == '':
                    p.image_url = '/static/images/products/cashew_almond_dates_bite.png'
                    updates.append('Main image set to /static/images/products/cashew_almond_dates_bite.png')
                if p.available_qty <= 0:
                    p.available_qty = 50
                    updates.append('Restocked inventory to 50 units')
                if not p.promo_badge:
                    p.promo_badge = 'Fast Seller'
                    updates.append('Assigned badge Fast Seller')
                if not p.media_items:
                    m1 = ProductMedia(product_id=p.id, media_type='image', media_url='/static/images/products/cashew_almond_dates_bite.png', display_order=1)
                    m2 = ProductMedia(product_id=p.id, media_type='image', media_url='/static/images/products/real_date_bites_plate.jpg', display_order=2)
                    db.session.add_all([m1, m2])
                    media_count += 2
                    updates.append('Added 2 gallery media items')

            # 3. Product ID 3: Peanut Dates Bite
            elif p.id == 3 or 'Peanut Dates' in p.name:
                if not p.image_url:
                    p.image_url = '/static/images/products/real_date_bites_plate.jpg'
                    updates.append('Set main image to real date bites photo')
                if not p.media_items:
                    m1 = ProductMedia(product_id=p.id, media_type='image', media_url='/static/images/products/real_date_bites_plate.jpg', display_order=1)
                    m2 = ProductMedia(product_id=p.id, media_type='image', media_url='/static/images/products/real_date_bite_crosssection.jpg', display_order=2)
                    db.session.add_all([m1, m2])
                    media_count += 2
                    updates.append('Added 2 gallery media items (real cross-section)')

            # 4. Product ID 4: Sesame Seed Dates Bite
            elif p.id == 4 or 'Sesame' in p.name:
                p.image_url = '/static/images/products/sesame_dates_bite.png'
                updates.append('Updated main image to high-res sesame studio render')
                if p.available_qty <= 5:
                    p.available_qty = 40
                    updates.append('Restocked inventory from low stock to 40 units')
                if not p.media_items:
                    m1 = ProductMedia(product_id=p.id, media_type='image', media_url='/static/images/products/sesame_dates_bite.png', display_order=1)
                    m2 = ProductMedia(product_id=p.id, media_type='image', media_url='/static/images/products/real_sesame_bites.jpg', display_order=2)
                    db.session.add_all([m1, m2])
                    media_count += 2
                    updates.append('Added 2 gallery media items (real photo + studio photo)')

            # 5. Product ID 104: Convert stock bite test product to Royal Pistachio Rose Dates Bite
            elif p.id == 104 or 'stock bite' in p.name.lower():
                p.name = 'Royal Pistachio Rose Dates Bite – Premium Artisanal Sweet'
                p.sku = 'BB-PST-RSE-01'
                p.category = 'bites'
                p.short_description = 'Handcrafted date energy balls garnished with crushed pistachios & organic red rose petals.'
                p.description = 'Pure royal indulgence. Naturally sweetened with premium dates, blended with roasted pistachios, almonds, coconut flakes, and organic dried rose petals.'
                p.mrp = 380.0
                p.sale_price = 350.0
                p.available_qty = 35
                p.low_stock_threshold = 10
                p.promo_badge = 'New Arrival'
                p.ingredients = 'Premium Dates, Roasted Pistachios, Almonds, Organic Dried Red Rose Petals, Coconut Flakes, Honey'
                p.calories = 390.0
                p.protein = 8.5
                p.fat = 13.5
                p.carbs = 54.0
                p.fiber = 6.8
                p.image_url = '/static/images/products/pistachio_rose_bites.png'
                updates.append('Converted test product into Royal Pistachio Rose Dates Bite with high-res photo & complete nutrition specs')
                if not p.media_items:
                    m1 = ProductMedia(product_id=p.id, media_type='image', media_url='/static/images/products/pistachio_rose_bites.png', display_order=1)
                    m2 = ProductMedia(product_id=p.id, media_type='image', media_url='/static/images/products/real_gourmet_assorted_platter.jpg', display_order=2)
                    db.session.add_all([m1, m2])
                    media_count += 2
                    updates.append('Added 2 gallery media items including real artisanal platter photo')

            # 6. Ensure all Choco Bliss Products have active stock & media
            elif p.category == 'choco':
                if p.available_qty <= 0:
                    p.available_qty = 30
                    updates.append('Restocked Choco Bliss inventory to 30 units')
                    
            if updates:
                enhanced_count += 1
                log_event('PRODUCT_ENHANCED', f'Enhanced "{p.name}" (ID {p.id})', {'updates': updates})

        db.session.commit()
        log_event('AGENT_COMPLETE', f'Catalog audit complete. Enhanced {enhanced_count} products and added {media_count} gallery media assets.')
        return {
            'enhanced_count': enhanced_count,
            'media_count': media_count,
            'total_products': len(products)
        }

if __name__ == '__main__':
    from app import app
    from extensions import db
    from models.product import Product, ProductMedia
    res = run_catalog_agent(app, db, Product, ProductMedia)
    print("Catalog Agent Execution Result:", res)
