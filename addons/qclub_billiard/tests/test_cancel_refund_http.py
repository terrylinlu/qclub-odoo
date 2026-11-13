from datetime import timedelta
from unittest.mock import patch

from freezegun import freeze_time
from lxml import html
from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import new_test_user
from odoo.addons.payment.tests.http_common import PaymentHttpCommon


@tagged('post_install', '-at_install')
@freeze_time('2026-11-01 00:00:00')
class TestCancelRefundHttp(PaymentHttpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.enable_post_process_patcher = False
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

    def _call(self, suffix, params=None):
        self.env.flush_all()
        return self.url_open(f'/billiard/booking/{self.booking.id}/cancel/{suffix}', json={
            'jsonrpc': '2.0', 'id': 1, 'method': 'call', 'params': params or {},
        })

    def _token(self):
        page = self.url_open(self.path)
        buttons = html.fromstring(page.content).xpath('//*[contains(@class, "o_qclub_cancel")]')
        self.assertEqual(len(buttons), 1)
        return buttons[0].get('data-csrf-token')

    def _pay(self):
        tx = self.env['payment.transaction'].create({
            'provider_id': self.provider.id, 'payment_method_id': self.payment_method.id,
            'amount': self.booking.deposit_amount, 'currency_id': self.booking.currency_id.id,
            'partner_id': self.owner.partner_id.id, 'operation': 'online_redirect',
            'qclub_booking_id': self.booking.id,
        })
        tx._set_done()
        tx._post_process()
        return tx

    def test_rf_003_owner_buttons_and_server_outcomes(self):
        self.authenticate(self.owner.login, 'offline')
        self._token()
        self.assertIn('Cancel booking', self.url_open('/my/billiard').text)
        self.assertEqual(self._call('outcome').json()['result']['text'], 'This booking has no deposit to refund.')
        self._pay()
        text = self._call('outcome').json()['result']['text']
        self.assertIn('You will receive a full refund of', text)
        self.assertIn('10.00', text)
        with freeze_time(self.booking.start - timedelta(hours=1)):
            text = self._call('outcome').json()['result']['text']
            self.assertIn('non-refundable', text)
            self.assertIn('10.00', text)

    def test_rf_003_owner_website_started_and_csrf_guards(self):
        for user in (self.other, None):
            self.authenticate(user.login if user else None, 'offline' if user else None)
            for suffix in ('outcome', 'confirm'):
                response = self._call(suffix)
                self.assertTrue(response.status_code != 200 or 'error' in response.json())
        self.authenticate(self.owner.login, 'offline')
        self.assertIn('error', self._call('confirm', {'csrf_token': 'invalid'}).json())
        token = self._token()
        with freeze_time(self.booking.start):
            self.assertNotIn('o_qclub_cancel', self.url_open(self.path).text)
            for suffix in ('outcome', 'confirm'):
                self.assertIn('error', self._call(suffix, {'csrf_token': token}).json())
        self._website(self.aushare)
        self.authenticate(self.owner.login, 'offline')
        for suffix in ('outcome', 'confirm'):
            self.assertEqual(self._call(suffix).status_code, 404)

    def test_rf_001_rf_003_confirm_double_submit_refunds_once(self):
        tx = self._pay()
        self.authenticate(self.owner.login, 'offline')
        token = self._token()
        def done(refund):
            refund._set_done()
        with patch.object(type(tx), '_send_refund_request', done):
            for _ in range(2):
                self.assertTrue(self._call('confirm', {'csrf_token': token}).json()['result']['cancelled'])
        self.booking.invalidate_recordset()
        tx.invalidate_recordset()
        self.assertEqual(self.booking.state, 'cancelled')
        self.assertEqual(len(tx.child_transaction_ids), 1)
        self.assertEqual(self.booking.deposit_state, 'refunded')
        self.assertNotIn('o_qclub_cancel', self.url_open(self.path).text)
