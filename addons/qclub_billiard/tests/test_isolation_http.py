from lxml import html

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestIsolationHttp(HttpCase):
    def test_iso_001_aushare_homepage_and_shop(self):
        website = self.env["website"].search([("name", "=", "AUSHARE")], limit=1)
        self.assertTrue(website, "AUSHARE must be seeded in the test database")
        # Match the actual test HTTP server Host, rather than falling back to
        # whichever website happens to be first in the database.
        website.domain = self.base_url()
        self.env.flush_all()
        for path in ("/", "/shop"):
            with self.subTest(path=path):
                response = self.url_open(path)
                self.assertEqual(response.status_code, 200)
                document = html.fromstring(response.content)
                self.assertEqual(document.get("data-website-id"), str(website.id))
                # Avoid generic words: AUSHARE legitimately sells billiard products.
                for forbidden in ("/billiard/booking", "o_qclub", "qclub_billiard"):
                    self.assertNotIn(forbidden, response.text)
