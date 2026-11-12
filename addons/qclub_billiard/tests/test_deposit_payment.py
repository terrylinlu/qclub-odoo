"""Offline deposit contract tests; no installed provider or network is required."""
from datetime import timedelta
from unittest.mock import patch

from freezegun import freeze_time
from lxml import etree

from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import new_test_user
from odoo.addons.payment.tests.common import PaymentCommon


@tagged('post_install', '-at_install')
@freeze_time('2026-11-01 00:00:00')
class TestDepositPayment(PaymentCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Exercise the REAL account_payment post-processing chain (Option A).
        cls.enable_post_process_patcher = False
        cls.qclub = cls.env['website'].search([('name', '=', 'Q Club')], limit=1)
        cls.aushare = cls.env['website'].search([('name', '=', 'AUSHARE')], limit=1)
        cls.currency = cls.env.ref('base.AUD')
        cls.qclub.company_id.currency_id = cls.currency
        cls.provider = cls.dummy_provider.copy({
            'company_id': cls.qclub.company_id.id, 'website_id': cls.qclub.id,
            'code': 'none', 'state': 'test', 'is_published': True,
            'payment_method_ids': [Command.set(cls.pm_unknown.ids)],
            'available_currency_ids': [Command.set(cls.currency.ids)],
        })
        cls.payment_methods = cls.provider.payment_method_ids
        cls.payment_method = cls.payment_methods[:1]
        cls.payment_method_id = cls.payment_method.id
        cls.payment_method_code = cls.payment_method.code
        cls.payment_method.write({'active': True})
        cls.env['qclub.opening.hours']._load_default_hours(cls.qclub)
        cls.config = cls.env['qclub.config']._get_for_website(cls.qclub)
        cls.config.write({'online_booking': True, 'lock_minutes': 10, 'deposit_ratio': 50,
                          'max_advance_days': 14, 'booking_email_from': 'Q Club <booking@qclub.example>',
                          'contact_email': 'contact@qclub.example'})
        cls.qclub.domain = 'http://qclub.example'
        kind = cls.env['qclub.table.type'].create({'name': 'Payment type', 'website_id': cls.qclub.id})
        cls.table = cls.env['qclub.table'].create({
            'name': 'Payment table', 'website_id': cls.qclub.id, 'type_id': kind.id, 'hourly_price': 25,
        })
        cls.staff = new_test_user(cls.env, login='pay-staff', groups='qclub_billiard.group_billiard_staff',
                                 company_ids=[Command.set(cls.qclub.company_id.ids)], company_id=cls.qclub.company_id.id)
        cls.manager = new_test_user(cls.env, login='pay-manager', groups='qclub_billiard.group_billiard_manager',
                                   company_ids=[Command.set(cls.qclub.company_id.ids)], company_id=cls.qclub.company_id.id)

    def setUp(self):
        super().setUp()
        self.startPatcher(patch.object(type(self.provider), '_send_api_request',
                                     side_effect=AssertionError('Network forbidden in deposit tests')))

    def _book(self, **values):
        return self.env['qclub.booking'].create({
            'table_id': self.table.id, 'partner_id': self.partner.id,
            'start': '2026-11-06 03:30:00', 'duration_hours': 1, 'booking_channel': 'online', **values,
        })

    def _tx(self, booking, **values):
        return self.env['payment.transaction'].create({
            'provider_id': self.provider.id, 'payment_method_id': self.payment_method.id,
            'amount': booking.deposit_amount, 'currency_id': booking.currency_id.id,
            'partner_id': booking.partner_id.id, 'operation': 'online_redirect',
            'qclub_booking_id': booking.id, **values,
        })

    def _done(self, tx):
        tx._set_done()
        tx._post_process()

    def test_pay_001_website_provider_isolation(self):
        providers = self.env['payment.provider']
        self.assertEqual(self.provider.state, 'test')
        self.assertTrue(self.provider.is_published)
        self.assertTrue(self.payment_method.active)
        self.assertIn(self.payment_method, self.provider.payment_method_ids)
        before = providers.search([('company_id', '=', self.aushare.company_id.id)]).read(['state', 'website_id'])
        compatible = providers._get_compatible_providers(
            self.qclub.company_id.id, self.partner.id, 12.5,
            currency_id=self.currency.id, website_id=self.qclub.id)
        self.assertIn(self.provider, compatible)
        self.assertNotIn(self.provider, providers._get_compatible_providers(
            self.qclub.company_id.id, self.partner.id, 12.5,
            currency_id=self.currency.id, website_id=self.aushare.id))
        self.assertEqual(before, providers.search([('company_id', '=', self.aushare.company_id.id)]).read(['state', 'website_id']))

    def test_pay_002_reject_keys_before_provider_lookup(self):
        # Deliberately invalid placeholders, never usable credentials.
        for public, secret, webhook in [('bad', 'bad', 'bad'),
                                         ('pk_live_INVALID', 'sk_test_INVALID', 'whsec_INVALID'),
                                         ('pk_test_INVALID', 'sk_live_INVALID', 'whsec_INVALID'),
                                         ('pk_test_', 'sk_test_', 'whsec_')]:
            with self.assertRaises(ValidationError):
                self.config._configure_stripe_test(public, secret, webhook)
        with patch.object(type(self.config), '_stripe_test_provider', return_value=self.provider):
            # Mock the Stripe-only fields on an uninstalled provider without installing Stripe.
            with patch.object(type(self.provider), 'write', return_value=True) as write:
                self.config._configure_stripe_test('pk_test_INVALID', 'sk_test_INVALID', 'whsec_INVALID')
                self.assertEqual(write.call_args.args[0]['state'], 'test')
                self.assertEqual(write.call_args.args[0]['website_id'], self.qclub.id)
        if 'stripe_secret_key' not in self.provider._fields:
            with self.assertRaisesRegex(ValidationError, 'Stripe'):
                self.config._configure_stripe_test('pk_test_INVALID', 'sk_test_INVALID', 'whsec_INVALID')

    def test_pay_004_done_is_idempotent_and_option_a(self):
        booking = self._book()
        tx = self._tx(booking, provider_reference='offline-confirmation')
        before_payments = self.env['account.payment'].search_count([])
        before_moves = self.env['account.move'].search_count([])
        self._assert_no_booking_payments(booking)
        with patch.object(type(booking), '_queue_deposit_email') as mail:
            self._done(tx)
            tx._post_process()
            mail.assert_called_once()
        self.assertEqual((booking.state, booking.deposit_state), ('confirmed', 'paid'))
        self.assertEqual(booking.currency_id.compare_amounts(booking.paid_amount, booking.deposit_amount), 0)
        self.assertEqual(booking.payment_reference, 'offline-confirmation')
        self.assertTrue(booking.paid_at)
        self.assertEqual(booking.paid_transaction_id, tx)
        self.assertTrue(tx.reference.startswith(booking.name))
        self.assertTrue(tx.is_post_processed)
        self._assert_no_booking_payments(booking)
        self.assertEqual(self.env['account.payment'].search_count([]), before_payments)
        self.assertEqual(self.env['account.move'].search_count([]), before_moves)
        with patch.object(type(tx), '_send_refund_request') as request:
            refund = tx._refund()
            request.assert_called_once()
        self.assertEqual(tx.child_transaction_ids, refund)
        self._assert_no_booking_payments(booking)
        self.assertEqual(refund.qclub_booking_id, booking)
        self._done(refund)
        self.assertFalse(refund.payment_id)
        self._assert_no_booking_payments(booking)
        self.assertEqual(self.env['account.payment'].search_count([]), before_payments)
        self.assertEqual(self.env['account.move'].search_count([]), before_moves)

    def _assert_no_booking_payments(self, booking):
        transactions = self.env['payment.transaction'].search([('qclub_booking_id', '=', booking.id)])
        payments = self.env['account.payment'].search([('payment_transaction_id', 'in', transactions.ids)])
        self.assertFalse(payments)
        self.assertFalse(transactions.payment_id)

    def test_pay_004_unlinked_payment_delegates(self):
        booking = self._book()
        tx = self._tx(booking, qclub_booking_id=False)
        with patch('odoo.addons.account_payment.models.payment_transaction.PaymentTransaction._create_payment') as create:
            self._done(tx)
            create.assert_called_once()

    def test_pay_005_amount_and_currency_mismatch(self):
        for values in ({'amount': 1}, {'currency_id': self.currency_euro.id}):
            booking = self._book()
            self._done(self._tx(booking, **values))
            self.assertEqual(booking.state, 'pending')
            self.assertTrue(booking.payment_attention)
            self.assertIn('mismatch', booking.payment_attention_reason.lower())
            booking.action_cancel()

    def test_pay_006_expired_free_restores_only_from_payment(self):
        booking = self._book()
        booking._action_expire()
        with self.assertRaises(ValidationError):
            booking.write({'state': 'confirmed'})
        self._done(self._tx(booking))
        self.assertEqual(booking.state, 'confirmed')
        self.assertEqual(booking.deposit_state, 'paid')

    def test_pay_006_expired_taken_refunds_once(self):
        booking = self._book()
        tx = self._tx(booking)
        booking._action_expire()
        self._book(partner_id=self.default_partner.copy({'name': 'Other'}).id).action_confirm()
        with patch.object(type(tx), '_send_refund_request') as refund, \
                patch.object(type(booking), '_queue_deposit_email') as mail:
            self._done(tx)
            tx._post_process()
            refund.assert_called_once()
            mail.assert_called_once()
        self.assertEqual(booking.state, 'expired')
        self.assertTrue(booking.payment_attention)
        self.assertEqual(len(tx.child_transaction_ids), 1)
        self.assertEqual(self.currency.compare_amounts(tx.child_transaction_ids.amount, -tx.amount), 0)

    def test_pay_006_pending_past_lock_and_cancelled(self):
        booking = self._book()
        tx = self._tx(booking)
        with freeze_time('2026-11-01 00:11:00'):
            self._done(tx)
        self.assertEqual(booking.state, 'confirmed')
        booking.action_cancel()
        extra = self._book()
        extra.action_cancel()
        cancelled_tx = self._tx(extra)
        with patch.object(type(tx), '_send_refund_request') as refund:
            self._done(cancelled_tx)
            cancelled_tx._post_process()
            refund.assert_called_once()
        self.assertEqual(len(cancelled_tx.child_transaction_ids), 1)
        self.assertEqual(cancelled_tx.child_transaction_ids.operation, 'refund')
        self.assertEqual(extra.state, 'cancelled')

    def test_pay_007_failure_cancel_retry(self):
        booking = self._book()
        for state in ('error', 'cancel'):
            tx = self._tx(booking)
            tx.write({'state': state})
            tx._post_process()
            self.assertEqual((booking.state, booking.deposit_state), ('pending', 'awaiting'))
        self._done(self._tx(booking))
        self.assertFalse(booking._can_pay_deposit())

    def test_pay_008_pay_013_email_identity(self):
        booking = self._book()
        self._done(self._tx(booking))
        mail = self.env['mail.mail'].search([('subject', 'ilike', 'Deposit received'),
                                             ('body_html', 'ilike', booking.name)], limit=1)
        self.assertTrue(mail)
        self.assertEqual(mail.email_from, self.config.booking_email_from)
        for value in (booking.name, 'Q Club', booking.company_id.name, 'Free cancellation', booking._time_label()):
            self.assertIn(value, mail.body_html)
        for value in ('AUSHARE', 'card_number', '4242', 'cvc'):
            self.assertNotIn(value, mail.body_html)

    def test_pay_009_fields_protected_for_staff_managers(self):
        booking = self._book()
        for user in (self.staff, self.manager):
            for key, value in {'paid_amount': 1, 'deposit_state': 'paid', 'payment_reference': 'fake',
                               'payment_attention': False, 'lock_extended': True,
                               'paid_at': fields.Datetime.now(), 'paid_transaction_id': False,
                               'payment_attention_reason': 'fake'}.items():
                with self.assertRaises(ValidationError):
                    booking.with_user(user).write({key: value})
            self.assertIsInstance(booking.with_user(user).payment_transactions_html, str)
            view = booking.with_user(user).get_view(
                view_id=self.env.ref('qclub_billiard.qclub_booking_view_form').id, view_type='form')
            arch = etree.fromstring(view['arch'])
            for name in ('deposit_state', 'paid_amount', 'paid_at', 'payment_reference',
                         'payment_attention', 'lock_extended', 'payment_transactions_html'):
                nodes = arch.xpath(f"//field[@name='{name}']")
                self.assertTrue(nodes)
                self.assertTrue(all(n.get('readonly') in ('True', '1') for n in nodes))
            buttons = arch.xpath("//button[@name='action_refund_extra_payment']")
            self.assertEqual(bool(buttons), user == self.manager)

    def test_pay_010_manual_confirm_no_deposit(self):
        booking = self._book()
        booking.with_user(self.staff).action_confirm()
        self.assertEqual(booking.deposit_state, 'no_deposit')
        booking.action_cancel()
        self.assertEqual(self._book(booking_channel='backoffice').deposit_state, 'no_deposit')

    def test_pay_014_duplicate_and_manager_refund(self):
        booking = self._book()
        original = self._tx(booking)
        extra = self._tx(booking)
        self._done(original)
        with patch.object(type(extra), '_send_refund_request') as refund:
            self._done(extra)
            refund.assert_not_called()
        self.assertEqual(booking.payment_attention_reason, 'Duplicate deposit payment')
        self.assertEqual(booking.paid_transaction_id, original)
        self.assertTrue(self.env['mail.mail'].search_count([('email_to', '=', self.config.contact_email)]))
        with self.assertRaises(AccessError):
            booking.with_user(self.staff).action_refund_extra_payment()
        with self.assertRaises(ValidationError):
            self.env['qclub.deposit.refund'].with_user(self.manager).with_context(default_booking_id=booking.id).create({
                'booking_id': booking.id, 'transaction_id': str(extra.id), 'reason': '   ',
            })
        wizard = self.env['qclub.deposit.refund'].with_user(self.manager).with_context(default_booking_id=booking.id).create({
            'booking_id': booking.id, 'transaction_id': str(extra.id), 'reason': 'Two tabs paid',
        })
        with patch.object(type(extra), '_send_refund_request') as refund:
            wizard.action_refund()
            refund.assert_called_once()
        self.assertFalse(original.child_transaction_ids)
        self.assertEqual(len(extra.child_transaction_ids), 1)
        self.assertEqual(extra.child_transaction_ids.operation, 'refund')
        self.assertEqual(extra.child_transaction_ids.source_transaction_id, extra)
        self.assertEqual(self.currency.compare_amounts(extra.child_transaction_ids.amount, -extra.amount), 0)
        with self.assertRaises(ValidationError):
            wizard.action_refund()
        self.assertEqual(len(extra.child_transaction_ids), 1)
        self.assertTrue(booking.message_ids.filtered(lambda m: 'Two tabs paid' in str(m.body)
                                                       and self.manager.display_name in str(m.body)))
        # A refund request remains an issue until the provider confirms it.
        self.assertTrue(booking.payment_attention)
        self._done(extra.child_transaction_ids)
        self.assertFalse(booking.payment_attention)

    def test_pay_003_lock_extension_once(self):
        booking = self._book()
        booking._extend_payment_lock()
        self.assertFalse(booking.lock_extended)
        with freeze_time('2026-11-01 00:06:00'):
            booking._extend_payment_lock()
            self.assertEqual(booking.lock_expire, fields.Datetime.now() + timedelta(minutes=5))
        expiry = booking.lock_expire
        with freeze_time('2026-11-01 00:09:00'):
            booking._extend_payment_lock()
        self.assertEqual(booking.lock_expire, expiry)
