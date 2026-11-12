from datetime import timedelta

from markupsafe import Markup
from psycopg2.errors import ExclusionViolation

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools.misc import format_amount

from .qclub_booking import BookingConflict, QclubBooking

DEPOSIT_FIELDS = {
    'deposit_state', 'paid_amount', 'paid_at', 'payment_reference', 'paid_transaction_id',
    'payment_attention', 'payment_attention_reason', 'lock_extended',
}


class BookingDeposit(models.Model):
    _inherit = ['qclub.booking', 'mail.thread']
    _name = 'qclub.booking'

    deposit_state = fields.Selection([
        ('awaiting', 'Awaiting payment'), ('paid', 'Paid'), ('no_deposit', 'No online deposit'),
    ], required=True, default='no_deposit', readonly=True, copy=False)
    paid_amount = fields.Monetary(readonly=True, copy=False)
    paid_at = fields.Datetime(readonly=True, copy=False)
    payment_reference = fields.Char(readonly=True, copy=False)
    paid_transaction_id = fields.Many2one('payment.transaction', readonly=True, copy=False, ondelete='restrict')
    payment_attention = fields.Boolean(readonly=True, copy=False, index=True)
    payment_attention_reason = fields.Char(readonly=True, copy=False)
    lock_extended = fields.Boolean(readonly=True, copy=False)
    # Project only display data through sudo. A relation widget would need payment ACLs
    # on its subsequent browser RPC, even when its compute ran as sudo.
    has_extra_payment = fields.Boolean(compute='_compute_payment_transactions', compute_sudo=True)
    payment_transactions_html = fields.Html(compute='_compute_payment_transactions', compute_sudo=True)

    @api.depends('payment_attention', 'payment_attention_reason')
    def _compute_payment_transactions(self):
        for booking in self:
            transactions = self.env['payment.transaction'].sudo().search([('qclub_booking_id', '=', booking.id)])
            booking.has_extra_payment = any(tx.qclub_payment_issue == 'duplicate'
                                            and not tx.qclub_refund_requested for tx in transactions)
            booking.payment_transactions_html = Markup('<ul>%s</ul>') % Markup('').join(
                Markup('<li>%s — %s — %s</li>') % (tx.reference, tx.state,
                                                       format_amount(self.env, tx.amount, tx.currency_id))
                for tx in transactions
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if DEPOSIT_FIELDS.intersection(vals):
                raise ValidationError(_('Deposit facts cannot be edited directly.'))
        bookings = super().create(vals_list)
        for booking in bookings.filtered(lambda b: b.booking_channel == 'online'):
            booking._write_deposit({'deposit_state': 'awaiting'})
        return bookings

    def write(self, vals):
        if DEPOSIT_FIELDS.intersection(vals):
            raise ValidationError(_('Deposit facts cannot be edited directly.'))
        return super().write(vals)

    def _write_deposit(self, vals):
        """Private server-only write. No RPC-settable context flag bypasses protection."""
        return super(QclubBooking, self).write(vals)

    def action_confirm(self):
        result = super().action_confirm()
        self.filtered(lambda b: b.deposit_state == 'awaiting')._write_deposit({'deposit_state': 'no_deposit'})
        return result

    def _can_pay_deposit(self):
        self.ensure_one()
        return (self.booking_channel == 'online' and self.state == 'pending'
                and self.deposit_state == 'awaiting' and self.lock_expire
                and self.lock_expire > fields.Datetime.now())

    def _extend_payment_lock(self):
        self.ensure_one()
        now = fields.Datetime.now()
        if self._can_pay_deposit() and not self.lock_extended and self.lock_expire - now < timedelta(minutes=5):
            self._write_deposit({'lock_extended': True, 'lock_expire': now + timedelta(minutes=5)})

    def _refresh_payment_attention(self):
        for booking in self:
            issues = self.env['payment.transaction'].sudo().search([
                ('qclub_booking_id', '=', booking.id), ('qclub_payment_issue', '!=', False),
            ])
            remaining = issues.filtered(lambda tx: tx.qclub_payment_issue != 'duplicate' or not any(
                child.operation == 'refund' and child.state == 'done'
                and child.currency_id == tx.currency_id
                and tx.currency_id.compare_amounts(-child.amount, tx.amount) == 0
                for child in tx.child_transaction_ids
            ))
            labels = dict(issues._fields['qclub_payment_issue']._description_selection(self.env))
            booking._write_deposit({
                'payment_attention': bool(remaining),
                'payment_attention_reason': '; '.join(dict.fromkeys(labels[tx.qclub_payment_issue] for tx in remaining)) or False,
            })

    def _receive_deposit(self, tx):
        self.ensure_one()
        if tx.currency_id != self.currency_id or self.currency_id.compare_amounts(tx.amount, self.deposit_amount) != 0:
            tx.qclub_payment_issue = 'mismatch'
            self.message_post(body=_('Deposit amount or currency mismatch: %s', tx.reference))
        elif self.state == 'cancelled':
            self._refund_unavailable_deposit(tx)
        elif self.deposit_state == 'paid':
            tx.qclub_payment_issue = 'duplicate'
            self.message_post(body=_('Duplicate deposit payment: %s', tx.reference))
            self._queue_deposit_email('duplicate')
        elif self.state in ('pending', 'expired'):
            try:
                with self.env.cr.savepoint():
                    # Only this private payment path permits expired -> confirmed.
                    # Flush makes the exclusion constraint the final authority.
                    self._expire_stale_locks(self.table_id.ids)
                    super(QclubBooking, self).write({'state': 'confirmed'})
                    self.flush_recordset()
                    self._check_conflicts()
            except (ExclusionViolation, BookingConflict):
                self._refund_unavailable_deposit(tx)
            else:
                self._write_deposit({
                    'deposit_state': 'paid', 'paid_amount': tx.amount, 'paid_at': fields.Datetime.now(),
                    'payment_reference': tx.provider_reference or tx.reference, 'paid_transaction_id': tx.id,
                })
                self.message_post(body=_('Deposit received: %s', tx.reference))
                self._queue_deposit_email('confirmed')
        else:
            self._refund_unavailable_deposit(tx)
        self._refresh_payment_attention()

    def _refund_unavailable_deposit(self, tx):
        tx.qclub_payment_issue = 'slot'
        refund = tx._refund(amount_to_refund=tx.amount)
        tx.qclub_refund_requested = True
        self.message_post(body=_('Slot unavailable; full deposit refund requested: %s', tx.reference))
        self._queue_deposit_email('refunded' if refund.state == 'done' else 'refund_pending')
        if refund.state == 'done':
            refund.qclub_deposit_processed = True

    def _queue_deposit_email(self, event):
        self.ensure_one()
        config = self._config()
        recipient = config.contact_email if event == 'duplicate' else self.partner_id.email
        domain = (self.website_id.domain or '').rstrip('/')
        if not config.booking_email_from or not recipient or not domain.startswith(('https://', 'http://')):
            return
        labels = {
            'confirmed': _('Deposit received – booking confirmed'),
            'duplicate': _('Duplicate deposit payment – payment needs attention'),
            'refunded': _('Deposit refunded – slot no longer available'),
            'refund_pending': _('Deposit refund requested – slot no longer available'),
        }
        deadline = self.start - timedelta(hours=self.free_cancel_hours)
        body = self.env['ir.qweb']._render('qclub_billiard.deposit_email', {
            'booking': self, 'config': config, 'domain': domain, 'event': event,
            'event_label': labels[event], 'time_label': self._time_label(),
            'deadline_label': self._format_booking_time(deadline, deadline).split(' – ')[0],
        })
        mail = self.env['mail.mail'].sudo().create({
            'subject': f'{labels[event]}: {self.name}', 'email_from': config.booking_email_from,
            'email_to': recipient, 'body_html': body, 'auto_delete': False,
        })
        mail.send_after_commit()

    def action_refund_extra_payment(self):
        self.ensure_one()
        if not self.env.user.has_group('qclub_billiard.group_billiard_manager'):
            raise AccessError(_('Only billiard managers can refund extra payments.'))
        self.check_access('write')
        return {'type': 'ir.actions.act_window', 'res_model': 'qclub.deposit.refund',
                'view_mode': 'form', 'target': 'new', 'context': {'default_booking_id': self.id}}
