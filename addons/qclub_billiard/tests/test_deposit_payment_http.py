from datetime import timedelta
from unittest.mock import patch

from freezegun import freeze_time
from odoo import Command, fields, http
from odoo.tests import tagged
from odoo.tests.common import new_test_user
from odoo.addons.payment.tests.http_common import PaymentHttpCommon
from odoo.addons.website_sale.controllers.sale import CustomerPortal as WebsiteSalePortal

from ..controllers.main import BilliardBooking
from ..controllers.board import BilliardBoard
from ..controllers.my_account import BilliardAccount
from ..controllers.payment import BilliardPayment
from ..controllers.company_portal import BilliardSalePortal, BilliardInvoicePortal


@tagged('post_install', '-at_install')
@freeze_time('2026-11-01 00:00:00')
class TestDepositHttp(PaymentHttpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.qclub = cls.env['website'].search([('name', '=', 'Q Club')], limit=1)
        cls.aushare = cls.env['website'].search([('name', '=', 'AUSHARE')], limit=1)
        cls.owner = new_test_user(cls.env, login='deposit-owner', password='offline', groups='base.group_portal')
        cls.other = new_test_user(cls.env, login='deposit-other', password='offline', groups='base.group_portal')
        cls.config = cls.env['qclub.config']._get_for_website(cls.qclub)
        cls.config.write({'online_booking': True, 'lock_minutes': 10, 'max_advance_days': 14})
        cls.env['qclub.opening.hours']._load_default_hours(cls.qclub)
        kind = cls.env['qclub.table.type'].create({'name': 'Pay HTTP', 'website_id': cls.qclub.id})
        cls.table = cls.env['qclub.table'].create({'name': 'Pay HTTP', 'type_id': kind.id,
                                                 'website_id': cls.qclub.id, 'hourly_price': 20})
        cls.provider = cls.dummy_provider.copy({
            'company_id': cls.qclub.company_id.id, 'website_id': cls.qclub.id,
            'code': 'none', 'state': 'test', 'is_published': True,
            'payment_method_ids': [Command.set(cls.pm_unknown.ids)],
            'available_currency_ids': [Command.set(cls.qclub.company_id.currency_id.ids)],
        })
        cls.payment_methods = cls.provider.payment_method_ids
        cls.payment_method = cls.payment_methods[:1]
        cls.payment_method_id = cls.payment_method.id
        cls.payment_method_code = cls.payment_method.code
        cls.payment_method.write({'active': True})

    def setUp(self):
        super().setUp()
        self.startPatcher(patch.object(type(self.provider), '_send_api_request',
                                     side_effect=AssertionError('Network forbidden in deposit HTTP tests')))
        self._website(self.qclub)
        self.booking = self.env['qclub.booking'].create({
            'table_id': self.table.id, 'partner_id': self.owner.partner_id.id,
            'start': '2026-11-06 03:30:00', 'duration_hours': 1, 'booking_channel': 'online',
        })
        self.path = '/billiard/booking/confirmation/' + self.booking.name
        self.route = f'/billiard/booking/{self.booking.id}/transaction'
        self.params = {'provider_id': self.provider.id, 'payment_method_id': self.payment_method.id,
                       'token_id': None, 'flow': 'redirect', 'tokenization_requested': False,
                       'landing_route': '/untrusted', 'amount': 1}

    def _website(self, website):
        self.env['website'].search([('domain', '=', self.base_url())]).write({'domain': False})
        self.env.flush_all()
        website.domain = self.base_url()
        self.env.flush_all()
        self.env.registry.clear_cache()
        self.opener.cookies.clear()

    def _refused(self):
        # Inspect the actual JSON-RPC error envelope, including 404 website gates.
        response = self.url_open(self.route, json={'jsonrpc': '2.0', 'id': 1,
                                                  'method': 'call', 'params': self.params})
        self.assertTrue(response.status_code != 200 or 'error' in response.json())

    def test_pay_003_booking_routes_include_payment_override(self):
        # Exercise Odoo's real controller-leaf selection and routing metadata merging.
        # Inspect all endpoints, including duplicates from other portal roots.
        expected = {
            '/billiard/booking': BilliardBooking.booking_page,
            '/billiard/booking/occupancy': BilliardBooking.occupancy,
            '/billiard/booking/quote': BilliardBooking.quote,
            '/billiard/booking/submit': BilliardBooking.submit,
            '/billiard/booking/confirmation/<string:name>': BilliardPayment.confirmation,
            '/billiard/booking/board': BilliardBoard.board,
            '/billiard/booking/post': BilliardBoard.post,
            '/billiard/booking/post/create': BilliardBoard.create_post,
            '/billiard/booking/post/reply': BilliardBoard.reply,
            '/billiard/booking/post/apply': BilliardBoard.apply,
            '/billiard/booking/post/withdraw': BilliardBoard.withdraw,
            '/billiard/booking/application/decide': BilliardBoard.decide,
            '/billiard/booking/post/report': BilliardBoard.report,
            '/billiard/booking/reminders': BilliardAccount.reminders,
            '/my/billiard': BilliardAccount.my_billiard,
            '/billiard/booking/<int:booking_id>/transaction': BilliardPayment.booking_transaction,
        }
        found = set()
        commerce_found = set()
        commerce = {'/my/orders': BilliardSalePortal, '/my/invoices': BilliardInvoicePortal}
        modules = sorted(self.env.registry._init_modules)
        for url, endpoint in http._generate_routing_rules(
                modules, False, self.env['ir.http']._get_converters()):
            # The payment leaf also participates in Odoo's portal hierarchy.
            # Keep the existing sale/invoice company overrides and sale's own
            # payment-values method; booking payment values use a distinct name.
            if url in commerce:
                self.assertIsInstance(endpoint.func.__self__, commerce[url])
                if url == '/my/orders':
                    self.assertIs(endpoint.func.__self__._get_payment_values.__func__,
                                  WebsiteSalePortal._get_payment_values)
                    self.assertIs(endpoint.func.__self__._prepare_orders_domain.__func__,
                                  BilliardSalePortal._prepare_orders_domain)
                else:
                    self.assertIs(endpoint.func.__self__._get_invoices_domain.__func__,
                                  BilliardInvoicePortal._get_invoices_domain)
                commerce_found.add(url)
            if url not in expected:
                continue
            with self.subTest(route=url):
                self.assertIsInstance(endpoint.func.__self__, BilliardPayment)
                self.assertIs(endpoint.func.__func__, expected[url])
                if url == '/billiard/booking/<int:booking_id>/transaction':
                    self.assertEqual(endpoint.routing['auth'], 'user')
                    self.assertEqual(endpoint.routing['type'], 'jsonrpc')
                    self.assertEqual(endpoint.routing['methods'], ['POST'])
                found.add(url)
        self.assertEqual(found, set(expected))
        self.assertEqual(commerce_found, {'/my/orders', '/my/invoices'})

    def test_pay_003_pay_011_pay_013_owner_form_and_server_values(self):
        self.authenticate(self.owner.login, 'offline')
        page = self.url_open(self.path)
        self.assertEqual(page.status_code, 200)
        context = self._get_payment_context(page)
        self.assertEqual(context['transaction_route'], self.route)
        self.assertIn(self.qclub.company_id.name, page.text)
        self.assertNotIn('AUSHAREU', page.text)
        params = {**self.params, 'currency_id': self.currency_usd.id, 'partner_id': self.other.partner_id.id,
                  'is_validation': True}
        self.make_jsonrpc_request(self.route, params)
        tx = self.env['payment.transaction'].search([('qclub_booking_id', '=', self.booking.id)])
        self.assertEqual(len(tx), 1)
        self.assertEqual(tx.currency_id, self.booking.currency_id)
        self.assertEqual(tx.partner_id, self.owner.partner_id)
        self.assertEqual(tx.currency_id.compare_amounts(tx.amount, self.booking.deposit_amount), 0)
        self.assertEqual(tx.website_id, self.qclub)
        self.assertEqual(tx.landing_route, self.path)
        self.assertNotEqual(tx.operation, 'validation')

    def test_pay_011_other_customer_anonymous_other_website(self):
        for user in (self.other, None):
            self.opener.cookies.clear()
            if user:
                self.authenticate(user.login, 'offline')
            self.assertEqual(self.url_open(self.path).status_code, 404)
            self._refused()
        self._website(self.aushare)
        self.authenticate(self.owner.login, 'offline')
        self.assertEqual(self.url_open(self.path).status_code, 404)
        self._refused()

    def test_pay_007_confirmed_expired_and_paid_refuse(self):
        self.authenticate(self.owner.login, 'offline')
        self.booking.action_confirm()
        self.assertNotIn('id="o_payment_form"', self.url_open(self.path).text)
        self._refused()
        self.booking.action_cancel()
        self.booking = self.env['qclub.booking'].create({
            'table_id': self.table.id, 'partner_id': self.owner.partner_id.id,
            'start': '2026-11-06 03:30:00', 'duration_hours': 1, 'booking_channel': 'online',
        })
        self.path = '/billiard/booking/confirmation/' + self.booking.name
        self.route = f'/billiard/booking/{self.booking.id}/transaction'
        self.booking._action_expire()
        self.assertNotIn('id="o_payment_form"', self.url_open(self.path).text)
        self._refused()

    def test_pay_007_paid_booking_refuses_transaction(self):
        self.authenticate(self.owner.login, 'offline')
        tx = self.env['payment.transaction'].create({
            'provider_id': self.provider.id, 'payment_method_id': self.payment_method.id,
            'partner_id': self.owner.partner_id.id, 'amount': self.booking.deposit_amount,
            'currency_id': self.booking.currency_id.id, 'operation': 'online_redirect',
            'qclub_booking_id': self.booking.id,
        })
        tx._set_done()
        tx._post_process()
        self.assertEqual(self.booking.deposit_state, 'paid')
        self.assertNotIn('id="o_payment_form"', self.url_open(self.path).text)
        self._refused()
        self.assertEqual(self.env['payment.transaction'].search_count([
            ('qclub_booking_id', '=', self.booking.id)]), 1)

    def test_pay_011_expired_lock_no_form_or_transaction(self):
        self.authenticate(self.owner.login, 'offline')
        with freeze_time('2026-11-01 00:11:00'):
            self.assertNotIn('id="o_payment_form"', self.url_open(self.path).text)
            self._refused()

    def test_pay_003_lock_extension_through_route_once(self):
        self.authenticate(self.owner.login, 'offline')
        page = self.url_open(self.path)
        context = self._get_payment_context(page)
        self.assertIn(self.payment_method.id, context['payment_method_ids'])
        with freeze_time('2026-11-01 00:06:00'):
            values = self.make_jsonrpc_request(self.route, self.params)
            tx = self.env['payment.transaction'].search([('reference', '=', values['reference'])])
            self.assertEqual(tx.provider_id, self.provider)
            self.assertEqual(tx.payment_method_id, self.payment_method)
            self.assertEqual(tx.operation, 'online_redirect')
            self.booking.invalidate_recordset()
            self.assertTrue(self.booking.lock_extended)
            self.assertEqual(self.booking.lock_expire, fields.Datetime.now() + timedelta(minutes=5))
        expiry = self.booking.lock_expire
        with freeze_time('2026-11-01 00:09:00'):
            self.make_jsonrpc_request(self.route, self.params)
            self.booking.invalidate_recordset()
            self.assertEqual(self.booking.lock_expire, expiry)

    def test_pay_011_provider_and_kwargs_injection_refused(self):
        self.authenticate(self.owner.login, 'offline')
        for extra in ({'custom_create_values': {'amount': 0}}, {'provider_id': self.dummy_provider.id},
                      {'flow': 'token', 'token_id': 999999}):
            with self.subTest(extra=extra):
                original = self.params
                self.params = {**original, **extra}
                self._refused()
                self.params = original
        self.assertFalse(self.env['payment.transaction'].search_count([('qclub_booking_id', '=', self.booking.id)]))
