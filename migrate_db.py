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
        
    db.session.commit()
    print("Migration completed successfully.")
