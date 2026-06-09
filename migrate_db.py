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
        
    db.session.commit()
    print("Migration completed successfully.")

