from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import SQL
from odoo.tools.misc import format_amount

AUDIT_FIELDS = {
    'actual_table_fee', 'settle_reason', 'settle_operator_id', 'settle_at', 'balance_amount',
    'balance_method', 'settle_correction_reason', 'settle_correction_operator_id', 'settle_correction_at',
}


class BookingSettlement(models.Model):
    _inherit = 'qclub.booking'

    actual_table_fee = fields.Monetary(readonly=True, copy=False)
    settle_reason = fields.Char(readonly=True, copy=False)
    settle_operator_id = fields.Many2one('res.users', readonly=True, copy=False)
    settle_at = fields.Datetime(readonly=True, copy=False)
    balance_amount = fields.Monetary(readonly=True, copy=False)
    balance_method = fields.Selection([('eftpos', 'EFTPOS'), ('cash', 'Cash')], readonly=True, copy=False)
    settle_correction_reason = fields.Char(readonly=True, copy=False)
    settle_correction_operator_id = fields.Many2one('res.users', readonly=True, copy=False)
    settle_correction_at = fields.Datetime(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if any(AUDIT_FIELDS.intersection(vals) for vals in vals_list):
            raise ValidationError(_('Settlement facts cannot be edited directly.'))
        return super().create(vals_list)

    def write(self, vals):
        if AUDIT_FIELDS.intersection(vals):
            raise ValidationError(_('Settlement facts cannot be edited directly.'))
        return super().write(vals)

    def _check_settlement_access(self, correction=False):
        group = 'group_billiard_manager' if correction else 'group_billiard_staff'
        if not self.env.user.has_group('qclub_billiard.' + group):
            raise AccessError(_('Only billiard managers can correct a settlement.') if correction
                              else _('Only billiard staff can settle bookings.'))
        self.check_access('write')

    def action_settle(self):
        self.ensure_one()
        self._check_settlement_access()
        if self.state != 'arrived':
            raise UserError(_('Only arrived bookings can be settled.'))
        return {
            'type': 'ir.actions.act_window', 'res_model': 'qclub.booking.settle',
            'view_mode': 'form', 'view_id': self.env.ref('qclub_billiard.booking_settle_form').id,
            'target': 'new', 'context': {'default_booking_id': self.id, 'default_mode': 'settle'},
        }

    def action_correct_settlement(self):
        self.ensure_one()
        self._check_settlement_access(correction=True)
        if self.state != 'done':
            raise UserError(_('Only completed bookings can be corrected.'))
        return {
            'type': 'ir.actions.act_window', 'res_model': 'qclub.booking.settle',
            'view_mode': 'form', 'view_id': self.env.ref('qclub_billiard.booking_settle_correct_form').id,
            'target': 'new', 'context': {'default_booking_id': self.id, 'default_mode': 'correct',
                                      'default_actual_table_fee': self.actual_table_fee,
                                      'default_method': self.balance_method},
        }

    def action_complete(self):
        for booking in self:
            # Explicit default for the legacy convenience entry point only. The
            # interactive wizard must still supply a payment method itself.
            booking._settle(booking.table_fee, None, 'cash', correction=False)
        return True

    def _settle(self, actual_table_fee, reason, method, correction=False):
        self.ensure_one()
        self._check_settlement_access(correction)
        with self.env.cr.savepoint():
            self._lock_tables(self.table_id.ids)
            self.env.cr.execute(SQL('SELECT id FROM qclub_booking WHERE id = %s FOR UPDATE', self.id))
            self.invalidate_recordset()
            self._check_settlement_access(correction)
            expected = 'done' if correction else 'arrived'
            if self.state != expected:
                raise UserError(_('Only completed bookings can be corrected.') if correction
                                else _('Only arrived bookings can be settled.'))
            balance_due = max(self.currency_id.round(actual_table_fee - self.paid_amount), 0.0)
            if balance_due and not method:
                raise ValidationError(_('Select how the balance was paid.'))
            if self.currency_id.compare_amounts(actual_table_fee, self.table_fee) and not (reason and reason.strip()):
                raise ValidationError(_('A reason is required when the actual table fee differs from the booking.'))
            if correction and not (reason and reason.strip()):
                raise ValidationError(_('A reason is required to correct a settlement.'))
            values = {
                'actual_table_fee': actual_table_fee, 'balance_amount': balance_due,
                'balance_method': method if balance_due else False,
            }
            if correction:
                values.update({
                    'settle_correction_reason': reason.strip(), 'settle_correction_operator_id': self.env.uid,
                    'settle_correction_at': fields.Datetime.now(),
                })
            else:
                values.update({
                    'settle_reason': (reason or '').strip() or False, 'settle_operator_id': self.env.uid,
                    'settle_at': fields.Datetime.now(),
                })
                if self.deposit_state == 'paid':
                    values['deposit_state'] = 'applied'
                super().write({'state': 'done'})
            self._write_deposit(values)
            self.sudo().message_post(body=_(
                '%(event)s Actual table fee: %(fee)s. Balance: %(balance)s%(method)s. '
                'Reason: %(reason)s. Operator: %(operator)s.',
                event=_('Settlement corrected.') if correction else _('Booking settled.'),
                fee=format_amount(self.env, actual_table_fee, self.currency_id),
                balance=format_amount(self.env, balance_due, self.currency_id),
                method=f' via {method}' if balance_due and method else '',
                reason=(reason or '').strip(), operator=self.env.user.display_name,
            ))
