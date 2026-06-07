import unittest
from app import create_app
from extensions import db
from utils.blog_data import BLOGS

class TestBlogFeatures(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_all_blog_routes_render_correctly(self):
        for slug, expected_blog in BLOGS.items():
            response = self.client.get(f'/blog/{slug}')
            self.assertEqual(response.status_code, 200)
            
            # Verify basic contents are rendered in the HTML (using substrings that avoid HTML escaping issues)
            html_content = response.data.decode('utf-8')
            
            # Match start of title/author to avoid apostrophes or ampersands autoescaping
            title_prefix = expected_blog['title'].split(':')[0].split('?')[0]
            author_prefix = expected_blog['author'].split('(')[0].strip()
            quote_snippet = expected_blog['quote'][:30]
            
            self.assertIn(title_prefix, html_content)
            self.assertIn(author_prefix, html_content)
            self.assertIn(quote_snippet, html_content)
            
            # Verify the specific interactive component is present
            if expected_blog['interactive_component'] == 'office-calculator':
                self.assertIn('sleep-slider', html_content)
                self.assertIn('coffee-slider', html_content)
                self.assertIn('calculateProductivity', html_content)
            elif expected_blog['interactive_component'] == 'lunchbox-checklist':
                self.assertIn('lunchbox-item', html_content)
                self.assertIn('checkLunchbox', html_content)
            elif expected_blog['interactive_component'] == 'glycemic-slider':
                self.assertIn('glycemic-line-traditional', html_content)
                self.assertIn('glycemic-line-sweet', html_content)
                self.assertIn('animateChart', html_content)
            elif expected_blog['interactive_component'] == 'energy-selector':
                self.assertIn('showFuel', html_content)
                self.assertIn('fuel-progress', html_content)
            elif expected_blog['interactive_component'] == 'gifting-estimator':
                self.assertIn('box-color-select', html_content)
                self.assertIn('gift-box-preview', html_content)
                self.assertIn('customizeBox', html_content)
            elif expected_blog['interactive_component'] == 'cravings-roulette':
                self.assertIn('spinRoulette', html_content)
                self.assertIn('roulette-wheel', html_content)

    def test_invalid_blog_slug_redirects(self):
        response = self.client.get('/blog/non-existent-blog-slug')
        self.assertEqual(response.status_code, 302)
        # Should redirect back to home page
        self.assertIn('/', response.location)

if __name__ == '__main__':
    unittest.main()
