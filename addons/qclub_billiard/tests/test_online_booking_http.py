import json
from urllib.parse import parse_qs, urlparse

from freezegun import freeze_time
from lxml import html
from odoo.tests import HttpCase, tagged
from odoo.tests.common import new_test_user


@tagged("post_install", "-at_install")
@freeze_time("2026-11-01 00:00:00")
class TestOnlineBookingHttp(HttpCase):
    def setUp(self):
        super().setUp()
        self.qclub = self.env["website"].search([("name", "=", "Q Club")], limit=1)
        self.aushare = self.env["website"].search([("name", "=", "AUSHARE")], limit=1)
        self.config = self.env["qclub.config"]._get_for_website(self.qclub)
        self.config.write({"online_booking": True, "booking_email_from": "Q Club <book@cueclub.example>"})
        self.env["qclub.opening.hours"]._load_default_hours(self.qclub)
        kind = self.env["qclub.table.type"].create({"name": "HTTP kind", "website_id": self.qclub.id})
        self.table = self.env["qclub.table"].create({
            "name": "HTTP online table", "website_id": self.qclub.id, "type_id": kind.id, "hourly_price": 20,
        })
        self.portal = new_test_user(self.env, login="online-http-guest", password="online-test",
                                    groups="base.group_portal")
        self.other = new_test_user(self.env, login="online-http-other", password="online-test",
                                   groups="base.group_portal")
        self._website(self.qclub)
        self.params = {"date": "2026-11-06", "table": self.table.id,
                       "start": "2026-11-06T12:30:00Z", "hours": 2}

    def _website(self, website):
        self.env["website"].search([("domain", "=", self.base_url())]).write({"domain": False})
        website.domain = self.base_url()
        self.env.flush_all()
        self.env.registry.clear_cache()
        self.opener.cookies.clear()

    def _rpc(self, route, **extra):
        return self.url_open("/billiard/booking/" + route, data=json.dumps({
            "jsonrpc": "2.0", "method": "call", "id": 1, "params": dict(self.params, **extra),
        }), headers={"Content-Type": "application/json"})

    def _login(self, user=None):
        self.authenticate((user or self.portal).login, "online-test")
        page = html.fromstring(self.url_open("/billiard/booking").content)
        self.token = page.xpath("//div[@data-csrf-token]/@data-csrf-token")[0]

    def test_web_006_login_redirect_preserves_selection(self):
        result = self._rpc("submit").json()["result"]
        self.assertEqual(result["error"], "login_required")
        target = parse_qs(urlparse(result["login_url"]).query)["redirect"][0]
        self.assertEqual(parse_qs(urlparse(target).query), {key: [str(value)] for key, value in self.params.items()})
        document = html.fromstring(self.url_open(target).content)
        self.assertEqual(document.xpath("//input[@type='date']/@value"), ["2026-11-06"])

    def test_web_004_web_008_tampering_csrf_and_server_amounts(self):
        self._login()
        self.assertEqual(self._rpc("submit").json()["result"]["error"], "csrf")
        quote = self._rpc("quote").json()["result"]
        result = self._rpc("submit", csrf_token=self.token, table_fee=0, deposit_amount=0,
                           state="confirmed", partner_id=self.other.partner_id.id).json()["result"]
        self.assertIn("confirmation_url", result)
        booking = self.env["qclub.booking"].search([("name", "=", result["confirmation_url"].split("/")[-1])])
        self.assertEqual(booking.partner_id, self.portal.partner_id)
        self.assertEqual(booking.state, "pending")
        self.assertEqual((booking.table_fee, booking.deposit_amount), (quote["table_fee"], quote["deposit_amount"]))
        page = self.url_open(result["confirmation_url"])
        self.assertEqual(page.status_code, 200)
        self.assertIn(result["time_label"], page.text)
        self.assertIn("Online deposit payment is coming soon. Our staff will contact you to confirm.", page.text)
        self.assertIn("data-remaining=", page.text)

    def test_web_005_conflict_exact_message_and_no_record(self):
        self._login()
        self.assertIn("confirmation_url", self._rpc("submit", csrf_token=self.token).json()["result"])
        before = self.env["qclub.booking"].search_count([])
        self._login(self.other)
        result = self._rpc("submit", csrf_token=self.token).json()["result"]
        self.assertEqual(result, {"error": "conflict", "message":
            "This time slot has just been taken. Please choose another.\n"
            "Slots awaiting a deposit are released automatically if not paid within "
            f"{self.config.lock_minutes} minutes."})
        self.assertEqual(self.env["qclub.booking"].search_count([]), before)

    def test_iso_002_confirmation_ownership_and_website_routes(self):
        self._login()
        result = self._rpc("submit", csrf_token=self.token).json()["result"]
        path = result["confirmation_url"]
        self._login(self.other)
        self.assertEqual(self.url_open(path).status_code, 404)
        self.opener.cookies.clear()
        self.assertEqual(self.url_open(path).status_code, 404)
        self.config.occupancy_requires_login = True
        self.env.flush_all()
        self.assertEqual(self._rpc("quote").json()["result"], {"error": "login_required"})
        self._website(self.aushare)
        for route in ("quote", "submit"):
            self.assertEqual(self._rpc(route).status_code, 404)
        self.assertEqual(self.url_open(path).status_code, 404)

    def test_web_004_foreign_table_rejected(self):
        kind = self.env["qclub.table.type"].create({"name": "Other kind", "website_id": self.aushare.id})
        table = self.env["qclub.table"].create({"name": "Other table", "website_id": self.aushare.id,
                                               "type_id": kind.id, "hourly_price": 1})
        self._login()
        before = self.env["qclub.booking"].search_count([])
        for route in ("quote", "submit"):
            result = self._rpc(route, table=table.id, csrf_token=self.token).json()["result"]
            self.assertEqual(result["error"], "validation")
        self.assertEqual(self.env["qclub.booking"].search_count([]), before)

    def test_web_009_web_010_warning_matches_quote_confirmation_and_email(self):
        self.portal.partner_id.email = "online-guest@example.invalid"
        with freeze_time("2026-11-06 00:00:00"):
            self._login()
            quote = self._rpc("quote").json()["result"]
            self.assertTrue(quote["created_in_cancel_window"])
            result = self._rpc("submit", csrf_token=self.token).json()["result"]
            page = self.url_open(result["confirmation_url"])
            warning = "This booking cannot be cancelled free of charge."
            self.assertIn(warning, page.text)
            self.assertIn("Fri 6 Nov, 11:00 PM – Sat 7 Nov, 1:00 AM", page.text)
            name = result["confirmation_url"].split("/")[-1]
            booking = self.env["qclub.booking"].search([("name", "=", name)])
            self.assertTrue(booking.created_in_cancel_window)
            mail = self.env["mail.mail"].search([("subject", "ilike", name)], limit=1)
            self.assertTrue(mail)
            self.assertIn(warning, mail.body_html)
            self.assertIn(quote["time_label"], mail.body_html)

    def test_web_004_web_009_submit_rechecks_quote_when_slot_becomes_past(self):
        self._login()
        self.assertNotIn("error", self._rpc("quote").json()["result"])
        before = self.env["qclub.booking"].search_count([])
        with freeze_time("2026-11-06 12:30:00"):
            # Refresh token as a real reload would do after several days.
            self._login()
            result = self._rpc("submit", csrf_token=self.token).json()["result"]
            self.assertEqual(result["error"], "validation")
        self.assertEqual(self.env["qclub.booking"].search_count([]), before)

    def test_web_004_submit_rejects_invalid_times_and_duration(self):
        self._login()
        before = self.env["qclub.booking"].search_count([])
        for values in (
            {"start": "2026-11-06T12:31:00Z"}, {"hours": 5}, {"hours": 0}, {"hours": True},
            {"hours": 1.5}, {"start": "2026-10-31T12:30:00Z"},
            {"start": "2026-11-06T01:30:00Z"}, {"start": "2026-12-06T12:30:00Z"},
        ):
            with self.subTest(values=values):
                result = self._rpc("submit", csrf_token=self.token, **values).json()["result"]
                self.assertEqual(result["error"], "validation")
        self.assertEqual(self.env["qclub.booking"].search_count([]), before)

    def test_web_005_own_hold_quote_and_submit_no_record(self):
        self._login()
        created = self._rpc("submit", csrf_token=self.token).json()["result"]
        name = created["confirmation_url"].split("/")[-1]
        before = self.env["qclub.booking"].search_count([])
        for route in ("quote", "submit"):
            with self.subTest(route=route):
                self.assertEqual(self._rpc(route, csrf_token=self.token).json()["result"], {
                    "error": "own_hold",
                    "message": f"You already hold this time slot ({name}, awaiting deposit).",
                    "confirmation_url": created["confirmation_url"],
                })
                self.assertEqual(self.env["qclub.booking"].search_count([]), before)

    def test_web_005_other_hold_generic_quote_and_submit_configured_minutes(self):
        self.config.lock_minutes = 17
        self.env.flush_all()
        self._login()
        created = self._rpc("submit", csrf_token=self.token).json()["result"]
        name = created["confirmation_url"].split("/")[-1]
        self._login(self.other)
        before = self.env["qclub.booking"].search_count([])
        for route in ("quote", "submit"):
            with self.subTest(route=route):
                result = self._rpc(route, csrf_token=self.token).json()["result"]
                self.assertEqual(result, {"error": "conflict", "message":
                    "This time slot has just been taken. Please choose another.\n"
                    "Slots awaiting a deposit are released automatically if not paid within 17 minutes."})
                self.assertNotIn(name, json.dumps(result))
                self.assertNotIn(self.portal.partner_id.name, json.dumps(result))
                self.assertEqual(self.env["qclub.booking"].search_count([]), before)

    def test_web_005_confirmed_own_booking_is_generic_conflict(self):
        self._login()
        created = self._rpc("submit", csrf_token=self.token).json()["result"]
        booking = self.env["qclub.booking"].search([
            ("name", "=", created["confirmation_url"].split("/")[-1]),
        ])
        booking.action_confirm()
        self.env.flush_all()
        for route in ("quote", "submit"):
            result = self._rpc(route, csrf_token=self.token).json()["result"]
            self.assertEqual(result["error"], "conflict")
            self.assertNotIn(booking.name, json.dumps(result))

    def test_web_005_expired_own_hold_does_not_block_quote_or_submit(self):
        self.config.lock_minutes = 1
        self.env.flush_all()
        self._login()
        created = self._rpc("submit", csrf_token=self.token).json()["result"]
        with freeze_time("2026-11-01 00:02:00"):
            self.assertNotIn("error", self._rpc("quote").json()["result"])
            result = self._rpc("submit", csrf_token=self.token).json()["result"]
            self.assertNotIn("error", result)
            self.assertNotEqual(result["confirmation_url"], created["confirmation_url"])
