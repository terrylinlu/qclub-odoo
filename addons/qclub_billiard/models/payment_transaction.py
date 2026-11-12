from odoo import api, fields, models
from odoo.tools import SQL


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    website_id = fields.Many2one('website', index=True, readonly=True, copy=False)
    qclub_booking_id = fields.Many2one('qclub.booking', index=True, readonly=True, ondelete='restrict', copy=False)
    qclub_deposit_processed = fields.Boolean(readonly=True, copy=False)
    qclub_payment_issue = fields.Selection([
        ('mismatch', 'Deposit amount or currency mismatch'),
        ('duplicate', 'Duplicate deposit payment'),
        ('slot', 'Slot unavailable; refund requested'),
    ], readonly=True, copy=False)
    qclub_refund_requested = fields.Boolean(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('source_transaction_id'):
                source = self.browse(vals['source_transaction_id'])
                if source.qclub_booking_id:
                    vals['qclub_booking_id'] = source.qclub_booking_id.id
                    vals['website_id'] = source.qclub_booking_id.website_id.id
            elif vals.get('qclub_booking_id'):
                vals['website_id'] = self.env['qclub.booking'].browse(vals['qclub_booking_id']).website_id.id
        return super().create(vals_list)

    @api.model
    def _compute_reference_prefix(self, separator, **values):
        booking = self.env['qclub.booking'].browse(values.get('qclub_booking_id')).exists()
        if booking:
            return booking.name
        return super()._compute_reference_prefix(separator, **values)

    def _qclub_booking(self):
        self.ensure_one()
        return self.qclub_booking_id or self.source_transaction_id.qclub_booking_id

    def _create_payment(self, **extra_create_values):
        self.ensure_one()
        if self._qclub_booking():
            return self.env['account.payment']
        return super()._create_payment(**extra_create_values)

    def _post_process(self):
        # Use Odoo's regular chain; the narrow _create_payment override implements Option A.
        for tx in self.filtered(lambda t: t.state == 'done' and t._qclub_booking()):
            booking = tx._qclub_booking().sudo()
            # Consistent table -> booking -> transaction lock order with booking creation/expiry.
            booking._lock_tables(booking.table_id.ids)
            self.env.cr.execute(SQL('SELECT id FROM qclub_booking WHERE id = %s FOR UPDATE', booking.id))
            self.env.cr.execute(SQL('SELECT id FROM payment_transaction WHERE id = %s FOR UPDATE', tx.id))
            booking.invalidate_recordset()
            tx.invalidate_recordset()
            if tx.operation == 'refund':
                if not tx.qclub_deposit_processed:
                    if tx.source_transaction_id.qclub_payment_issue == 'slot':
                        booking._queue_deposit_email('refunded')
                    tx.qclub_deposit_processed = True
                booking._refresh_payment_attention()
            elif not tx.qclub_deposit_processed:
                booking._receive_deposit(tx)
                tx.qclub_deposit_processed = True
        return super()._post_process()
