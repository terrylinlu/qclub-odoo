import json
from datetime import date, timedelta

from freezegun import freeze_time
from lxml import html

from odoo.tests import HttpCase, tagged
from odoo.tests.common import new_test_user


@tagged("post_install", "-at_install")
class TestOccupancyHttp(HttpCase):
    def setUp(self):
        super().setUp()
        self.qclub = self.env["website"].search([("name", "=", "Q Club")], limit=1)
        self.aushare = self.env["website"].search([("name", "=", "AUSHARE")], limit=1)
        self.assertTrue(self.qclub and self.aushare)
        self.config = self.env["qclub.config"]._get_for_website(self.qclub)
        self.config.write({"online_booking": True, "occupancy_requires_login": False, "max_advance_days": 14})
        self.portal = new_test_user(
            self.env, login="occupancy-http-portal", password="occupancy-test", groups="base.group_portal",
        )
        self._website(self.qclub)

    def _website(self, website):
        test_domain = self.base_url()
        others = self.env["website"].search([
            ("id", "!=", website.id), ("domain", "=", test_domain),
        ])
        others.write({"domain": False})
        self.env.flush_all()
        website.domain = test_domain
        self.env.flush_all()
        self.env.registry.clear_cache()
        self.opener.cookies.clear()

    def _occupancy(self, value="2026-06-01", **extra):
        return self.url_open(
            "/billiard/booking/occupancy",
            data=json.dumps({"jsonrpc": "2.0", "method": "call", "id": 1, "params": {"date": value, **extra}}),
            headers={"Content-Type": "application/json"},
        )

    @freeze_time("2026-06-01 00:00:00")
    def test_web_001_routes_only_on_enabled_current_website(self):
        page = self.url_open("/billiard/booking")
        self.assertEqual(page.status_code, 200)
        document = html.fromstring(page.content)
        self.assertEqual(document.get("data-website-id"), str(self.qclub.id))
        self.assertTrue(document.xpath("//div[contains(@class, 'o_qclub_booking_grid')]"))
        self.assertEqual(self._occupancy().status_code, 200)
        self.assertIn("result", self._occupancy().json())
        for website, enabled in ((self.aushare, True), (self.qclub, False)):
            with self.subTest(website=website.name, enabled=enabled):
                self.config.online_booking = enabled
                self._website(website)
                self.assertEqual(self.url_open("/billiard/booking").status_code, 404)
                response = self._occupancy()
                self.assertEqual(response.status_code, 404)

    @freeze_time("2026-06-01 00:00:00")
    def test_web_002_public_http_and_strict_date_validation(self):
        hours = self.env["qclub.opening.hours"]
        hours.search([("website_id", "=", self.qclub.id)]).unlink()
        hours.create({"website_id": self.qclub.id, "weekday": "0", "open_hour": 14, "close_hour": 24})
        kind = self.env["qclub.table.type"].create({"name": "HTTP occupancy type", "website_id": self.qclub.id})
        table = self.env["qclub.table"].create({
            "name": "HTTP occupancy table", "website_id": self.qclub.id, "type_id": kind.id, "hourly_price": 20,
        })
        customer = self.env["res.partner"].create({
            "name": "Secret HTTP Customer", "email": "secret-http@example.invalid", "phone": "+61000000888",
        })
        booking = self.env["qclub.booking"].create({
            "table_id": table.id, "partner_id": customer.id, "start": "2026-06-01 04:30:00", "duration_hours": 1,
        })
        self.env.flush_all()
        response = self._occupancy()
        self.assertEqual(response.status_code, 200)
        result = response.json()["result"]
        self.assertEqual(result["business_date"], "2026-06-01")
        self.assertEqual(set(result), {"business_date", "available_dates", "currency", "slots", "tables"})
        self.assertEqual(set(result["available_dates"]), {"min", "max"})
        for slot in result["slots"]:
            self.assertEqual(set(slot), {"start", "label", "next_day"})
        for row in result["tables"]:
            self.assertEqual(set(row), {"id", "name", "type", "hourly_price", "slots"})
        own_row = next(row for row in result["tables"] if row["id"] == table.id)
        self.assertEqual(own_row["slots"][0], "occupied")
        for secret in (customer.name, customer.email, customer.phone, booking.name):
            self.assertNotIn(secret, response.text)
        for value in (None, False, 20260601, [], {}, "20260601", "2026-6-01", "2026-02-30",
                      "2026-06-01T00:00:00", "2026-05-31", "2026-06-16"):
            with self.subTest(value=value):
                self.assertEqual(self._occupancy(value).json()["result"], {"error": "invalid_date"})
        self.assertEqual(self._occupancy("2026-06-15").json()["result"]["business_date"], "2026-06-15")

    @freeze_time("2026-06-01 21:00:00")
    def test_web_007_date_range_uses_adelaide_today(self):
        # UTC Monday, already Tuesday 6:30 AM in Adelaide (past the 6:00 business-day cutoff).
        self.assertEqual(self._occupancy("2026-06-01").json()["result"], {"error": "invalid_date"})
        result = self._occupancy("2026-06-02").json()["result"]
        self.assertEqual(result["available_dates"], {"min": "2026-06-02", "max": "2026-06-16"})
        document = html.fromstring(self.url_open("/billiard/booking").content)
        picker = document.xpath("//input[@type='date']")[0]
        self.assertEqual((picker.get("min"), picker.get("max")), ("2026-06-02", "2026-06-16"))

    @freeze_time("2026-06-01 00:00:00")
    def test_cfg_005_anonymous_blocked_portal_allowed_and_no_writes(self):
        self.assertIn("slots", self._occupancy().json()["result"])
        self.config.occupancy_requires_login = True
        self.env.flush_all()
        self.assertEqual(self._occupancy().json()["result"], {"error": "login_required"})
        page = html.fromstring(self.url_open("/billiard/booking").content)
        self.assertTrue(page.xpath("//a[@href='/web/login?redirect=/billiard/booking']"))
        self.authenticate(self.portal.login, "occupancy-test")
        self.assertIn("slots", self._occupancy().json()["result"])
        # Enabling a route never auto-creates configuration on another website.
        self._website(self.aushare)
        before = self.env["qclub.config"].search_count([("website_id", "=", self.aushare.id)])
        self._occupancy((date(2026, 6, 1) + timedelta(days=1)).isoformat())
        self.assertEqual(self.env["qclub.config"].search_count([("website_id", "=", self.aushare.id)]), before)
