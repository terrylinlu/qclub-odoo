from decimal import Decimal

from freezegun import freeze_time
from lxml import html

from odoo.exceptions import AccessError
from odoo.tests import HttpCase, tagged
from odoo.tests.common import new_test_user

from .common import BilliardCase
from . import test_online_booking_http


@tagged("post_install", "-at_install")
class TestGridPricesConfig(BilliardCase):
    def test_cfg_006_default_true_for_new_config(self):
        website = self.env["website"].create({"name": "Grid prices default"})
        config = self.env["qclub.config"].create({"website_id": website.id})
        self.assertIs(config.show_grid_prices, True)

    def test_cfg_006_staff_read_only_manager_can_write(self):
        config = self.env["qclub.config"]._get_for_website(self.qclub)
        self.assertIs(config.with_user(self.staff).show_grid_prices, True)
        with self.assertRaises(AccessError):
            config.with_user(self.staff).write({"show_grid_prices": False})
        for value in (False, True):
            config.with_user(self.manager).write({"show_grid_prices": value})
            self.assertIs(config.with_user(self.staff).show_grid_prices, value)


@tagged("post_install", "-at_install")
@freeze_time("2026-11-01 00:00:00")
class TestGridPricesHttp(HttpCase):
    _website = test_online_booking_http.TestOnlineBookingHttp._website
    _rpc = test_online_booking_http.TestOnlineBookingHttp._rpc
    _login = test_online_booking_http.TestOnlineBookingHttp._login

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

    def test_cfg_006_page_flag_preserves_occupancy_fields(self):
        baseline = self._rpc("occupancy").json()["result"]
        expected_keys = {"business_date", "available_dates", "currency", "slots", "tables"}
        self.assertEqual(set(baseline), expected_keys)
        for value in (False, True):
            self.config.show_grid_prices = value
            self.env.flush_all()
            page = self.url_open("/billiard/booking")
            self.assertEqual(page.status_code, 200)
            document = html.fromstring(page.content)
            self.assertEqual(document.xpath(
                "//div[contains(concat(' ', normalize-space(@class), ' '), "
                "' o_qclub_booking_grid ')]/@data-show-grid-prices",
            ), ["1" if value else "0"])
            result = self._rpc("occupancy").json()["result"]
            self.assertEqual(set(result), expected_keys)
            self.assertEqual(result, baseline)

    def test_cfg_006_hidden_grid_prices_keep_quote_and_submit_amounts(self):
        self.config.write({"show_grid_prices": False, "deposit_ratio": 50})
        self.env.flush_all()
        self._login()
        quote = self._rpc("quote").json()["result"]
        submitted = self._rpc("submit", csrf_token=self.token).json()["result"]
        self.assertIn("confirmation_url", submitted)
        for result in (quote, submitted):
            self.assertNotIn("error", result)
            self.assertEqual(Decimal(str(result["table_fee"])), Decimal("40"))
            self.assertEqual(Decimal(str(result["deposit_amount"])), Decimal("20"))
        booking = self.env["qclub.booking"].search([
            ("name", "=", submitted["confirmation_url"].split("/")[-1]),
        ])
        self.assertTrue(booking)
        self.assertEqual(Decimal(str(booking.table_fee)), Decimal("40"))
        self.assertEqual(Decimal(str(booking.deposit_amount)), Decimal("20"))
