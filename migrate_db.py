from app import create_app
from extensions import db
from sqlalchemy import text

app = create_app()

with app.app_context():
    print("Running migration to add new columns if they do not exist...")
    
    try:
        # Check and add promo_badge to products
        db.session.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS promo_badge VARCHAR(50);"))
        print("Column 'promo_badge' checked/added to 'products' table.")
    except Exception as e:
        print(f"Error adding promo_badge: {e}")
        
    try:
        # Check and add is_stock_deducted to orders
        db.session.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS is_stock_deducted BOOLEAN DEFAULT FALSE;"))
        # Set default value for existing rows
        db.session.execute(text("UPDATE orders SET is_stock_deducted = FALSE WHERE is_stock_deducted IS NULL;"))
        # Alter column to be NOT NULL
        db.session.execute(text("ALTER TABLE orders ALTER COLUMN is_stock_deducted SET NOT NULL;"))
        print("Column 'is_stock_deducted' checked/added/updated in 'orders' table.")
    except Exception as e:
        print(f"Error adding is_stock_deducted: {e}")
        
    try:
        # Check and add zoho_payment_link_id to orders
        db.session.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS zoho_payment_link_id VARCHAR(100);"))
        print("Column 'zoho_payment_link_id' checked/added to 'orders' table.")
    except Exception as e:
        print(f"Error adding zoho_payment_link_id: {e}")
        
    try:
        # Check and create collections table
        db.session.execute(text("""
            CREATE TABLE IF NOT EXISTS collections (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) UNIQUE NOT NULL,
                slug VARCHAR(100) UNIQUE NOT NULL,
                description TEXT,
                theme_class VARCHAR(50) DEFAULT 'theme-bites'
            );
        """))
        print("Table 'collections' checked/created.")
        
        # Seed default collections
        db.session.execute(text("""
            INSERT INTO collections (name, slug, description, theme_class)
            VALUES 
                ('Daily Nutritional Bites', 'bites', 'Pure Taste, Zero Guilt', 'theme-bites'),
                ('Choco Bliss Bites', 'choco', 'Clean Indulgence, Honest Ingredients', 'theme-choco'),
                ('Gifting & Celebrations', 'gifting', 'Handcrafted Happiness, Custom Curations', 'theme-gifting')
            ON CONFLICT (slug) DO NOTHING;
        """))
        print("Default collections seeded.")
    except Exception as e:
        print(f"Error creating/seeding collections: {e}")
        
    try:
        # Check and add box_weight and box_quantity to products
        db.session.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS box_weight VARCHAR(50) DEFAULT '250g';"))
        db.session.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS box_quantity INTEGER DEFAULT 12;"))
        db.session.execute(text("UPDATE products SET box_weight = '250g' WHERE box_weight IS NULL;"))
        db.session.execute(text("UPDATE products SET box_quantity = 12 WHERE box_quantity IS NULL;"))
        print("Columns 'box_weight' and 'box_quantity' checked/added to 'products' table.")
    except Exception as e:
        print(f"Error adding box_weight/box_quantity: {e}")

    try:
        # Check and add max_discount, min_order_amount, created_at to coupons
        db.session.execute(text("ALTER TABLE coupons ADD COLUMN IF NOT EXISTS max_discount FLOAT;"))
        db.session.execute(text("ALTER TABLE coupons ADD COLUMN IF NOT EXISTS min_order_amount FLOAT DEFAULT 0.0;"))
        db.session.execute(text("ALTER TABLE coupons ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;"))
        print("Columns 'max_discount', 'min_order_amount', 'created_at' checked/added to 'coupons' table.")
    except Exception as e:
        print(f"Error updating coupons table: {e}")

    try:
        # Check and add coupon_code, discount_amount, shipping_fee to orders
        db.session.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS coupon_code VARCHAR(50);"))
        db.session.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_amount FLOAT DEFAULT 0.0;"))
        db.session.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_fee FLOAT DEFAULT 0.0;"))
        print("Columns 'coupon_code', 'discount_amount', 'shipping_fee' checked/added to 'orders' table.")
    except Exception as e:
        print(f"Error updating orders table: {e}")

    try:
        # Check and create site_settings table
        db.session.execute(text("""
            CREATE TABLE IF NOT EXISTS site_settings (
                id SERIAL PRIMARY KEY,
                key VARCHAR(50) UNIQUE NOT NULL,
                value VARCHAR(255) NOT NULL,
                description VARCHAR(255)
            );
        """))
        print("Table 'site_settings' checked/created.")
        
        # Seed default shipping settings
        db.session.execute(text("""
            INSERT INTO site_settings (key, value, description)
            VALUES 
                ('free_shipping_threshold', '999.0', 'Minimum order net total (₹) for FREE shipping'),
                ('flat_shipping_fee', '50.0', 'Standard flat shipping fee (₹) for orders below threshold'),
                ('shipping_enabled', 'true', 'Master switch to enable/disable shipping charges')
            ON CONFLICT (key) DO NOTHING;
        """))
        print("Default shipping settings seeded.")
    except Exception as e:
        print(f"Error creating/seeding site_settings: {e}")

    try:
        # Check and create banners table
        db.session.execute(text("""
            CREATE TABLE IF NOT EXISTS banners (
                id SERIAL PRIMARY KEY,
                title VARCHAR(150),
                subtitle VARCHAR(255),
                image_url VARCHAR(255) NOT NULL,
                mobile_image_url VARCHAR(255),
                link_url VARCHAR(255) DEFAULT '/collections',
                button_text VARCHAR(100) DEFAULT 'Shop Now',
                promo_code VARCHAR(50),
                display_order INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        print("Table 'banners' checked/created.")
        
        # Seed default banners
        db.session.execute(text("""
            INSERT INTO banners (title, subtitle, image_url, link_url, button_text, promo_code, display_order, is_active)
            VALUES 
                ('Wishing You a Happy Independence Day', 'Use code FREEDOM15 to get a flat 15% off', '/static/images/banners/banner_independence_day.jpg', '/collections', 'Claim 15% OFF', 'FREEDOM15', 1, TRUE),
                ('Sweet Scribbles Confectionery', 'Naturally Sweet. Thoughtfully Crafted. 100% Natural Ingredients.', '/static/images/banners/banner_hero_products.png', '/collections', 'Explore Range', NULL, 2, TRUE)
            ON CONFLICT DO NOTHING;
        """))
        print("Default banners seeded.")
    except Exception as e:
        print(f"Error creating/seeding banners: {e}")

    db.session.commit()
    print("Migration completed successfully.")


