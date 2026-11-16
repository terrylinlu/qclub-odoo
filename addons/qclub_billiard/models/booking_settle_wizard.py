from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class BookingSettleWizard(models.TransientModel):
    _name = 'qclub.booking.settle'
    _description = 'Booking Settlement'

    mode = fields.Selection([('settle', 'Settle'), ('correct', 'Correct Settlement')],
                            required=True, default='settle')
    booking_id = fields.Many2one('qclub.booking', required=True, readonly=True)
    website_id = fields.Many2one(related='booking_id.website_id', store=True)
    company_id = fields.Many2one(related='website_id.company_id', store=True)
    currency_id = fields.Many2one(related='booking_id.currency_id')
    table_fee = fields.Monetary(related='booking_id.table_fee')
    paid_amount = fields.Monetary(related='booking_id.paid_amount')
    actual_table_fee = fields.Monetary()
    reason = fields.Char()
    balance_due = fields.Monetary(compute='_compute_balance')
    method = fields.Selection([('eftpos', 'EFTPOS'), ('cash', 'Cash')])

    @api.model
    def default_get(self, field_names):
        values = super().default_get(field_names)
        if 'actual_table_fee' in field_names and 'actual_table_fee' not in values and values.get('booking_id'):
            booking = self.env['qclub.booking'].browse(values['booking_id'])
            booking.check_access('write')
            values['actual_table_fee'] = booking.table_fee
        return values

    @api.model_create_multi
    def create(self, vals_list):
        default_mode = self.default_get(['mode']).get('mode')
        prepared = []
        for vals in vals_list:
            if vals.get('mode', default_mode) == 'correct' and not self.env.user.has_group(
                    'qclub_billiard.group_billiard_manager'):
                raise AccessError(_('Only billiard managers can correct a settlement.'))
            booking = self.env['qclub.booking'].browse(vals.get('booking_id') or self.env.context.get('default_booking_id'))
            booking.check_access('write')
            vals = dict(vals)
            if 'actual_table_fee' not in vals and 'default_actual_table_fee' not in self.env.context:
                vals['actual_table_fee'] = booking.table_fee
            prepared.append(vals)
        return super().create(prepared)

    def write(self, vals):
        if (vals.get('mode') == 'correct' or any(w.mode == 'correct' for w in self)) and not self.env.user.has_group(
                'qclub_billiard.group_billiard_manager'):
            raise AccessError(_('Only billiard managers can correct a settlement.'))
        if vals.get('booking_id'):
            self.env['qclub.booking'].browse(vals['booking_id']).check_access('write')
        return super().write(vals)

    @api.depends('actual_table_fee', 'booking_id.paid_amount', 'currency_id')
    def _compute_balance(self):
        for wizard in self:
            wizard.balance_due = max(wizard.currency_id.round(wizard.actual_table_fee - wizard.paid_amount), 0.0) \
                if wizard.currency_id else 0.0

    def action_confirm_settlement(self):
        self.ensure_one()
        if self.mode != 'settle':
            raise ValidationError(_('Use the settlement wizard to settle a booking.'))
        self.booking_id._settle(self.actual_table_fee, self.reason, self.method, correction=False)
        return {'type': 'ir.actions.act_window_close'}

    def action_confirm_correction(self):
        self.ensure_one()
        if self.mode != 'correct':
            raise ValidationError(_('Use the correction wizard to correct a settlement.'))
        self.booking_id._settle(self.actual_table_fee, self.reason, self.method, correction=True)
        return {'type': 'ir.actions.act_window_close'}
