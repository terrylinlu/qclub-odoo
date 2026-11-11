"""Two-company access and cross-website customer regressions (CO-001–005)."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from freezegun import freeze_time
from lxml import etree, html

from odoo.exceptions import AccessError
from odoo.fields import Domain
from odoo.tests import HttpCase, tagged
from odoo.tests.common import new_test_user

from .common import BilliardCase
from ..controllers import company_portal


@tagged("post_install", "-at_install")
@freeze_time("2026-11-01 00:00:00")
class TestMultiCompany(BilliardCase):
    def test_co_006_new_company_providers_do_not_touch_aushare(self):
        """tools/iso_fingerprint.sql and make iso-check cover the rest of CO-006."""
        Provider = self.env["payment.provider"].sudo().with_context(active_test=False)
        domain = [("company_id", "=", self.aushare.company_id.id)]
        before = Provider.search(domain)
        before_count = len(before)
        before_values = {provider.id: (provider.code, provider.state, provider.website_id.id)
                         for provider in before}
        all_before = Provider.search([])
        source = Provider.search([
            ("company_id", "=", self.env.user.company_id.id), ("module_state", "=", "installed"),
        ])
        self.assertTrue(source, "The test requires installed providers to exercise company copying.")

        company = self.env["res.company"].sudo().create({
            "name": "CO-006 provider isolation", "currency_id": self.env.ref("base.AUD").id,
            "country_id": self.env.ref("base.au").id,
        })

        after = Provider.search(domain)
        after.invalidate_recordset(["code", "state", "website_id"])
        self.assertEqual(len(after), before_count)
        self.assertEqual({provider.id: (provider.code, provider.state, provider.website_id.id)
                          for provider in after}, before_values)
        copied = Provider.search([]) - all_before
        self.assertEqual(len(copied), len(source))
        self.assertTrue(copied)
        self.assertEqual(Provider.search([("company_id", "=", company.id)]), copied)
        for provider in copied:
            self.assertEqual(provider.company_id, company)
            self.assertEqual(provider.state, "disabled")
            self.assertNotEqual(provider.website_id, self.aushare)

    def test_co_004_all_commerce_domains_only_on_enabled_website(self):
        sale = company_portal.BilliardSalePortal()
        account = company_portal.BilliardInvoicePortal()
        partner = self.env.user.partner_id
        config = self.env["qclub.config"]._get_for_website(self.qclub)
        calls = (
            lambda: sale._prepare_quotations_domain(partner),
            lambda: sale._prepare_orders_domain(partner),
            lambda: account._get_invoices_domain("out"),
            lambda: account._get_overdue_invoices_domain(partner.id),
        )
        for website in (self.qclub, self.aushare):
            website_config = self.env["qclub.config"]._get_for_website(website)
            website_config.online_booking = False
            with patch.object(company_portal, "request", SimpleNamespace(website=website, env=self.env)):
                original = [list(call()) for call in calls]
                if website == self.qclub:
                    config.online_booking = True
                    for call, baseline in zip(calls, original):
                        self.assertEqual(list(call()), list(
                            Domain(baseline) & Domain("company_id", "=", website.company_id.id)))
                    config.online_booking = False
                for call, baseline in zip(calls, original):
                    self.assertEqual(list(call()), baseline)

    def test_co_001_seeded_companies_and_no_company_data(self):
        self.assertEqual(self.env["res.company"].sudo().search_count([]), 2)
        self.assertNotEqual(self.qclub.company_id, self.aushare.company_id)
        self.assertIn("TAB Entertainment", self.qclub.company_id.name)
        for company in self.qclub.company_id | self.aushare.company_id:
            self.assertEqual(company.currency_id.name, "AUD")
        for path in Path(__file__).parents[1].rglob("*.xml"):
            self.assertFalse(etree.parse(str(path)).xpath("//record[@model='res.company']"))

    def test_co_002_company_access_and_related_values(self):
        kind = self._make_type("Company isolation")
        table = self.env["qclub.table"].create({
            "name": "Company isolation", "type_id": kind.id,
            "website_id": self.qclub.id, "hourly_price": 20,
        })
        self.env["qclub.opening.hours"]._load_default_hours(self.qclub)
        booking = self.env["qclub.booking"].create({
            "table_id": table.id, "partner_id": self.env.user.partner_id.id,
            "start": "2026-11-06 12:30:00", "duration_hours": 1,
        })
        booking.action_confirm()
        post = self.env["qclub.board.post"].create({"booking_id": booking.id, "message": "Company test"})
        config = self.env["qclub.config"]._get_for_website(self.qclub)
        for label, company in (("aushare", self.aushare.company_id), ("tab", self.qclub.company_id)):
            user = new_test_user(
                self.env, login="co-staff-" + label, groups="qclub_billiard.group_billiard_staff",
                company_id=company.id, company_ids=[(6, 0, company.ids)],
            )
            for record in (table, booking, post, config):
                scoped = record.with_user(user).with_context(allowed_company_ids=company.ids)
                self.assertEqual(record.company_id, self.qclub.company_id)
                if label == "aushare":
                    self.assertFalse(scoped.search([("id", "=", record.id)]))
                    with self.assertRaises(AccessError):
                        scoped.read(["website_id"])
                    with self.assertRaises(AccessError):
                        scoped.write({"website_id": self.qclub.id})
                else:
                    self.assertEqual(scoped.search([("id", "=", record.id)]).ids, record.ids)
                    self.assertEqual(scoped.read(["website_id"])[0]["website_id"][0], self.qclub.id)
                    if record == booking:
                        scoped.write({"duration_hours": 1})
        for model in ("table", "table.type", "opening.hours", "config", "booking", "board.post",
                      "board.terms", "board.reply", "board.application", "board.report", "board.ban"):
            field = self.env["qclub." + model]._fields["company_id"]
            self.assertTrue(field.store and field.index)
            self.assertEqual(field.related, "website_id.company_id")
            rule = self.env.ref("qclub_billiard.rule_qclub_" + model.replace(".", "_") + "_company")
            self.assertEqual(rule.groups, self.env.ref("base.group_user"))
            self.assertFalse(rule["global"])
        unused = self._make_type("Company recomputation")
        unused.website_id = self.aushare
        self.assertEqual(unused.company_id, self.aushare.company_id)
        self.qclub.company_id = self.aushare.company_id
        for record in (table, booking, post, config):
            self.assertEqual(record.company_id, self.aushare.company_id)


@tagged("post_install", "-at_install")
@freeze_time("2026-11-01 00:00:00")
class TestMultiCompanyHttp(HttpCase):
    def setUp(self):
        super().setUp()
        self.qclub = self.env["website"].search([("name", "=", "Q Club")], limit=1)
        self.aushare = self.env["website"].search([("name", "=", "AUSHARE")], limit=1)
        self.config = self.env["qclub.config"]._get_for_website(self.qclub)
        self.config.online_booking = True
        self.env["qclub.opening.hours"]._load_default_hours(self.qclub)
        kind = self.env["qclub.table.type"].create({"name": "CO HTTP", "website_id": self.qclub.id})
        self.table = self.env["qclub.table"].create({
            "name": "CO HTTP", "type_id": kind.id, "website_id": self.qclub.id, "hourly_price": 20,
        })
        self.customers = {}
        for label, company in (("aushare", self.aushare.company_id), ("tab", self.qclub.company_id)):
            self.customers[label] = new_test_user(
                self.env, login="co-http-" + label, password="co-test", groups="base.group_portal",
                company_id=company.id, company_ids=[(6, 0, company.ids)],
            )

    def _website(self, website):
        self.env["website"].search([("domain", "=", self.base_url())]).write({"domain": False})
        self.env.flush_all()
        website.domain = self.base_url()
        self.env.flush_all()
        self.env.registry.clear_cache()
        self.opener.cookies.clear()

    def _rpc(self, path, params):
        response = self.url_open(path, data=json.dumps({
            "jsonrpc": "2.0", "method": "call", "id": 1, "params": params,
        }), headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn("error", payload)
        return payload["result"]

    def test_co_003_aushare_customer_books_qclub(self):
        self._website(self.qclub)
        self.authenticate(self.customers["aushare"].login, "co-test")
        response = self.url_open("/billiard/booking")
        self.assertEqual(response.status_code, 200)
        token = html.fromstring(response.content).xpath("//div[@data-csrf-token]/@data-csrf-token")[0]
        self._rpc("/billiard/booking/occupancy", {"date": "2026-11-06"})
        result = self._rpc("/billiard/booking/submit", {
            "date": "2026-11-06", "table": self.table.id, "start": "2026-11-06T12:30:00Z",
            "hours": 1, "csrf_token": token,
        })
        self.assertIn("confirmation_url", result)
        booking = self.env["qclub.booking"].sudo().search([
            ("partner_id", "=", self.customers["aushare"].partner_id.id),
        ])
        self.assertEqual(booking.company_id, self.qclub.company_id)

    def test_co_003_tab_customer_shops_aushare(self):
        product = self.env["product.product"].create({
            "name": "CO shared product", "company_id": False, "list_price": 12,
            "is_published": True, "website_id": self.aushare.id,
        })
        self._website(self.aushare)
        self.authenticate(self.customers["tab"].login, "co-test")
        self.assertIn("CO shared product", self.url_open("/shop").text)
        self._rpc("/shop/cart/add", {
            "product_template_id": product.product_tmpl_id.id, "product_id": product.id, "quantity": 1,
        })
        self.assertIn("CO shared product", self.url_open("/shop/cart").text)

    def test_co_004_orders_and_counters_by_website_company(self):
        customer = self.customers["aushare"]
        order = self.env["sale.order"].with_company(self.aushare.company_id).create({
            "partner_id": customer.partner_id.id, "company_id": self.aushare.company_id.id,
        })
        order.action_confirm()
        for website, expected in ((self.qclub, 0), (self.aushare, 1)):
            self._website(website)
            self.authenticate(customer.login, "co-test")
            page = self.url_open("/my/orders")
            self.assertEqual(page.status_code, 200)
            self.assertEqual(order.name in page.text, bool(expected))
            self.assertEqual(self.url_open("/my").status_code, 200)
            counters = self._rpc("/my/counters", {"counters": ["order_count"]})
            self.assertEqual(counters["order_count"], expected)
            if website == self.aushare:
                self.assertNotIn("/my/billiard", self.url_open("/my").text)
                self.assertEqual(self.url_open("/my/billiard").status_code, 404)

    def test_co_005_qclub_signup_company(self):
        self._website(self.qclub)
        self.qclub.auth_signup_uninvited = "b2c"
        page = html.fromstring(self.url_open("/web/signup").content)
        token = page.xpath("//input[@name='csrf_token']/@value")[0]
        self.url_open("/web/signup", data={
            "csrf_token": token, "login": "co-signup@example.invalid", "name": "CO signup",
            "password": "co-test", "confirm_password": "co-test",
        })
        user = self.env["res.users"].sudo().search([("login", "=", "co-signup@example.invalid")])
        self.assertTrue(user)
        self.assertEqual(user.company_id, self.qclub.company_id)
