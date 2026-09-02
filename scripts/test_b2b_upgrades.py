from app import create_app
from extensions import db
from models.user import User
from models.b2b import B2BProduct, B2BProductImage, B2BProductShowcase, B2BTestimonial, B2BTestimonialImage, B2BClient, B2BOrder

def run_tests():
    app = create_app()
    client = app.test_client()
    
    with app.app_context():
        print("=== 1. Testing Public B2B Routes ===")
        # Test B2B Landing Page
        res = client.get('/b2b/')
        assert res.status_code == 200, f"Expected 200 on /b2b/, got {res.status_code}"
        assert b"What Sets Sweet Scribbles Apart" in res.data, "What Sets Apart section missing on B2B index"
        assert b"Trusted by Industry Leaders" in res.data, "Testimonials section missing on B2B index"
        print("✅ B2B Landing Page rendered with updated What Sets Apart & Testimonials!")

        # Test Public Testimonials Page
        res_testi = client.get('/b2b/testimonials')
        assert res_testi.status_code == 200, f"Expected 200 on /b2b/testimonials, got {res_testi.status_code}"
        assert b"Corporate Gifting Stories &amp; Client Trust" in res_testi.data or b"Corporate Gifting Stories" in res_testi.data
        print("✅ Public Testimonials page (/b2b/testimonials) rendered successfully!")

        # Test Product Sub-Page
        prod = B2BProduct.query.filter_by(is_active=True).first()
        assert prod is not None, "No active B2B product found"
        res_prod = client.get(f'/b2b/product/{prod.id}')
        assert res_prod.status_code == 200, f"Expected 200 on /b2b/product/{prod.id}, got {res_prod.status_code}"
        assert prod.name.encode() in res_prod.data
        assert b"Real Client Deliveries of this Box Style" in res_prod.data
        print(f"✅ Product Sub-Page for '{prod.name}' rendered with gallery, specs & client deliveries!")

        # Test Admin Authentication & Routes
        print("\n=== 2. Testing Admin Control Room Routes ===")
        admin_user = User.query.filter_by(is_admin=True).first()
        if not admin_user:
            admin_user = User(
                name="B2B Test Admin",
                phone="919999999999",
                email="admin@sweetscribbles.test",
                is_admin=True
            )
            db.session.add(admin_user)
            
        admin_user.set_password("admin")
        db.session.commit()

        # Login as admin via /auth/login
        login_res = client.post('/auth/login', data={
            'email': admin_user.email,
            'password': 'admin'
        }, follow_redirects=True)
        assert login_res.status_code == 200

        # Test Admin Dashboard (Kanban)
        res_adm_dash = client.get('/admin/b2b/')
        assert res_adm_dash.status_code == 200, f"Expected 200 on /admin/b2b/, got {res_adm_dash.status_code}"
        print("✅ Admin Dashboard (/admin/b2b/) rendered successfully!")

        # Test Admin Orders List
        res_adm_orders = client.get('/admin/b2b/orders')
        assert res_adm_orders.status_code == 200, f"Expected 200 on /admin/b2b/orders, got {res_adm_orders.status_code}"
        print("✅ Admin Orders List (/admin/b2b/orders) rendered successfully!")

        # Test Admin Clients CRM
        res_adm_clients = client.get('/admin/b2b/clients')
        assert res_adm_clients.status_code == 200, f"Expected 200 on /admin/b2b/clients, got {res_adm_clients.status_code}"
        print("✅ Admin Clients CRM (/admin/b2b/clients) rendered successfully!")

        # Test Admin Products & Boxes Catalog
        res_adm_prods = client.get('/admin/b2b/products')
        assert res_adm_prods.status_code == 200, f"Expected 200 on /admin/b2b/products, got {res_adm_prods.status_code}"
        print("✅ Admin Products Catalog (/admin/b2b/products) rendered successfully!")

        # Test Admin Product Manage Control Room
        res_adm_manage = client.get(f'/admin/b2b/products/{prod.id}/manage')
        assert res_adm_manage.status_code == 200, f"Expected 200 on /admin/b2b/products/{prod.id}/manage, got {res_adm_manage.status_code}"
        assert b"Multi-Image Product Gallery" in res_adm_manage.data
        assert b"Real Client Deliveries Slideshow" in res_adm_manage.data
        print(f"✅ Admin Product Control Room for '{prod.name}' rendered successfully!")

        # Test Admin Testimonials Desk
        res_adm_testi = client.get('/admin/b2b/testimonials')
        assert res_adm_testi.status_code == 200, f"Expected 200 on /admin/b2b/testimonials, got {res_adm_testi.status_code}"
        assert b"Corporate Client Stories &amp; Testimonials" in res_adm_testi.data
        print("✅ Admin Testimonials Desk rendered successfully!")

        print("\n=== 3. Testing CRUD Actions for Testimonials & Showcases ===")
        # Add Testimonial with Multiple Photos
        add_res = client.post('/admin/b2b/testimonials/add', data={
            'company_name': 'Test Corp Pvt Ltd',
            'contact_person': 'Test Manager',
            'designation': 'Head of HR',
            'order_details': '100 Boxes · Test Event',
            'testimonial_text': 'Amazing bespoke quality and timely delivery!',
            'box_photo_fallback': '/static/images/official_logo_gold.png\n/static/images/official_logo_white.png',
            'rating': 5,
            'is_featured': 'on'
        }, follow_redirects=True)
        assert add_res.status_code == 200
        created_t = B2BTestimonial.query.filter_by(company_name='Test Corp Pvt Ltd').first()
        assert created_t is not None
        assert len(created_t.images) >= 2, f"Expected at least 2 images, got {len(created_t.images)}"
        print(f"✅ Created B2B Testimonial ID {created_t.id} with {len(created_t.images)} multi-photo carousel images!")

        # Verify Testimonials page renders carousel for this testimonial
        res_testi_multi = client.get('/b2b/testimonials')
        assert f'testiCarousel{created_t.id}'.encode() in res_testi_multi.data
        print("✅ Verified Multi-Image Carousel HTML rendered on /b2b/testimonials!")

        # Edit Testimonial
        edit_res = client.post(f'/admin/b2b/testimonials/{created_t.id}/edit', data={
            'company_name': 'Test Corp Pvt Ltd (Updated)',
            'contact_person': 'Test Manager',
            'designation': 'VP of HR',
            'order_details': '150 Boxes · Annual Meet',
            'testimonial_text': 'Updated testimonial text for testing.',
            'rating': 5,
            'is_featured': 'on',
            'is_active': 'on'
        }, follow_redirects=True)
        assert edit_res.status_code == 200
        assert created_t.company_name == 'Test Corp Pvt Ltd (Updated)'
        print(f"✅ Updated B2B Testimonial ID {created_t.id}")

        # Delete Testimonial
        del_res = client.post(f'/admin/b2b/testimonials/{created_t.id}/delete', follow_redirects=True)
        assert del_res.status_code == 200
        assert db.session.get(B2BTestimonial, created_t.id) is None
        print("✅ Deleted B2B Testimonial successfully!")

        # Add Product Gallery Image
        add_img_res = client.post(f'/admin/b2b/products/{prod.id}/images/add', data={
            'image_url_fallback': '/static/images/official_logo_gold.png',
            'caption': 'Inside Box Assortment'
        }, follow_redirects=True)
        assert add_img_res.status_code == 200
        created_img = B2BProductImage.query.filter_by(product_id=prod.id, caption='Inside Box Assortment').first()
        assert created_img is not None
        print(f"✅ Added Gallery Image ID {created_img.id} to Product {prod.id}")

        # Delete Product Gallery Image
        del_img_res = client.post(f'/admin/b2b/products/images/{created_img.id}/delete', follow_redirects=True)
        assert del_img_res.status_code == 200
        assert db.session.get(B2BProductImage, created_img.id) is None
        print("✅ Removed Gallery Image successfully!")

        print("\n🎉 ALL B2B UPGRADE TESTS & CONTROL ROOM ROUTES PASSED CLEANLY!")

if __name__ == '__main__':
    run_tests()
