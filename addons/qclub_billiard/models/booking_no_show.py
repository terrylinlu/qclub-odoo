import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import SQL
from odoo.tools.misc import format_amount

_logger = logging.getLogger(__name__)
AUDIT_FIELDS = {'no_show_at', 'no_show_revert_reason', 'no_show_revert_operator_id', 'no_show_revert_at'}


class BookingNoShow(models.Model):
    _inherit = 'qclub.booking'

    no_show_at = fields.Datetime(readonly=True, copy=False, index=True)
    no_show_revert_reason = fields.Char(readonly=True, copy=False)
    no_show_revert_operator_id = fields.Many2one('res.users', readonly=True, copy=False)
    no_show_revert_at = fields.Datetime(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if any(AUDIT_FIELDS.intersection(vals) for vals in vals_list):
            raise ValidationError(_('No-show facts cannot be edited directly.'))
        return super().create(vals_list)

    def write(self, vals):
        # Only the audit trail is protected here; the no-show/arrival window rules are
        # enforced by action_arrive()/_mark_no_show() themselves (NS-002/NS-005), the same
        # entry points the UI and the cron use. A plain write() (as other tests' setup code
        # and internal callers already rely on) is intentionally left unrestricted, matching
        # how the base model's write() has always allowed any ALLOWED_TRANSITIONS target.
        if AUDIT_FIELDS.intersection(vals):
            raise ValidationError(_('No-show facts cannot be edited directly.'))
        return super().write(vals)

    def _lock_no_show(self):
        self.check_access('write')
        self._lock_tables(self.table_id.ids)
        for booking in self.sorted('id'):
            self.env.cr.execute(SQL('SELECT id FROM qclub_booking WHERE id = %s FOR UPDATE', booking.id))
        self.invalidate_recordset()

    def _check_arrival_window(self):
        now = fields.Datetime.now()
        for booking in self:
            if booking.state != 'confirmed':
                raise UserError(_('Only confirmed bookings can be marked arrived.'))
            if not (booking.start - timedelta(minutes=30) <= now
                    < booking.start + timedelta(minutes=booking.no_show_wait_minutes)):
                raise UserError(_('Can only mark arrived between 30 minutes before the start time and the no-show cutoff.'))

    def action_arrive(self):
        self._lock_no_show()
        self._check_arrival_window()
        return super().action_arrive()

    @api.model
    def _cron_mark_no_show(self):
        bookings = self.sudo().search([('state', '=', 'confirmed')])
        for booking in bookings:
            try:
                with self.env.cr.savepoint():
                    booking._mark_no_show()
            except Exception:
                _logger.exception('Failed to mark booking %s as no-show', booking.id)

    def _mark_no_show(self):
        self.ensure_one()
        self._lock_no_show()
        now = fields.Datetime.now()
        if self.state != 'confirmed' or self.start + timedelta(minutes=self.no_show_wait_minutes) > now:
            return
        # Keep the normal state write so board closure and conflict handling run.
        super().write({'state': 'no_show'})
        values = {'no_show_at': now}
        if self.deposit_state == 'paid':
            values['deposit_state'] = 'forfeited'
        self._write_deposit(values)
        self._queue_no_show_email()

    def action_revert_no_show(self):
        self.ensure_one()
        self._check_revert_permission()
        if self.state != 'no_show':
            raise UserError(_('Only no-show bookings can be reverted.'))
        return {
            'type': 'ir.actions.act_window', 'res_model': 'qclub.deposit.refund',
            'view_mode': 'form', 'view_id': self.env.ref('qclub_billiard.no_show_revert_form').id,
            'target': 'new', 'context': {'default_booking_id': self.id, 'default_mode': 'no_show_revert'},
        }

    def _check_revert_permission(self):
        if not self.env.user.has_group('qclub_billiard.group_billiard_manager'):
            raise AccessError(_('Only billiard managers can revert a no-show.'))
        self.check_access('write')

    def _revert_no_show(self, reason):
        self.ensure_one()
        self._check_revert_permission()
        if not reason or not reason.strip():
            raise ValidationError(_('A reason is required.'))
        with self.env.cr.savepoint():
            self._lock_no_show()
            if self.state != 'no_show':
                raise UserError(_('Only no-show bookings can be reverted.'))
            # Private exception to BK-010, protected by manager and reason checks.
            # Serialize against new reservations, then enforce the exclusion constraint.
            self._expire_stale_locks(self.table_id.ids)
            self._check_conflicts()
            values = {
                'state': 'arrived', 'no_show_revert_reason': reason.strip(),
                'no_show_revert_operator_id': self.env.uid, 'no_show_revert_at': fields.Datetime.now(),
            }
            if self.deposit_state == 'forfeited':
                values['deposit_state'] = 'paid'
            self._write_deposit(values)
            self.flush_recordset()

    def _queue_no_show_email(self):
        self.ensure_one()
        config = self._config()
        if not self.partner_id.email or not config.booking_email_from:
            return
        try:
            with self.env.cr.savepoint():
                body = self.env['ir.qweb']._render('qclub_billiard.no_show_email', {
                    'booking': self, 'config': config,
                    'amount': format_amount(self.env, self.paid_amount, self.currency_id),
                })
                mail = self.env['mail.mail'].sudo().create({
                    'subject': _('Booking no-show: %s', self.name),
                    'email_from': config.booking_email_from, 'email_to': self.partner_id.email,
                    'body_html': body, 'auto_delete': False,
                })
                mail.send_after_commit()
        except Exception:
            _logger.exception('Could not queue no-show email for booking %s', self.id)
