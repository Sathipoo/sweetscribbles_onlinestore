import os
from app import create_app
from extensions import db
from models.user import User
from models.product import Product, ProductMedia
from models.coupon import Coupon

app = create_app()

with app.app_context():
    print("Dropping existing tables...")
    db.drop_all()

    print("Creating tables...")
    db.create_all()
    
    print("Checking admin user...")
    admin_email = "admin@sweetscribbles.com"
    admin_password = os.environ.get('ADMIN_PASSWORD', 'admin')
    admin = User(email=admin_email, name="Admin", is_admin=True)
    admin.set_password(admin_password)
    db.session.add(admin)
    print(f"Created admin user: {admin_email} / {admin_password}")
    
    print("Adding sample products matching screenshots...")
    
    # Daily Nutritional Bites (bites)
    p1 = Product(
        name="Anjeer Dry Fruit Dates Bite – Premium Fig & Nut Energy Ball",
        sku="BB-ANJ-01",
        category="bites",
        short_description="Naturally sweetened fig & nut energy ball. No sugar, no jaggery.",
        description="Handcrafted dry-fruit sweets made with dates, figs (anjeer), premium nuts, and honest goodness. Zero preservatives.",
        mrp=350.0,
        sale_price=320.0,
        available_qty=0, # Out of stock
        ingredients="Dates, Figs (Anjeer), Almonds, Cashews, Pistachios",
        image_url="" # Placeholder icon as in screenshot
    )
    
    p2 = Product(
        name="Cashew Almond Dates Bite – Premium Dry Fruit Energy Ball",
        sku="BB-CSH-ALM-01",
        category="bites",
        short_description="Naturally sweetened with dates, premium cashews, and almonds.",
        description="Pure dry-fruit sweet sweetened only with dates. High in fiber, healthy fats, and natural clean energy.",
        mrp=280.0,
        sale_price=250.0,
        available_qty=0, # Out of stock
        ingredients="Dates, Cashews, Almonds, Honey",
        image_url="" # Placeholder icon as in screenshot
    )
    
    p3 = Product(
        name="Peanut Dates Bite – Protein-Rich Daily Energy Ball",
        sku="BB-PNT-01",
        category="bites",
        short_description="Protein-rich energy ball sweetened only with dates.",
        description="Handcrafted peanut dates energy balls made in small batches. Perfect for kids, parents, and fitness lovers.",
        mrp=180.0,
        sale_price=155.0,
        available_qty=50, # In stock
        ingredients="Dates, Roasted Peanuts, Sea Salt",
        image_url="/static/images/Gemini_Generated_Image_5qp0wq5qp0wq5qp0.png" # Stack of balls image
    )
    
    p4 = Product(
        name="Sesame Seed Dates Bite – Calcium-Rich Daily Nutrition Ball",
        sku="BB-SSM-01",
        category="bites",
        short_description="Calcium-rich daily nutrition ball sweetened with dates.",
        description="Wholesome sesame seeds blended with rich dates. Handcrafted, high-fiber, and delicious.",
        mrp=200.0,
        sale_price=170.0,
        available_qty=30, # In stock
        ingredients="Dates, Sesame Seeds, Cashews, Almonds",
        image_url="/static/images/Gemini_Generated_Image_kcrjxfkcrjxfkcrj.png" # Reused stack image or similar
    )
    
    # Choco Bliss Bites (choco)
    p5 = Product(
        name="Dark Choco Bliss Bites – Premium Dark Chocolate Dry Fruit Bite",
        sku="CB-DRK-01",
        category="choco",
        short_description="Naturally sweetened dry fruit bite coated with premium dark chocolate.",
        description="Satisfy your chocolate cravings without the guilt. Premium dark couverture chocolate coating over a nutritious dates and nuts center.",
        mrp=220.0,
        sale_price=200.0,
        available_qty=0, # Out of stock
        ingredients="Dates, Almonds, Cashews, Dark Couverture Chocolate (Cocoa mass, Cocoa butter)",
        image_url="/static/images/Gemini_Generated_Image_w08uwnw08uwnw08u.png"
    )
    
    p6 = Product(
        name="Milk Choco Bliss Bites – Premium Milk Chocolate Dry Fruit Bite",
        sku="CB-MLK-01",
        category="choco",
        short_description="Naturally sweetened dry fruit bite coated with premium milk chocolate.",
        description="Indulgent, handcrafted milk chocolate bliss bites. Creamy couverture chocolate coating over a soft, nut-filled dates center.",
        mrp=220.0,
        sale_price=200.0,
        available_qty=0, # Out of stock
        ingredients="Dates, Almonds, Cashews, Milk Couverture Chocolate",
        image_url="/static/images/Gemini_Generated_Image_kcrjxfkcrjxfkcrj.png"
    )
    
    p7 = Product(
        name="White Choco Bliss Bites – Premium White Chocolate Dry Fruit Bite",
        sku="CB-WHT-01",
        category="choco",
        short_description="Naturally sweetened dry fruit bite coated with premium white chocolate.",
        description="Pure white chocolate bliss. Elegant couverture white chocolate covering a delicious, natural dates and nuts base.",
        mrp=220.0,
        sale_price=200.0,
        available_qty=0, # Out of stock
        ingredients="Dates, Almonds, Cashews, White Couverture Chocolate",
        image_url="/static/images/Gemini_Generated_Image_5xxpwv5xxpwv5xxp.png"
    )
    
    # Gifting Boxes
    p8 = Product(
        name="Large Delight Box",
        sku="GB-DLG-LG",
        category="gifting",
        short_description="Perfect for corporate gifting or large family celebrations.",
        description="A beautiful premium gift box containing an assortment of our signature Bliss Bites and Daily Nutrition Bites. Custom branding and sleeves available.",
        mrp=1800.0,
        sale_price=1500.0,
        available_qty=25,
        ingredients="Assorted Bliss Bites & Daily Nutrition Bites",
        image_url="/static/images/Gemini_Generated_Image_6kgcok6kgcok6kgc.png"
    )

    db.session.add_all([p1, p2, p3, p4, p5, p6, p7, p8])
    db.session.flush()

    # Seed initial media files for gallery showcase
    m1 = ProductMedia(product_id=p5.id, media_type='image', media_url='/static/images/Gemini_Generated_Image_w08uwnw08uwnw08u.png', display_order=1)
    m2 = ProductMedia(product_id=p5.id, media_type='image', media_url='/static/images/Gemini_Generated_Image_6kgcok6kgcok6kgc.png', display_order=2)
    m3 = ProductMedia(product_id=p6.id, media_type='image', media_url='/static/images/Gemini_Generated_Image_kcrjxfkcrjxfkcrj.png', display_order=1)
    m4 = ProductMedia(product_id=p7.id, media_type='image', media_url='/static/images/Gemini_Generated_Image_5xxpwv5xxpwv5xxp.png', display_order=1)
    m5 = ProductMedia(product_id=p8.id, media_type='image', media_url='/static/images/Gemini_Generated_Image_6kgcok6kgcok6kgc.png', display_order=1)
    m6 = ProductMedia(product_id=p5.id, media_type='video', media_url='https://www.w3schools.com/html/mov_bbb.mp4', display_order=3)

    db.session.add_all([m1, m2, m3, m4, m5, m6])

    # Seed Coupons
    c1 = Coupon(code="SWEET10", discount_type="percent", discount_value=10.0, is_active=True)
    c2 = Coupon(code="FESTIVE200", discount_type="flat", discount_value=200.0, is_active=True)
    db.session.add_all([c1, c2])

    db.session.commit()
    print("Database initialization complete.")
