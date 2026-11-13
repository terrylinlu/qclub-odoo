"""Cancellation contracts: real Odoo refund children, mocked provider boundary only."""
from datetime import timedelta
from unittest.mock import patch

from freezegun import freeze_time
from odoo import Command
from odoo.tests.common import new_test_user
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.addons.payment.tests.common import PaymentCommon



@tagged('post_install', '-at_install')
@freeze_time('2026-11-01 00:00:00')
class TestCancelRefund(PaymentCommon):
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

    def _paid(self):
        booking = self._book()
        tx = self._tx(booking)
        self._done(tx)
        return booking, tx

    def _refund_done(self, tx):
        tx.provider_reference = 'offline-refund'
        tx._set_done()

    def test_rf_001_boundary_and_idempotency_option_a(self):
        for hours in (24, 25):
            booking, tx = self._paid()
            payments = self.env['account.payment'].search_count([])
            moves = self.env['account.move'].search_count([])
            with freeze_time(booking.start - timedelta(hours=hours)), patch.object(
                    type(tx), '_send_refund_request', lambda tx: self._refund_done(tx)):
                booking.action_cancel()
                booking.action_cancel()
                tx.child_transaction_ids._post_process()
            self.assertEqual(booking.state, 'cancelled')
            self.assertEqual(booking.deposit_state, 'refunded')
            self.assertEqual(len(tx.child_transaction_ids), 1)
            self.assertEqual(self.currency.compare_amounts(booking.refund_amount, tx.amount), 0)
            self.assertEqual(self.env['account.payment'].search_count([]), payments)
            self.assertEqual(self.env['account.move'].search_count([]), moves)

    def test_rf_002_inside_window_including_created_inside(self):
        for created_inside in (False, True):
            with freeze_time('2026-11-05 04:00:00' if created_inside else '2026-11-01'):
                booking, tx = self._paid()
            self.assertEqual(booking.created_in_cancel_window, created_inside)
            with freeze_time(booking.start - timedelta(hours=23, minutes=59)), patch.object(
                    type(tx), '_send_refund_request') as refund:
                booking.action_cancel()
            refund.assert_not_called()
            self.assertEqual(booking.deposit_state, 'forfeited')

    def test_rf_004_utc_dst_and_overnight(self):
        # Adelaide spring changeover 4 Oct, and Saturday night after midnight.
        for start in ('2026-10-04 03:30:00', '2026-11-07 14:30:00'):
            with freeze_time('2026-10-01' if '10-04' in start else '2026-11-01'):
                booking = self._book(start=start)
                tx = self._tx(booking)
                self._done(tx)
            with freeze_time(booking.start - timedelta(hours=24)):
                self.assertEqual(booking._cancellation_outcome()['kind'], 'refund')
            with freeze_time(booking.start - timedelta(hours=24) + timedelta(seconds=1)):
                self.assertEqual(booking._cancellation_outcome()['kind'], 'forfeit')
            with freeze_time(booking.start - timedelta(hours=1)):
                booking.action_cancel()

    def test_rf_005_exception_permission_reason_and_window(self):
        booking, tx = self._paid()
        with self.assertRaises(ValidationError):
            booking._cancel_booking(exception_refund=True, reason='Outside window')
        with freeze_time(booking.start - timedelta(hours=1)):
            with self.assertRaises(AccessError):
                booking.with_user(self.staff)._cancel_booking(exception_refund=True, reason='Reason')
            with self.assertRaises(ValidationError):
                booking.with_user(self.manager)._cancel_booking(exception_refund=True, reason=' ')
            with patch.object(type(tx), '_send_refund_request', lambda tx: self._refund_done(tx)):
                booking.with_user(self.manager)._cancel_booking(exception_refund=True, reason='Courtesy')
        self.assertEqual(booking.deposit_state, 'refunded')
        self.assertEqual(booking.refund_reason, 'Exception refund: Courtesy')
        self.assertEqual(booking.refund_operator_id, self.manager)

    def test_rf_006_failure_retry_and_later_failure(self):
        booking, tx = self._paid()
        with patch.object(type(tx), '_send_refund_request', side_effect=ValidationError('Offline failure')):
            booking.action_cancel()
        self.assertEqual((booking.state, booking.deposit_state), ('cancelled', 'refund_failed'))
        self.assertTrue(booking.payment_attention)
        self.assertTrue(self.env['mail.mail'].search_count([
            ('email_to', '=', self.config.contact_email), ('subject', 'ilike', 'Refund failed')]))
        with self.assertRaises(AccessError):
            booking.with_user(self.staff).action_retry_refund()
        with patch.object(type(tx), '_send_refund_request', lambda tx: self._refund_done(tx)):
            booking.with_user(self.manager).action_retry_refund()
            booking.with_user(self.manager).action_retry_refund()
        self.assertEqual(booking.deposit_state, 'refunded')
        done = tx.child_transaction_ids.filtered(lambda child: child.state == 'done')
        self.assertEqual(len(done), 1)
        self.assertEqual(self.currency.compare_amounts(-sum(done.mapped('amount')), tx.amount), 0)
        self.assertFalse(booking.payment_attention)

    def test_rf_007_email_three_outcomes_and_board_closure(self):
        for kind in ('refund', 'forfeit', 'none'):
            booking = self._book()
            if kind != 'none':
                tx = self._tx(booking)
                self._done(tx)
            if kind == 'none':
                booking.action_confirm()
            post = self.env['qclub.board.post'].sudo().create({
                'booking_id': booking.id, 'partner_id': booking.partner_id.id,
                'players_needed': 1, 'message': 'Offline cancellation test',
            }) if kind != 'none' else self.env['qclub.board.post']
            with freeze_time(booking.start - timedelta(hours=1 if kind == 'forfeit' else 25)), patch.object(
                    type(self.env['payment.transaction']), '_send_refund_request', lambda tx: self._refund_done(tx)):
                booking.action_cancel()
            if post:
                self.assertEqual(post.state, 'closed')
            mail = self.env['mail.mail'].search([('subject', '=', 'Booking cancelled: ' + booking.name)], limit=1)
            self.assertTrue(mail)
            self.assertIn({'refund': 'refunded', 'forfeit': 'non-refundable', 'none': 'no deposit'}[kind], mail.body_html)

    def test_rf_008_pending_unpaid_and_started_rejected(self):
        booking = self._book()
        with freeze_time(booking.start):
            with self.assertRaisesRegex(ValidationError, 'started'):
                booking.action_cancel()
        booking.action_cancel()
        self.assertEqual((booking.state, booking.deposit_state), ('cancelled', 'awaiting'))
        self.assertFalse(booking.refund_amount)

    def test_st_002_reason_operator_and_protected_facts(self):
        booking, tx = self._paid()
        with patch.object(type(tx), '_send_refund_request', lambda tx: self._refund_done(tx)):
            booking.with_user(self.staff).action_cancel()
        self.assertEqual(booking.refund_reason, 'Free cancellation')
        self.assertEqual(booking.refund_operator_id, self.staff)
        self.assertTrue(booking.refund_at)
        self.assertEqual(booking.refund_reference, 'offline-refund')
        self.assertTrue(booking.message_ids.filtered(lambda m: 'Free cancellation' in str(m.body)))
        with self.assertRaises(ValidationError):
            booking.write({'refund_amount': 1})

    def test_rf_006_late_refund_failure_postprocessing(self):
        for state in ('error', 'cancel'):
            booking, tx = self._paid()
            with patch.object(type(tx), '_send_refund_request'):
                booking.action_cancel()
            refund = tx.child_transaction_ids
            refund.write({'state': state})
            refund._post_process()
            refund._post_process()
            self.assertEqual((booking.state, booking.deposit_state), ('cancelled', 'refund_failed'))
            self.assertTrue(booking.payment_attention)
            self.assertEqual(self.env['mail.mail'].search_count([
                ('subject', '=', 'Refund failed – payment needs attention: ' + booking.name)]), 1)
            with patch.object(type(tx), '_send_refund_request', lambda child: self._refund_done(child)):
                booking.with_user(self.manager).action_retry_refund()
            self.assertEqual(booking.deposit_state, 'refunded')

    def test_rf_006_failure_after_successful_postprocessing(self):
        booking, tx = self._paid()
        with patch.object(type(tx), '_send_refund_request', lambda child: self._refund_done(child)):
            booking.action_cancel()
        refund = tx.child_transaction_ids
        refund._post_process()
        # charge.refund.updated may change a previously successful refund to error.
        refund._set_error('Offline later failure', extra_allowed_states=('done',))
        refund._post_process()
        self.assertEqual(booking.deposit_state, 'refund_failed')
        self.assertTrue(booking.payment_attention)

    def test_rf_005_wizard_visibility_and_pending_entry(self):
        booking, tx = self._paid()
        for user in (self.manager, self.staff):
            wizard = self.env['qclub.deposit.refund'].with_user(user).create({'booking_id': booking.id, 'mode': 'cancel'})
            self.assertFalse(wizard.exception_available)
            with freeze_time(booking.start - timedelta(hours=1)):
                wizard.invalidate_recordset()
                self.assertEqual(wizard.exception_available, user == self.manager)
        with patch.object(type(tx), '_send_refund_request'):
            booking.action_cancel()
        pending = self._book()
        action = pending.with_user(self.staff).with_context(qclub_cancel_dialog=True).action_cancel()
        self.assertEqual(action['res_model'], 'qclub.deposit.refund')
        self.assertEqual(action['context']['default_mode'], 'cancel')
        self.assertEqual(action['view_id'], self.env.ref('qclub_billiard.deposit_cancel_form').id)
        wizard = self.env['qclub.deposit.refund'].with_user(self.staff).create({'booking_id': pending.id, 'mode': 'cancel'})
        wizard.action_cancel_booking()
        self.assertEqual((pending.state, pending.deposit_state), ('cancelled', 'awaiting'))

    def test_rf_008_manually_confirmed_no_deposit(self):
        booking = self._book()
        booking.action_confirm()
        self.assertEqual(booking._cancellation_outcome()['kind'], 'none')
        booking.action_cancel()
        self.assertEqual(booking.deposit_state, 'no_deposit')

    def test_rf_006_request_exception_retains_attempt_and_retry(self):
        booking, tx = self._paid()
        with patch.object(type(tx), '_send_refund_request', side_effect=RuntimeError('Offline request failure')):
            booking.action_cancel()
        self.assertEqual((booking.state, booking.deposit_state), ('cancelled', 'refund_failed'))
        self.assertEqual(len(tx.child_transaction_ids), 1)
        self.assertEqual(tx.child_transaction_ids.state, 'error')
        with patch.object(type(tx), '_send_refund_request', lambda child: self._refund_done(child)):
            booking.with_user(self.manager).action_retry_refund()
            booking.with_user(self.manager).action_retry_refund()
        self.assertEqual(booking.deposit_state, 'refunded')
        self.assertEqual(len(tx.child_transaction_ids.filtered(lambda c: c.state == 'done')), 1)

    def test_rf_005_shared_wizard_modes_enforce_permissions(self):
        booking, tx = self._paid()
        extra = self._tx(booking)
        self._done(extra)
        Wizard = self.env['qclub.deposit.refund'].with_context(default_booking_id=booking.id)
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            Wizard.with_user(self.staff).create({
                'booking_id': booking.id, 'mode': 'extra_refund',
                'transaction_id': str(extra.id), 'reason': 'Duplicate payment',
            })
        staff_cancel = Wizard.with_user(self.staff).create({'booking_id': booking.id, 'mode': 'cancel'})
        self.assertEqual(staff_cancel._extra_transaction_options(), [])
        with self.assertRaises(AccessError):
            staff_cancel.action_refund()
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            staff_cancel.write({'mode': 'extra_refund'})
        manager_extra = Wizard.with_user(self.manager).create({
            'booking_id': booking.id, 'transaction_id': str(extra.id), 'reason': 'Duplicate payment',
        })
        self.assertEqual(manager_extra.mode, 'extra_refund')
        with self.assertRaises(ValidationError):
            manager_extra.action_cancel_booking()
        self.assertFalse(manager_extra.outcome)
        self.assertFalse(manager_extra.exception_available)
        with patch.object(type(tx), '_send_refund_request', lambda child: self._refund_done(child)):
            manager_extra.action_refund()
        self.assertEqual(booking.state, 'confirmed')
        self.assertFalse(tx.child_transaction_ids)
        self.assertEqual(len(extra.child_transaction_ids), 1)
        action = booking.with_user(self.manager).action_refund_extra_payment()
        self.assertEqual(action['context']['default_mode'], 'extra_refund')
        self.assertEqual(action['view_id'], self.env.ref('qclub_billiard.deposit_refund_form').id)

    def test_rf_005_shared_wizard_cancel_exception_and_required_extra_fields(self):
        booking, tx = self._paid()
        Wizard = self.env['qclub.deposit.refund'].with_context(default_booking_id=booking.id)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            Wizard.with_user(self.manager).create({'booking_id': booking.id, 'reason': 'Missing transaction'})
        with freeze_time(booking.start - timedelta(hours=1)):
            staff_cancel = Wizard.with_user(self.staff).create({
                'booking_id': booking.id, 'mode': 'cancel', 'exception_refund': True, 'reason': 'Forged request',
            })
            with self.assertRaises(AccessError):
                staff_cancel.action_cancel_booking()
            manager_cancel = Wizard.with_user(self.manager).create({
                'booking_id': booking.id, 'mode': 'cancel', 'exception_refund': True,
            })
            with self.assertRaises(ValidationError):
                manager_cancel.action_cancel_booking()
            manager_cancel.reason = 'Courtesy'
            with patch.object(type(tx), '_send_refund_request', lambda child: self._refund_done(child)):
                manager_cancel.action_cancel_booking()
        self.assertEqual(booking.refund_reason, 'Exception refund: Courtesy')
        self.assertEqual(booking.deposit_state, 'refunded')

    def test_rf_007_deposit_and_cancellation_email_opt_out(self):
        booking = self._book(booking_channel='backoffice')
        Mail = self.env['mail.mail']
        before = Mail.search_count([])
        booking.action_cancel()
        for event in ('confirmed', 'duplicate', 'refunded', 'refund_pending'):
            booking._queue_deposit_email(event)
        self.assertEqual(Mail.search_count([]), before)
        online = self._book()
        self.config.booking_email_from = False
        online._queue_cancellation_email()
        online._queue_cancellation_email(attention=True)
        for event in ('confirmed', 'duplicate', 'refunded', 'refund_pending'):
            online._queue_deposit_email(event)
        self.assertEqual(Mail.search_count([]), before)
        self.config.booking_email_from = 'Q Club <booking@qclub.example>'
        online.partner_id.email = False
        online._queue_cancellation_email()
        online._queue_deposit_email('confirmed')
        self.config.contact_email = False
        online._queue_cancellation_email(attention=True)
        online._queue_deposit_email('duplicate')
        self.assertEqual(Mail.search_count([]), before)

    def test_rf_007_mail_failure_preserves_payment_cancellation_and_refund(self):
        booking = self._book()
        tx = self._tx(booking)
        Mail = self.env['mail.mail']
        original_create = type(Mail).create
        def fail_after_create(records, values):
            original_create(records, values)
            raise RuntimeError('Offline queue failure after insert')
        with patch.object(type(Mail), 'create', fail_after_create), patch(
                'odoo.addons.qclub_billiard.models.booking_deposit._logger') as logger:
            before = Mail.search_count([])
            self._done(tx)
            self.assertEqual((booking.state, booking.deposit_state), ('confirmed', 'paid'))
            self.assertEqual(Mail.search_count([]), before)
            with patch.object(type(tx), '_send_refund_request', lambda child: self._refund_done(child)):
                booking.action_cancel()
            self.assertEqual((booking.state, booking.deposit_state), ('cancelled', 'refunded'))
            self.assertEqual(Mail.search_count([]), before)
            self.assertGreaterEqual(logger.exception.call_count, 2)

    def test_rf_007_email_render_and_send_registration_failure_are_isolated(self):
        booking = self._book()
        Mail = self.env['mail.mail']
        for model, method in ((type(self.env['ir.qweb']), '_render'), (type(Mail), 'send_after_commit')):
            with patch.object(model, method, side_effect=RuntimeError('Offline mail failure')), patch(
                    'odoo.addons.qclub_billiard.models.booking_deposit._logger') as logger:
                before = Mail.search_count([])
                for event in ('confirmed', 'duplicate', 'refunded', 'refund_pending'):
                    booking._queue_deposit_email(event)
                booking._queue_cancellation_email()
                booking._queue_cancellation_email(attention=True)
                self.assertEqual(Mail.search_count([]), before)
                self.assertEqual(logger.exception.call_count, 6)

    def test_rf_007_board_queue_boundary_failure_does_not_undo_cancellation(self):
        booking, tx = self._paid()
        post = self.env['qclub.board.post'].create({
            'booking_id': booking.id, 'players_needed': 1, 'message': 'Queue isolation test',
        })
        applicant = self.partner.copy({'name': 'Offline applicant', 'email': 'applicant@example.invalid'})
        application = self.env['qclub.board.application'].create({
            'post_id': post.id, 'partner_id': applicant.id,
        })
        application._transition('accept', booking.partner_id)
        with patch.object(type(post), '_queue_email', side_effect=RuntimeError('Offline board queue failure')), patch(
                'odoo.addons.qclub_billiard.models.qclub_board._logger') as logger, patch.object(
                    type(tx), '_send_refund_request', lambda child: self._refund_done(child)):
            booking.action_cancel()
            logger.exception.assert_called_once()
        self.assertEqual((booking.state, booking.deposit_state), ('cancelled', 'refunded'))
        self.assertEqual(post.state, 'closed')
        self.assertEqual(application.state, 'accepted')

    def test_rf_007_board_four_mails_plus_online_customer_cancellation(self):
        self.partner.email = 'owner@example.invalid'
        applicant = self.partner.copy({'name': 'Offline applicant', 'email': 'applicant@example.invalid'})
        Mail = self.env['mail.mail']
        for channel in ('backoffice', 'online'):
            booking = self._book(booking_channel=channel, duration_hours=2)
            booking.action_confirm()
            post = self.env['qclub.board.post'].create({
                'booking_id': booking.id, 'players_needed': 1, 'message': 'Notification audience test',
            })
            before = Mail.search([])
            application = self.env['qclub.board.application'].create({
                'post_id': post.id, 'partner_id': applicant.id,
            })
            application._transition('accept', booking.partner_id)
            booking.write({'duration_hours': 1})
            booking.action_cancel()
            added = Mail.search([]) - before
            cancellation = added.filtered(lambda m: m.subject == 'Booking cancelled: ' + booking.name)
            board_mails = added - cancellation
            self.assertEqual(len(board_mails), 4)
            self.assertEqual(board_mails.mapped('email_to').count(applicant.email), 3)
            self.assertEqual(len(cancellation), 1 if channel == 'online' else 0)
            if cancellation:
                self.assertEqual(cancellation.email_to, booking.partner_id.email)
                self.assertIn('no deposit', cancellation.body_html)
