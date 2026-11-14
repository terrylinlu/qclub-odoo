from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import SQL
from odoo.tools.misc import format_amount


class DepositRefund(models.TransientModel):
    _name = 'qclub.deposit.refund'
    _description = 'Deposit Refund and Booking Cancellation'

    mode = fields.Selection([('extra_refund', 'Refund extra payment'), ('cancel', 'Cancel booking')],
                            required=True, default='extra_refund')
    booking_id = fields.Many2one('qclub.booking', required=True, readonly=True)
    website_id = fields.Many2one(related='booking_id.website_id', store=True)
    company_id = fields.Many2one(related='website_id.company_id', store=True)
    # Manager selection reads a safe projection, never payment.transaction ACLs.
    transaction_id = fields.Selection(selection='_extra_transaction_options',
                                      string='Extra payment')
    extra_payments_html = fields.Html(related='booking_id.payment_transactions_html', readonly=True)
    reason = fields.Char()
    outcome = fields.Char(compute='_compute_outcome')
    exception_available = fields.Boolean(compute='_compute_outcome')
    exception_refund = fields.Boolean(string='Exception full refund')

    @api.model_create_multi
    def create(self, vals_list):
        default_mode = self.default_get(['mode']).get('mode')
        for vals in vals_list:
            if vals.get('mode', default_mode) == 'extra_refund' and not self.env.user.has_group(
                    'qclub_billiard.group_billiard_manager'):
                raise AccessError(_('Only billiard managers can refund extra payments.'))
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('mode') == 'extra_refund' and not self.env.user.has_group(
                'qclub_billiard.group_billiard_manager'):
            raise AccessError(_('Only billiard managers can refund extra payments.'))
        return super().write(vals)

    @api.depends('booking_id', 'mode')
    def _compute_outcome(self):
        for wizard in self:
            wizard.outcome = False
            wizard.exception_available = False
            if wizard.mode == 'cancel' and wizard.booking_id:
                wizard.booking_id.check_access('write')
                outcome = wizard.booking_id._cancellation_outcome()
                wizard.outcome = outcome['text']
                wizard.exception_available = outcome['exception_allowed'] and self.env.user.has_group(
                    'qclub_billiard.group_billiard_manager')

    def action_cancel_booking(self):
        self.ensure_one()
        if not self.env.user.has_group('qclub_billiard.group_billiard_staff'):
            raise AccessError(_('Only billiard staff can use this wizard.'))
        if self.mode != 'cancel':
            raise ValidationError(_('Use the cancellation wizard to cancel a booking.'))
        self.booking_id._cancel_booking(exception_refund=self.exception_refund, reason=self.reason)
        return {'type': 'ir.actions.act_window_close'}

    @api.model
    def _extra_transaction_options(self):
        if not self.env.user.has_group('qclub_billiard.group_billiard_manager'):
            return []
        booking = self.env['qclub.booking'].browse(self.env.context.get('default_booking_id')).exists()
        if not booking:
            return []
        booking.check_access('write')
        transactions = self.env['payment.transaction'].sudo().search([
            ('qclub_booking_id', '=', booking.id), ('qclub_payment_issue', '=', 'duplicate'),
            ('state', '=', 'done'), ('qclub_refund_requested', '=', False),
        ])
        return [(str(tx.id), f'{tx.reference} — {format_amount(self.env, tx.amount, tx.currency_id)}')
                for tx in transactions]

    @api.constrains('mode', 'reason', 'transaction_id')
    def _check_reason(self):
        for wizard in self:
            if wizard.mode != 'extra_refund':
                continue
            if not self.env.user.has_group('qclub_billiard.group_billiard_manager'):
                raise AccessError(_('Only billiard managers can refund extra payments.'))
            if not wizard.transaction_id:
                raise ValidationError(_('Select an extra deposit transaction.'))
            if not wizard.reason or not wizard.reason.strip():
                raise ValidationError(_('A refund reason is required.'))

    def action_refund(self):
        self.ensure_one()
        if not self.env.user.has_group('qclub_billiard.group_billiard_manager'):
            raise AccessError(_('Only billiard managers can refund extra payments.'))
        if self.mode != 'extra_refund':
            raise ValidationError(_('Use the extra-payment refund wizard to refund an extra payment.'))
        self._check_reason()
        booking = self.booking_id
        booking.check_access('write')
        booking._lock_tables(booking.table_id.ids)
        self.env.cr.execute(SQL('SELECT id FROM qclub_booking WHERE id = %s FOR UPDATE', booking.id))
        tx = self.env['payment.transaction'].sudo().browse(int(self.transaction_id)).exists()
        if not tx:
            raise ValidationError(_('Select an extra deposit transaction.'))
        self.env.cr.execute(SQL('SELECT id FROM payment_transaction WHERE id = %s FOR UPDATE', tx.id))
        tx.invalidate_recordset()
        if (tx.qclub_booking_id != booking or tx.qclub_payment_issue != 'duplicate'
                or tx.state != 'done' or tx == booking.sudo().paid_transaction_id
                or tx.qclub_refund_requested or tx.child_transaction_ids.filtered(lambda c: c.operation == 'refund')):
            raise ValidationError(_('This transaction is not an unrefunded extra deposit.'))
        self._check_reason()
        tx._refund(amount_to_refund=tx.amount)
        tx.qclub_refund_requested = True
        booking.sudo().message_post(body=_(
            'Extra deposit refund: %(reference)s. Reason: %(reason)s. Operator: %(operator)s. Time (UTC): %(time)s.',
            reference=tx.reference, reason=self.reason.strip(), operator=self.env.user.display_name,
            time=fields.Datetime.now(),
        ))
        booking.sudo()._refresh_payment_attention()
        return {'type': 'ir.actions.act_window_close'}
