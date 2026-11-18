"""Read-only, live reconciliation of booking facts; no accounting entries."""
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from .qclub_opening_hours import BUSINESS_DAY_CUTOFF, BUSINESS_TZ, business_today

# field, label, event timestamp, amount field, additional domain
CATEGORIES = (
    ('deposits_received', 'Deposits received', 'paid_at', 'paid_amount', ()),
    ('deposits_refunded', 'Deposits refunded', 'refund_at', 'refund_amount', ()),
    ('deposits_applied', 'Deposits applied', 'settle_at', 'paid_amount', (('deposit_state', '=', 'applied'),)),
    ('cancellation_forfeited', 'Cancellation forfeitures', 'cancelled_at', 'paid_amount',
     (('state', '=', 'cancelled'), ('deposit_state', '=', 'forfeited'))),
    ('no_show_forfeited', 'No-show forfeitures', 'no_show_at', 'paid_amount',
     (('state', '=', 'no_show'), ('deposit_state', '=', 'forfeited'))),
    ('eftpos', 'On-site EFTPOS', 'settle_at', 'balance_amount', (('balance_method', '=', 'eftpos'),)),
    ('cash', 'On-site cash', 'settle_at', 'balance_amount', (('balance_method', '=', 'cash'),)),
    ('settlement_retained', 'Settlement difference retained', 'settle_at', None, (('state', '=', 'done'),)),
)


def business_day_bounds(business_date):
    """Adelaide 06:00 to next 06:00, localized separately for 23/25-hour DST days."""
    return tuple(
        datetime.combine(business_date + timedelta(days=offset), time(BUSINESS_DAY_CUTOFF))
        .replace(tzinfo=ZoneInfo(BUSINESS_TZ)).astimezone(timezone.utc).replace(tzinfo=None)
        for offset in (0, 1)
    )


def money(value):
    return Decimal(str(value or 0))


