"""ST-001, ST-005–007 settlement and correction contracts."""
from freezegun import freeze_time
from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import new_test_user

from .test_cancel_refund import TestCancelRefund


@tagged('post_install', '-at_install')
class TestSettlement(TestCancelRefund):
    def _arrived(self, paid=True):
        if paid:
            booking, tx = self._paid()
        else:
            booking = self._book(booking_channel='backoffice')
            booking.action_confirm()
        with freeze_time(booking.start):
            booking.with_user(self.staff).action_arrive()
        return booking

    def _wizard(self, booking, user=None, **values):
        action = booking.with_user(user or self.staff).action_settle()
        return self.env[action['res_model']].with_user(user or self.staff).with_context(
            **action['context']).create(values)

    def test_st_001_st_005_default_and_changed_fee(self):
        booking = self._arrived()
        wizard = self._wizard(booking)
        self.assertEqual(wizard.actual_table_fee, booking.table_fee)
        self.assertEqual(wizard.balance_due, 12.5)
        wizard.method = 'eftpos'
        wizard.actual_table_fee = 40
        for reason in (False, '   '):
            wizard.reason = reason
            with self.assertRaises(ValidationError):
                wizard.action_confirm_settlement()
        self.assertEqual(booking.state, 'arrived')
        wizard.reason = ' Extra time '
        wizard.action_confirm_settlement()
        self.assertEqual((booking.state, booking.actual_table_fee, booking.balance_amount), ('done', 40, 27.5))
        self.assertEqual(booking.settle_reason, 'Extra time')
        self.assertEqual(booking.settle_operator_id, self.staff)
        self.assertTrue(booking.settle_at)
        self.assertEqual(booking.balance_method, 'eftpos')
        self.assertEqual(booking.deposit_state, 'applied')
        with self.assertRaises(UserError):
            wizard.action_confirm_settlement()
        booking = self._arrived()
        self._wizard(booking, method='cash').action_confirm_settlement()
        self.assertFalse(booking.settle_reason)

    def test_st_006_boundaries_no_refund_and_required_method(self):
        for fee in (12.5, 10, 0):
            booking = self._arrived()
            tx = booking.sudo().paid_transaction_id
            refund_fields = ['refund_amount', 'refund_at', 'refund_reference', 'refund_reason',
                             'refund_operator_id', 'refund_transaction_id']
            before = booking.read(refund_fields)
            wizard = self._wizard(booking, actual_table_fee=fee, reason='Discount', method=False if fee == 12.5 else 'cash')
            self.assertEqual(wizard.balance_due, 0)
            wizard.action_confirm_settlement()
            self.assertEqual((booking.balance_amount, booking.balance_method), (0, False))
            self.assertEqual(booking.deposit_state, 'applied')
            self.assertEqual(booking.read(refund_fields), before)
            self.assertFalse(tx.child_transaction_ids)
        booking = self._arrived()
        wizard = self._wizard(booking)
        with self.assertRaises(ValidationError):
            wizard.action_confirm_settlement()
        self.assertEqual(booking.state, 'arrived')

    def test_st_006_phone_and_default_completion_wrapper(self):
        booking = self._arrived(paid=False)
        wizard = self._wizard(booking)
        self.assertEqual(wizard.balance_due, booking.table_fee)
        with self.assertRaises(ValidationError):
            wizard.action_confirm_settlement()
        wizard.method = 'cash'
        wizard.action_confirm_settlement()
        self.assertEqual((booking.balance_amount, booking.deposit_state), (25, 'no_deposit'))
        booking = self._arrived()
        booking.with_user(self.staff).action_complete()
        self.assertEqual((booking.state, booking.balance_amount, booking.balance_method), ('done', 12.5, 'cash'))

    def test_st_005_illegal_states_and_st_007_correction_state(self):
        booking = self._book()
        for state in ('pending', 'confirmed', 'done', 'cancelled', 'expired', 'no_show'):
            # Private setup only: exercise every terminal and pre-arrival state.
            booking._write_deposit({'state': state})
            with self.assertRaises(UserError):
                booking.with_user(self.staff).action_settle()
            wizard = self.env['qclub.booking.settle'].with_user(self.staff).create({
                'booking_id': booking.id, 'actual_table_fee': 25, 'method': 'cash',
            })
            with self.assertRaises(UserError):
                wizard.action_confirm_settlement()
            if state != 'done':
                with self.assertRaises(UserError):
                    booking.with_user(self.manager).action_correct_settlement()

    def test_st_007_correction_permission_reason_audit_and_modes(self):
        booking = self._arrived()
        self._wizard(booking, method='cash').action_confirm_settlement()
        original = (booking.settle_at, booking.settle_operator_id, booking.settle_reason)
        Wizard = self.env['qclub.booking.settle']
        with self.assertRaises(AccessError):
            booking.with_user(self.staff).action_correct_settlement()
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            Wizard.with_user(self.staff).with_context(default_mode='correct').create({'booking_id': booking.id})
        staff_wizard = Wizard.with_user(self.staff).create({'booking_id': booking.id})
        with self.assertRaises(AccessError):
            staff_wizard.write({'mode': 'correct'})
        with self.assertRaises(ValidationError):
            staff_wizard.action_confirm_correction()
        action = booking.with_user(self.manager).action_correct_settlement()
        wizard = Wizard.with_user(self.manager).with_context(**action['context']).create({})
        self.assertEqual(wizard.actual_table_fee, 25)
        self.assertEqual(wizard.method, 'cash')
        with self.assertRaises(ValidationError):
            wizard.action_confirm_settlement()
        wizard.reason = '  '
        with self.assertRaises(ValidationError):
            wizard.action_confirm_correction()
        wizard.write({'actual_table_fee': 50, 'method': 'eftpos', 'reason': ' Correct charge '})
        wizard.action_confirm_correction()
        self.assertEqual((booking.actual_table_fee, booking.balance_amount, booking.balance_method), (50, 37.5, 'eftpos'))
        self.assertEqual((booking.settle_at, booking.settle_operator_id, booking.settle_reason), original)
        self.assertEqual(booking.settle_correction_reason, 'Correct charge')
        self.assertEqual(booking.settle_correction_operator_id, self.manager)
        self.assertTrue(booking.settle_correction_at)
        self.assertEqual(booking.deposit_state, 'applied')
        for name in ('actual_table_fee', 'balance_amount', 'balance_method', 'settle_reason', 'settle_operator_id',
                     'settle_at', 'settle_correction_reason', 'settle_correction_operator_id', 'settle_correction_at'):
            with self.assertRaises(ValidationError):
                booking.write({name: False})
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._book(actual_table_fee=1)
        self.assertTrue(booking.message_ids.filtered(lambda m: 'Correct charge' in str(m.body)))

    def test_st_007_company_isolation(self):
        booking = self._arrived()
        other_company = self.aushare.company_id
        before = other_company.read(['name', 'currency_id'])
        outsider = new_test_user(self.env, login='settlement-other-company',
                                 groups='qclub_billiard.group_billiard_manager',
                                 company_id=other_company.id, company_ids=[Command.set(other_company.ids)])
        with self.assertRaises(AccessError):
            booking.with_user(outsider).action_settle()
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            self.env['qclub.booking.settle'].with_user(outsider).create({'booking_id': booking.id})
        self._wizard(booking, method='cash').action_confirm_settlement()
        with self.assertRaises(AccessError):
            booking.with_user(outsider).action_correct_settlement()
        self.assertEqual(other_company.read(['name', 'currency_id']), before)
