"""NS-001–005: cutoff, arrival, reversal and notification contracts."""
from datetime import timedelta
from xml.etree import ElementTree

from freezegun import freeze_time
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .test_cancel_refund import TestCancelRefund


@tagged('post_install', '-at_install')
class TestNoShow(TestCancelRefund):
    def test_ns_001_ns_003_cutoff_snapshot_and_idempotency(self):
        booking, tx = self._paid()
        self.config.no_show_wait_minutes = 90
        before = self.env['mail.mail'].search_count([])
        with freeze_time(booking.start + timedelta(minutes=29)):
            booking._cron_mark_no_show()
        self.assertEqual(booking.state, 'confirmed')
        cutoff = booking.start + timedelta(minutes=30)
        with freeze_time(cutoff):
            booking._cron_mark_no_show()
            booking._cron_mark_no_show()
        self.assertEqual((booking.state, booking.deposit_state), ('no_show', 'forfeited'))
        self.assertEqual(booking.no_show_at, cutoff)
        self.assertEqual(booking.paid_amount, tx.amount)
        self.assertEqual(self.env['mail.mail'].search_count([]), before + 1)
        mail = self.env['mail.mail'].search([('subject', '=', 'Booking no-show: ' + booking.name)])
        self.assertIn('deposit has been forfeited', mail.body_html)
        cron = self.env.ref('qclub_billiard.qclub_booking_cron_no_show')
        self.assertEqual((cron.interval_number, cron.interval_type), (1, 'minutes'))

    def test_ns_002_ns_005_arrival_boundaries_and_illegal_states(self):
        booking = self._book()
        with self.assertRaises(UserError):
            booking.action_arrive()
        booking.action_confirm()
        self.config.no_show_wait_minutes = 90
        for minutes in (-31, 30):
            with freeze_time(booking.start + timedelta(minutes=minutes)), self.assertRaises(UserError):
                booking.with_user(self.staff).action_arrive()
        with freeze_time(booking.start - timedelta(minutes=30)):
            booking.with_user(self.staff).action_arrive()
            with self.assertRaises(UserError):
                booking.action_arrive()
        self.assertEqual(booking.state, 'arrived')
        other = self._book(start='2026-11-06 04:30:00')
        other.action_confirm()
        with freeze_time(other.start + timedelta(minutes=29, seconds=59)):
            other.action_arrive()

    def test_ns_003_phone_email_and_no_email(self):
        for email in ('phone@example.invalid', False):
            self.partner.email = email
            booking = self._book(booking_channel='backoffice')
            booking.action_confirm()
            before = self.env['mail.mail'].search_count([])
            with freeze_time(booking.start + timedelta(minutes=30)):
                booking._cron_mark_no_show()
            self.assertEqual((booking.state, booking.deposit_state), ('no_show', 'no_deposit'))
            self.assertFalse(booking.paid_amount)
            self.assertTrue(booking.no_show_at)
            self.assertEqual(self.env['mail.mail'].search_count([]), before + bool(email))
            if email:
                mail = self.env['mail.mail'].search([('subject', '=', 'Booking no-show: ' + booking.name)])
                self.assertIn('Your booking was marked as no-show.', mail.body_html)
                self.assertNotIn('deposit', mail.body_html)

    def test_ns_004_reversal_permission_reason_audit_and_protection(self):
        booking, tx = self._paid()
        with freeze_time(booking.start + timedelta(minutes=30)):
            booking._cron_mark_no_show()
        with self.assertRaises(AccessError):
            booking.with_user(self.staff).action_revert_no_show()
        Wizard = self.env['qclub.deposit.refund']
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            Wizard.with_user(self.staff).create({'booking_id': booking.id, 'mode': 'no_show_revert'})
        action = booking.with_user(self.manager).action_revert_no_show()
        self.assertEqual(action['context']['default_mode'], 'no_show_revert')
        wizard = Wizard.with_user(self.manager).create({'booking_id': booking.id, 'mode': 'no_show_revert'})
        with self.assertRaises(ValidationError):
            wizard.action_revert_no_show()
        wizard.reason = 'Customer was present'
        wizard.action_revert_no_show()
        self.assertEqual((booking.state, booking.deposit_state), ('arrived', 'paid'))
        self.assertEqual(booking.paid_amount, tx.amount)  # ST-006 deposit available for settlement.
        self.assertEqual(booking.no_show_revert_operator_id, self.manager)
        self.assertEqual(booking.no_show_revert_reason, wizard.reason)
        self.assertTrue(booking.no_show_revert_at)
        with self.assertRaises(UserError):
            wizard.action_revert_no_show()
        for field in ('no_show_at', 'no_show_revert_at', 'no_show_revert_reason', 'no_show_revert_operator_id'):
            with self.assertRaises(ValidationError):
                booking.write({field: False})
        arch = ElementTree.fromstring(self.env.ref('qclub_billiard.qclub_booking_view_form').arch_db)
        self.assertFalse(arch.findall(".//button[@name='action_no_show']"))
        button = arch.find(".//button[@name='action_revert_no_show']")
        self.assertEqual(button.get('groups'), 'qclub_billiard.group_billiard_manager')

    def test_ns_001_ns_004_phone_revert_and_company_isolation(self):
        other = self.env['res.company'].browse(self.aushare.company_id.id)
        before = other.read(['name', 'currency_id'])
        booking = self._book(booking_channel='backoffice')
        booking.action_confirm()
        with freeze_time(booking.start + timedelta(minutes=30)):
            booking._cron_mark_no_show()
        booking.with_user(self.manager)._revert_no_show('Present')
        self.assertEqual((booking.state, booking.deposit_state), ('arrived', 'no_deposit'))
        self.assertEqual(other.read(['name', 'currency_id']), before)