class QclubReconciliation(models.TransientModel):
    _name = 'qclub.reconciliation'
    _description = 'Daily Reconciliation'

    website_id = fields.Many2one('website', required=True)
    business_date = fields.Date(required=True, default=lambda self: business_today())
    company_id = fields.Many2one(related='website_id.company_id')
    currency_id = fields.Many2one(related='company_id.currency_id')
    deposits_received = fields.Monetary(compute='_compute_totals')
    deposits_refunded = fields.Monetary(compute='_compute_totals')
    deposits_applied = fields.Monetary(compute='_compute_totals')
    cancellation_forfeited = fields.Monetary(compute='_compute_totals')
    no_show_forfeited = fields.Monetary(compute='_compute_totals')
    eftpos = fields.Monetary(compute='_compute_totals')
    cash = fields.Monetary(compute='_compute_totals')
    settlement_retained = fields.Monetary(compute='_compute_totals')
    settled_fee_total = fields.Monetary(compute='_compute_totals')
    check1_ok = fields.Boolean(compute='_compute_totals')
    check2_ok = fields.Boolean(compute='_compute_totals')
    check1_left = fields.Monetary(compute='_compute_totals')
    check1_right = fields.Monetary(compute='_compute_totals')
    check2_left = fields.Monetary(compute='_compute_totals')
    check2_right = fields.Monetary(compute='_compute_totals')

    @api.depends_context('lang')
    def _compute_display_name(self):
        for report in self:
            report.display_name = _("Daily Reconciliation")

    def _check_report_access(self):
        self.ensure_one()
        user = self.env.user
        if not (user.has_group('qclub_billiard.group_billiard_staff')
                or user.has_group('qclub_billiard.group_billiard_manager')):
            raise AccessError(_('Only billiard staff and managers can view reconciliation.'))
        if self.website_id.company_id not in self.env.companies:
            raise AccessError(_('The website must belong to an allowed company.'))

    def _category_domain(self, category, bounds=None):
        self.ensure_one()
        self._check_report_access()
        _, _, event, _, filters = next(item for item in CATEGORIES if item[0] == category)
        lower, upper = bounds or business_day_bounds(self.business_date)
        return [('website_id', '=', self.website_id.id), (event, '>=', lower), (event, '<', upper), *filters]

    @api.depends('website_id', 'business_date')
    def _compute_totals(self):
        Booking = self.env['qclub.booking']
        for report in self:
            if not report.website_id or not report.business_date:
                for name in [item[0] for item in CATEGORIES] + [
                        'settled_fee_total', 'check1_left', 'check1_right', 'check2_left', 'check2_right',
                        'check1_ok', 'check2_ok']:
                    report[name] = False
                continue
            report._check_report_access()
            bounds = business_day_bounds(report.business_date)
            totals = {}
            # ORM SQL aggregates enforce booking ACLs and record rules, with no sudo.
            for category, _label, _event, amount, _filters in CATEGORIES:
                domain = report._category_domain(category, bounds)
                if amount:
                    rows = Booking._read_group(domain, aggregates=[amount + ':sum'])
                    totals[category] = money(rows[0][0])
                else:
                    rows = Booking._read_group(domain, ['id'], ['paid_amount:sum', 'actual_table_fee:sum'])
                    totals[category] = sum((max(money(paid) - money(fee), Decimal(0))
                                            for _, paid, fee in rows), Decimal(0))
                report[category] = totals[category]
            fees = Booking._read_group(report._category_domain('settlement_retained', bounds),
                                       aggregates=['actual_table_fee:sum'])[0][0]
            report.settled_fee_total = fees or 0
            left1 = totals['deposits_received'] - sum(
                (totals[key] for key in ('deposits_refunded', 'deposits_applied',
                                        'cancellation_forfeited', 'no_show_forfeited')), Decimal(0))
            # Independent path: current booking states determine exit times. Strict entry
            # and inclusive exit implement outstanding immediately BEFORE each cutoff.
            outstanding = [Decimal(0), Decimal(0)]
            for booking in Booking.search([('website_id', '=', report.website_id.id), ('paid_at', '!=', False)]):
                exit_at = False
                if booking.deposit_state == 'refunded':
                    exit_at = booking.refund_at
                elif booking.deposit_state == 'applied':
                    exit_at = booking.settle_at
                elif booking.deposit_state == 'forfeited':
                    if booking.state == 'cancelled':
                        exit_at = booking.cancelled_at
                    elif booking.state == 'no_show':
                        exit_at = booking.no_show_at
                for index, cutoff in enumerate(bounds):
                    if booking.paid_at < cutoff and (not exit_at or exit_at >= cutoff):
                        outstanding[index] += money(booking.paid_amount)
            report.check1_left = left1
            report.check1_right = outstanding[1] - outstanding[0]
            report.check2_left = money(fees) + totals['settlement_retained']
            report.check2_right = totals['deposits_applied'] + totals['eftpos'] + totals['cash']
            report.check1_ok = report.currency_id.compare_amounts(report.check1_left, report.check1_right) == 0
            report.check2_ok = report.currency_id.compare_amounts(report.check2_left, report.check2_right) == 0

    def _category_action(self, category):
        self.ensure_one()
        label = next(item[1] for item in CATEGORIES if item[0] == category)
        return {'type': 'ir.actions.act_window', 'res_model': 'qclub.booking', 'view_mode': 'list,form',
                'domain': self._category_domain(category), 'name': _(label),
                'context': {'search_default_upcoming': 0}}

    def action_view_deposits_received(self):
        return self._category_action('deposits_received')

    def action_view_deposits_refunded(self):
        return self._category_action('deposits_refunded')

    def action_view_deposits_applied(self):
        return self._category_action('deposits_applied')

    def action_view_cancellation_forfeited(self):
        return self._category_action('cancellation_forfeited')

    def action_view_no_show_forfeited(self):
        return self._category_action('no_show_forfeited')

    def action_view_eftpos(self):
        return self._category_action('eftpos')

    def action_view_cash(self):
        return self._category_action('cash')

    def action_view_settlement_retained(self):
        return self._category_action('settlement_retained')

    def action_export_xlsx(self):
        self.ensure_one()
        self._check_report_access()
        return {'type': 'ir.actions.act_url', 'target': 'download',
                'url': '/billiard/reconciliation/export/xlsx?website_id=%s&business_date=%s'
                       % (self.website_id.id, self.business_date)}
