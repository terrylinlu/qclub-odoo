import logging
from datetime import timedelta

from markupsafe import Markup
from psycopg2.errors import ExclusionViolation

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import SQL
from odoo.tools.misc import format_amount

from .qclub_booking import BookingConflict, QclubBooking

_logger = logging.getLogger(__name__)

DEPOSIT_FIELDS = {
    'deposit_state', 'paid_amount', 'paid_at', 'payment_reference', 'paid_transaction_id',
    'payment_attention', 'payment_attention_reason', 'lock_extended',
    'refund_amount', 'refund_at', 'refund_reference', 'refund_reason', 'refund_operator_id',
    'refund_transaction_id', 'refund_failure',
}


class BookingDeposit(models.Model):
    _inherit = ['qclub.booking', 'mail.thread']
    _name = 'qclub.booking'

    deposit_state = fields.Selection([
        ('awaiting', 'Awaiting payment'), ('paid', 'Paid'), ('no_deposit', 'No online deposit'),
        ('refunded', 'Refunded'), ('forfeited', 'Forfeited'), ('refund_failed', 'Refund failed'),
    ], required=True, default='no_deposit', readonly=True, copy=False)
    refund_amount = fields.Monetary(readonly=True, copy=False)
    refund_at = fields.Datetime(readonly=True, copy=False)
    refund_reference = fields.Char(readonly=True, copy=False)
    refund_reason = fields.Char(readonly=True, copy=False)
    refund_operator_id = fields.Many2one('res.users', readonly=True, copy=False)
    refund_transaction_id = fields.Many2one('payment.transaction', readonly=True, copy=False, ondelete='restrict')
    refund_failure = fields.Char(readonly=True, copy=False)
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
            booking_id = booking._origin.id
            if not booking_id:
                booking.has_extra_payment = False
                booking.payment_transactions_html = False
                continue
            transactions = self.env['payment.transaction'].sudo().search([('qclub_booking_id', '=', booking_id)])
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
        if vals.get('state') == 'cancelled':
            if set(vals) != {'state'}:
                raise ValidationError(_('Cancel the booking separately from other changes.'))
            for booking in self:
                booking._cancel_booking()
            return True
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
                'payment_attention': bool(remaining) or bool(booking.refund_failure),
                'payment_attention_reason': '; '.join(filter(None, [*dict.fromkeys(labels[tx.qclub_payment_issue] for tx in remaining),
                                                       booking.refund_failure])) or False,
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
        if self.booking_channel != 'online' or not config.booking_email_from or not recipient:
            return
        try:
            with self.env.cr.savepoint():
                domain = (self.website_id.domain or '').rstrip('/')
                if not domain.startswith(('https://', 'http://')):
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
        except Exception:
            _logger.exception("Could not queue deposit email for booking %s", self.id)

    def action_refund_extra_payment(self):
        self.ensure_one()
        if not self.env.user.has_group('qclub_billiard.group_billiard_manager'):
            raise AccessError(_('Only billiard managers can refund extra payments.'))
        self.check_access('write')
        return {'type': 'ir.actions.act_window', 'res_model': 'qclub.deposit.refund',
                'view_mode': 'form', 'view_id': self.env.ref('qclub_billiard.deposit_refund_form').id,
                'target': 'new', 'context': {'default_booking_id': self.id, 'default_mode': 'extra_refund'}}

    def _can_cancel(self):
        self.ensure_one()
        return self.state in ('pending', 'confirmed') and self.start > fields.Datetime.now()

    def _cancellation_outcome(self):
        self.ensure_one()
        if not self._can_cancel():
            raise ValidationError(_('Only awaiting-deposit or confirmed bookings that have not started can be cancelled.'))
        paid = self.deposit_state == 'paid' and bool(self.paid_transaction_id)
        free = self.start - fields.Datetime.now() >= timedelta(hours=self.free_cancel_hours)
        kind = ('refund' if free else 'forfeit') if paid else 'none'
        amount = format_amount(self.env, self.currency_id.round(self.paid_amount), self.currency_id)
        text = {
            'refund': _('You will receive a full refund of %s.', amount),
            'forfeit': _('Your %s deposit is non-refundable.', amount),
            'none': _('This booking has no deposit to refund.'),
        }[kind]
        return {'kind': kind, 'text': text, 'exception_allowed': paid and not free}

    def _lock_cancellation(self):
        self.ensure_one()
        self._lock_tables(self.table_id.ids)
        self.env.cr.execute(SQL('SELECT id FROM qclub_booking WHERE id = %s FOR UPDATE', self.id))
        self.env.cr.execute(SQL(
            'SELECT id FROM payment_transaction WHERE qclub_booking_id = %s ORDER BY id FOR UPDATE', self.id))
        self.invalidate_recordset()
        self.env['payment.transaction'].sudo().search([('qclub_booking_id', '=', self.id)]).invalidate_recordset()

    def _cancel_booking(self, exception_refund=False, reason=None):
        """Private service. Website callers authenticate ownership before using sudo."""
        self.ensure_one()
        self.check_access('write')
        self._lock_cancellation()
        if self.state == 'cancelled':
            return False
        outcome = self._cancellation_outcome()
        operator = self.env.user
        if exception_refund:
            if not operator.has_group('qclub_billiard.group_billiard_manager'):
                raise AccessError(_('Only billiard managers can grant exception refunds.'))
            if not outcome['exception_allowed']:
                raise ValidationError(_('Exception refunds are only available inside the cancellation window for a paid deposit.'))
            if not isinstance(reason, str) or not reason.strip():
                raise ValidationError(_('An exception refund reason is required.'))
        # Keep QclubBooking.write: it closes board posts and notifies accepted players (BRD-015).
        super().write({'state': 'cancelled'})
        if outcome['kind'] == 'refund' or exception_refund:
            self._write_deposit({
                'refund_reason': 'Exception refund: ' + reason.strip() if exception_refund else 'Free cancellation',
                'refund_operator_id': operator.id,
            })
            self._request_cancellation_refund()
        elif outcome['kind'] == 'forfeit':
            self._write_deposit({'deposit_state': 'forfeited'})
        note = _('Exception full refund requested.') if exception_refund else outcome['text']
        self.sudo().message_post(body=_('Booking cancelled. %s', note))
        self._queue_cancellation_email()
        return True

    def action_cancel(self):
        if self.env.context.get('qclub_cancel_dialog'):
            return self.action_open_cancel()
        for booking in self:
            booking._cancel_booking()
        return True

    def action_open_cancel(self):
        self.ensure_one()
        self.check_access('write')
        self._cancellation_outcome()
        return {'type': 'ir.actions.act_window', 'res_model': 'qclub.deposit.refund',
                'view_mode': 'form', 'view_id': self.env.ref('qclub_billiard.deposit_cancel_form').id,
                'target': 'new', 'context': {'default_booking_id': self.id, 'default_mode': 'cancel'}}

    def _refund_failed(self):
        new_failure = not self.refund_failure
        self._write_deposit({'deposit_state': 'refund_failed', 'refund_failure': _('Cancellation refund failed; manager review required.')})
        self._refresh_payment_attention()
        if new_failure:
            self.sudo().message_post(body=_('Cancellation refund failed. Please review before retrying.'))
            self._queue_cancellation_email(attention=True)

    def _sync_cancellation_refund(self, tx):
        self.ensure_one()
        if tx != self.sudo().refund_transaction_id:
            return
        if tx.state in ('error', 'cancel'):
            self._refund_failed()
        elif tx.state == 'done':
            if self.deposit_state == 'refunded' and tx.qclub_deposit_processed:
                return
            self._write_deposit({
                'deposit_state': 'refunded', 'refund_amount': self.currency_id.round(-tx.amount),
                'refund_at': fields.Datetime.now(), 'refund_reference': tx.provider_reference or tx.reference,
                'refund_failure': False,
            })
            self._refresh_payment_attention()
            if not tx.qclub_deposit_processed:
                self.sudo().message_post(body=_(
                    'Deposit refunded: %(amount)s. Reason: %(reason)s. Operator: %(operator)s. Reference: %(reference)s.',
                    amount=format_amount(self.env, self.refund_amount, self.currency_id), reason=self.refund_reason,
                    operator=self.refund_operator_id.display_name, reference=self.refund_reference))
                tx.qclub_deposit_processed = True

    def _request_cancellation_refund(self):
        self.ensure_one()
        tx = self.sudo().paid_transaction_id
        if not tx or tx.state != 'done' or tx.currency_id != self.currency_id:
            self._refund_failed()
            return
        children = tx.child_transaction_ids.filtered(lambda child: child.operation == 'refund')
        # Reserve amounts for non-terminal requests as well as successful refunds.
        reserved = self.currency_id.round(-sum(children.filtered(lambda c: c.state not in ('error', 'cancel')).mapped('amount')))
        if self.currency_id.compare_amounts(reserved, tx.amount) >= 0:
            for child in children.filtered(lambda c: c.state == 'done'):
                self._sync_cancellation_refund(child)
            return
        # Partial refunds are outside this task: never request another full refund after one exists.
        if not self.currency_id.is_zero(reserved):
            self._refund_failed()
            return
        try:
            refund = tx._refund(amount_to_refund=self.currency_id.round(tx.amount))
        except Exception:
            # Retain the attempted child and mark the request failed without exposing
            # provider exception text (which may contain sensitive request details).
            children = tx.child_transaction_ids.filtered(lambda c: c.operation == 'refund' and c.id not in children.ids)
            if children:
                child = children[-1]
                if child.state not in ('done', 'error', 'cancel'):
                    child._set_error(_('Cancellation refund request failed.'))
                self._write_deposit({'refund_transaction_id': child.id})
                if child.state == 'done':
                    self._sync_cancellation_refund(child)
                    return
            self._refund_failed()
            return
        self._write_deposit({'refund_transaction_id': refund.id, 'refund_failure': False})
        self._sync_cancellation_refund(refund)
        self._refresh_payment_attention()

    def action_retry_refund(self):
        self.ensure_one()
        if not self.env.user.has_group('qclub_billiard.group_billiard_manager'):
            raise AccessError(_('Only billiard managers can retry refunds.'))
        self.check_access('write')
        self._lock_cancellation()
        if self.state != 'cancelled' or self.deposit_state != 'refund_failed':
            return False
        self._request_cancellation_refund()
        return True

    def _queue_cancellation_email(self, attention=False):
        self.ensure_one()
        config = self._config()
        recipient = config.contact_email if attention else self.partner_id.email
        if self.booking_channel != 'online' or not config.booking_email_from or not recipient:
            return
        try:
            with self.env.cr.savepoint():
                domain = (self.website_id.domain or '').rstrip('/')
                if not domain.startswith(('https://', 'http://')):
                    return
                amount = format_amount(self.env, self.paid_amount, self.currency_id)
                if attention:
                    text = _('Cancellation refund failed. A manager must review and retry the refund.')
                elif self.deposit_state == 'refunded':
                    text = _('Your deposit of %s has been refunded in full.', amount)
                elif self.deposit_state == 'forfeited':
                    text = _('Your %s deposit is non-refundable.', amount)
                elif self.refund_reason:
                    text = _('A full refund of %s has been requested. Our team will follow up if it fails.', amount)
                else:
                    text = _('This booking has no deposit to refund.')
                label = _('Refund failed – payment needs attention') if attention else _('Booking cancelled')
                body = self.env['ir.qweb']._render('qclub_billiard.cancellation_email', {
                    'booking': self, 'config': config, 'domain': domain, 'text': text, 'label': label,
                })
                mail = self.env['mail.mail'].sudo().create({
                    'subject': f'{label}: {self.name}', 'email_from': config.booking_email_from,
                    'email_to': recipient, 'body_html': body, 'auto_delete': False,
                })
                mail.send_after_commit()
        except Exception:
            _logger.exception("Could not queue cancellation email for booking %s", self.id)
