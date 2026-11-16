"""CFG-007: notification preferences do not change booking business events."""
from datetime import timedelta
from unittest.mock import patch
from xml.etree import ElementTree

from freezegun import freeze_time
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .test_cancel_refund import TestCancelRefund


@tagged('post_install', '-at_install')
class TestNotifyToggle(TestCancelRefund):
    toggles = (
        'notify_booking_received', 'notify_deposit_confirmed', 'notify_cancellation',
        'notify_no_show', 'notify_arrival',
    )

    def test_cfg_007_defaults_permissions_and_form(self):
        website = self.env['website'].create({'name': 'Notification defaults',
                                             'company_id': self.qclub.company_id.id})
        config = self.env['qclub.config'].with_user(self.manager)._get_for_website(website)
        arch = ElementTree.fromstring(self.env.ref('qclub_billiard.qclub_config_view_form').arch_db)
        for field in self.toggles:
            self.assertTrue(config[field], field)
            self.assertTrue(config.with_user(self.staff)[field], field)
            with self.assertRaises(AccessError):
                config.with_user(self.staff).write({field: False})
            config.with_user(self.manager).write({field: False})
            self.assertFalse(config[field], field)
            self.assertIsNotNone(arch.find(f".//group[@string='Notifications']/field[@name='{field}']"))

    def test_cfg_007_received_disabled_keeps_pending_hold(self):
        self.config.notify_booking_received = False
        before = self.env['mail.mail'].search_count([])
        booking = self._book()
        booking._queue_booking_email()
        self.assertEqual(booking.state, 'pending')
        self.assertTrue(booking.lock_expire)
        self.assertEqual(booking.deposit_amount, 12.5)
        self.assertEqual(self.env['mail.mail'].search_count([]), before)
        self.config.notify_booking_received = True
        booking._queue_booking_email()
        self.assertEqual(self.env['mail.mail'].search_count([]), before + 1)

    def test_cfg_007_deposit_disabled_keeps_confirmation_and_all_event_types(self):
        self.config.notify_deposit_confirmed = False
        before = self.env['mail.mail'].search_count([])
        booking, tx = self._paid()
        self.assertEqual((booking.state, booking.deposit_state), ('confirmed', 'paid'))
        self.assertEqual(self.currency.compare_amounts(booking.paid_amount, tx.amount), 0)
        for event in ('confirmed', 'duplicate', 'refunded', 'refund_pending'):
            booking._queue_deposit_email(event)
        self.assertEqual(self.env['mail.mail'].search_count([]), before)
        self.config.notify_deposit_confirmed = True
        for index, event in enumerate(('confirmed', 'duplicate', 'refunded', 'refund_pending'), 1):
            booking._queue_deposit_email(event)
            self.assertEqual(self.env['mail.mail'].search_count([]), before + index)

    def test_cfg_007_cancellation_disabled_keeps_refund_and_forfeiture(self):
        self.config.notify_cancellation = False
        for hours in (24, 23):
            booking, tx = self._paid()
            before = self.env['mail.mail'].search_count([])
            with freeze_time(booking.start - timedelta(hours=hours)), patch.object(
                    type(tx), '_send_refund_request', lambda tx: self._refund_done(tx)):
                booking.action_cancel()
                tx.child_transaction_ids._post_process()
            self.assertEqual(booking.state, 'cancelled')
            self.assertEqual(booking.deposit_state, 'refunded' if hours == 24 else 'forfeited')
            if hours == 24:
                self.assertEqual(self.currency.compare_amounts(booking.refund_amount, tx.amount), 0)
                self.assertEqual(len(tx.child_transaction_ids), 1)
            else:
                self.assertFalse(tx.child_transaction_ids)
            booking._queue_cancellation_email(attention=True)
            self.assertEqual(self.env['mail.mail'].search_count([]), before)

    def test_cfg_007_no_show_and_arrival_disabled_keep_audit_and_reversal(self):
        self.config.write({'notify_no_show': False, 'notify_arrival': False})
        booking, tx = self._paid()
        before = self.env['mail.mail'].search_count([])
        with freeze_time(booking.start + timedelta(minutes=30)):
            booking._mark_no_show()
        self.assertEqual((booking.state, booking.deposit_state), ('no_show', 'forfeited'))
        self.assertTrue(booking.no_show_at)
        self.assertEqual(self.env['mail.mail'].search_count([]), before)
        booking.with_user(self.manager)._revert_no_show('Customer present')
        self.assertEqual((booking.state, booking.deposit_state), ('arrived', 'paid'))
        self.assertEqual(self.currency.compare_amounts(booking.paid_amount, tx.amount), 0)
        self.assertEqual(booking.no_show_revert_reason, 'Customer present')
        self.assertEqual(booking.no_show_revert_operator_id, self.manager)
        self.assertTrue(booking.no_show_revert_at)
        self.assertEqual(self.env['mail.mail'].search_count([]), before)
        booking.action_complete()
        other, _tx = self._paid()
        before = self.env['mail.mail'].search_count([])
        with freeze_time(other.start):
            other.with_user(self.staff).action_arrive()
        self.assertEqual((other.state, other.deposit_state), ('arrived', 'paid'))
        self.assertEqual(self.env['mail.mail'].search_count([]), before)

    def test_cfg_007_preferences_are_per_website(self):
        # Use a separate test website, never alter AUSHARE's configuration or mail.
        website = self.env['website'].create({'name': 'Other notification site',
                                             'company_id': self.qclub.company_id.id,
                                             'domain': 'http://other.example.invalid'})
        config = self.env['qclub.config']._get_for_website(website)
        config.booking_email_from = 'other@example.invalid'
        self.env['qclub.opening.hours']._load_default_hours(website)
        kind = self.env['qclub.table.type'].create({'name': 'Other type', 'website_id': website.id})
        table = self.env['qclub.table'].create({'name': 'Other table', 'website_id': website.id,
                                               'type_id': kind.id, 'hourly_price': 25})
        booking = self._book()
        other = self._book(table_id=table.id)
        methods = (
            ('_queue_booking_email', ()), ('_queue_deposit_email', ('confirmed',)),
            ('_queue_cancellation_email', ()), ('_queue_no_show_email', ()),
            ('_queue_arrival_email', ()),
        )
        for field, (method, args) in zip(self.toggles, methods):
            self.config[field] = False
            self.assertTrue(config[field])
            before = self.env['mail.mail'].search_count([])
            getattr(booking, method)(*args)
            self.assertEqual(self.env['mail.mail'].search_count([]), before)
            getattr(other, method)(*args)
            self.assertEqual(self.env['mail.mail'].search_count([]), before + 1)
