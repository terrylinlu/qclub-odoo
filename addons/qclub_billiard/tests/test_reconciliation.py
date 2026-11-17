"""ST-003/004, ST-008–012: live business-day reconciliation, no accounting entries."""
from datetime import date, datetime, timedelta
from io import BytesIO
from unittest.mock import patch

from freezegun import freeze_time
from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import HttpCase, tagged
from odoo.tests.common import new_test_user

from ..models.reconciliation import CATEGORIES, business_day_bounds
from .test_cancel_refund import TestCancelRefund


@tagged('post_install', '-at_install')
@freeze_time('2026-11-01 00:00:00')
class TestReconciliation(TestCancelRefund):
    def _report(self, day=date(2026, 11, 6), website=None, user=None):
        return self.env['qclub.reconciliation'].with_user(user or self.staff).create({
            'website_id': (website or self.qclub).id, 'business_date': day,
        })

    def _new_table(self, **values):
        count = self.env['qclub.table'].search_count([])
        return self.table.copy({'name': f'Reconciliation table {count}', **values})

    def _scenario_booking(self, price, hours=1, start='2026-11-06 03:30:00'):
        table = self._new_table(hourly_price=price)
        with freeze_time('2026-11-06 00:00:00'):
            booking = self._book(table_id=table.id, duration_hours=hours, start=start)
            tx = self._tx(booking)
            self._done(tx)
        return booking, tx

    def _settle_booking(self, booking, fee, method):
        with freeze_time(booking.start):
            booking.with_user(self.staff).action_arrive()
            booking.with_user(self.staff)._settle(fee, 'Extra time or discount', method)

    def _scenarios(self):
        first, _ = self._scenario_booking(25, 2)
        self._settle_booking(first, 50, 'eftpos')
        second, tx = self._scenario_booking(20, 2, '2026-11-08 03:30:00')
        with freeze_time('2026-11-06 01:00:00'), patch.object(
                type(tx), '_send_refund_request', lambda refund: self._refund_done(refund)):
            second.action_cancel()
        third, _ = self._scenario_booking(30)
        with freeze_time('2026-11-06 01:00:00'):
            third.action_cancel()
        fourth, _ = self._scenario_booking(25)
        with freeze_time(fourth.start + timedelta(minutes=30)):
            fourth._mark_no_show()
        fifth, _ = self._scenario_booking(20, 2)
        self._settle_booking(fifth, 60, 'cash')
        return first, second, third, fourth, fifth

    def test_st_008_st_012_scenario_totals(self):
        bookings = self._scenarios()
        report = self._report()
        expected = [92.5, 20, 45, 15, 12.5, 25, 40, 0]
        for (category, *_), amount in zip(CATEGORIES, expected, strict=True):
            self.assertEqual(report.currency_id.compare_amounts(report[category], amount), 0, category)
        self.assertEqual(report.settled_fee_total, 110)
        self.assertTrue(report.check1_ok)
        self.assertTrue(report.check2_ok)
        self.assertEqual((report.check1_left, report.check1_right), (0, 0))
        self.assertEqual((report.check2_left, report.check2_right), (110, 110))
        self.assertTrue(bookings[1].cancelled_at)
        self.assertTrue(bookings[2].cancelled_at)
        with self.assertRaises(ValidationError):
            bookings[2].write({'cancelled_at': False})

    def test_st_003_st_004_no_tax_or_accounting_entries(self):
        moves = self.env['account.move'].search_count([])
        payments = self.env['account.payment'].search_count([])
        self._scenarios()
        self.assertTrue(self._report().check2_ok)
        self.assertEqual(self.env['account.move'].search_count([]), moves)
        self.assertEqual(self.env['account.payment'].search_count([]), payments)

    def test_st_008_category_actions(self):
        first, second, third, fourth, fifth = self._scenarios()
        expected = [{b.id for b in (first, second, third, fourth, fifth)}, {second.id},
                    {first.id, fifth.id}, {third.id}, {fourth.id}, {first.id}, {fifth.id},
                    {first.id, fifth.id}]
        report = self._report()
        for (category, *_), ids in zip(CATEGORIES, expected, strict=True):
            action = getattr(report, 'action_view_' + category)()
            self.assertEqual(action['res_model'], 'qclub.booking')
            self.assertEqual(action['view_mode'], 'list,form')
            self.assertEqual(set(self.env['qclub.booking'].search(action['domain']).ids), ids, category)

    def test_st_006_st_010_settlement_shortfall_and_check2(self):
        booking, _ = self._scenario_booking(25)
        self._settle_booking(booking, 10, None)
        report = self._report()
        self.assertEqual(report.settlement_retained, 2.5)
        self.assertEqual((report.check2_left, report.check2_right), (12.5, 12.5))
        self.assertTrue(report.check2_ok)
        original = booking.settle_at
        booking.with_user(self.manager)._settle(30, 'Correct fee', 'cash', correction=True)
        refreshed = self._report()
        self.assertEqual(booking.settle_at, original)
        self.assertEqual(refreshed.settlement_retained, 0)
        self.assertEqual(refreshed.cash, 17.5)
        self.assertTrue(refreshed.check2_ok)

    def test_st_009_business_day_boundary(self):
        for day, length in ((date(2026, 4, 4), 25), (date(2026, 10, 3), 23)):
            lower, upper = business_day_bounds(day)
            self.assertEqual((upper - lower).total_seconds(), length * 3600)
            records = []
            # Exercise both cutoffs, including the exact instant, across both DST changes.
            for instant in (lower - timedelta(seconds=1), lower, upper - timedelta(seconds=1), upper):
                booking = self._book(table_id=self._new_table().id)
                booking._write_deposit({'state': 'confirmed', 'paid_at': instant, 'paid_amount': 10, 'deposit_state': 'paid'})
                records.append(booking)
            report = self._report(day)
            self.assertEqual(report.deposits_received, 20)
            self.assertEqual(report.check1_right, 20)
            self.assertTrue(report.check1_ok)
            ids = self.env['qclub.booking'].search(report.action_view_deposits_received()['domain']).ids
            self.assertEqual(set(ids), {records[1].id, records[2].id})
            # Exact-cutoff exits belong to the following business day as well.
            records[1]._write_deposit({'state': 'cancelled', 'deposit_state': 'forfeited', 'cancelled_at': upper})
            report = self._report(day)
            self.assertEqual(report.cancellation_forfeited, 0)
            self.assertTrue(report.check1_ok)
            following = self._report(day + timedelta(days=1))
            self.assertEqual(following.cancellation_forfeited, 10)
            self.assertTrue(following.check1_ok)

    def test_st_010_check1_independent_cross_check(self):
        booking, _ = self._scenario_booking(25)
        with freeze_time(booking.start + timedelta(minutes=30)):
            booking._mark_no_show()
        before = self._report()
        self.assertEqual(before.no_show_forfeited, 12.5)
        self.assertTrue(before.check1_ok)
        with freeze_time(booking.start + timedelta(minutes=40)):
            booking.with_user(self.manager)._revert_no_show('Customer present')
            booking.with_user(self.staff)._settle(25, None, 'cash')
        report = self._report()
        self.assertEqual(report.no_show_forfeited, 0)
        self.assertEqual(report.deposits_applied, 12.5)
        self.assertEqual((report.check1_left, report.check1_right), (0, 0))
        self.assertTrue(report.check1_ok)
        self.assertTrue(report.check2_ok)

    def test_st_010_unbalanced_checks(self):
        booking, _ = self._scenario_booking(25)
        # Genuine incomplete event facts: refund recorded without a corresponding full deposit exit.
        booking._write_deposit({'refund_amount': 5, 'refund_at': datetime(2026, 11, 6, 1)})
        report = self._report()
        self.assertFalse(report.check1_ok)
        self.assertEqual((report.check1_left, report.check1_right), (7.5, 12.5))
        booking._write_deposit({'state': 'done', 'settle_at': datetime(2026, 11, 6, 2), 'actual_table_fee': 25})
        self.assertFalse(self._report().check2_ok)

    def test_st_011_access_and_website_isolation(self):
        self._scenarios()
        for user in (self.staff, self.manager):
            report = self._report(user=user)
            self.assertEqual(report.deposits_received, 92.5)
            self.assertFalse(report.has_access('write'))
            self.assertFalse(report.has_access('unlink'))
        for user in (self.env.ref('base.public_user'), new_test_user(
                self.env, login='reconciliation-portal', groups='base.group_portal')):
            with self.assertRaises(AccessError), self.env.cr.savepoint():
                self._report(user=user)
        both = new_test_user(self.env, login='reconciliation-both', groups='qclub_billiard.group_billiard_staff',
                             company_id=self.qclub.company_id.id,
                             company_ids=[Command.set((self.qclub.company_id | self.aushare.company_id).ids)])
        kind = self.env['qclub.table.type'].create({'name': 'Other site', 'website_id': self.aushare.id})
        self.env['qclub.opening.hours']._load_default_hours(self.aushare)
        table = self._new_table(website_id=self.aushare.id, type_id=kind.id)
        other_booking = self._book(table_id=table.id, booking_channel='backoffice')
        other_booking._write_deposit({'paid_at': datetime(2026, 11, 6), 'paid_amount': 7, 'deposit_state': 'paid'})
        other = self._report(website=self.aushare, user=both)
        for category, *_ in CATEGORIES:
            expected = 7 if category == 'deposits_received' else 0
            self.assertEqual(other[category], expected)
            action = getattr(other, 'action_view_' + category)()
            ids = set(self.env['qclub.booking'].search(action['domain']).ids)
            self.assertEqual(ids, {other_booking.id} if category == 'deposits_received' else set())
        self.assertEqual(self._report().deposits_received, 92.5)
        outsider = new_test_user(self.env, login='reconciliation-outsider',
                                 groups='qclub_billiard.group_billiard_staff',
                                 company_id=self.aushare.company_id.id,
                                 company_ids=[Command.set(self.aushare.company_id.ids)])
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            self._report(user=outsider)
        with self.assertRaises(AccessError):
            self._report().with_user(outsider).read(['deposits_received'])


@tagged('post_install', '-at_install')
@freeze_time('2026-11-01 00:00:00')
class TestReconciliationHttp(HttpCase):
    def test_st_011_xlsx_export_http(self):
        qclub = self.env['website'].search([('name', '=', 'Q Club')], limit=1)
        aushare = self.env['website'].search([('name', '=', 'AUSHARE')], limit=1)
        staff = new_test_user(self.env, login='reconciliation-http', password='offline',
                              groups='qclub_billiard.group_billiard_staff', company_id=qclub.company_id.id,
                              company_ids=[Command.set(qclub.company_id.ids)])
        portal = new_test_user(self.env, login='reconciliation-http-portal', password='offline',
                               groups='base.group_portal')
        qclub.company_id.currency_id = self.env.ref('base.AUD')
        self.env['qclub.opening.hours']._load_default_hours(qclub)
        kind = self.env['qclub.table.type'].create({'name': 'Export type', 'website_id': qclub.id})
        table = self.env['qclub.table'].create({'name': 'Export table', 'type_id': kind.id,
                                               'website_id': qclub.id, 'hourly_price': 25})
        booking = self.env['qclub.booking'].create({'table_id': table.id, 'partner_id': portal.partner_id.id,
                                                   'start': '2026-11-06 03:30:00', 'duration_hours': 1,
                                                   'booking_channel': 'backoffice'})
        booking.action_confirm()
        booking._write_deposit({'paid_at': datetime(2026, 11, 6), 'paid_amount': 12.5, 'deposit_state': 'paid'})
        with freeze_time(booking.start):
            booking.with_user(staff).action_arrive()
            booking.with_user(staff)._settle(25, None, 'eftpos')
        self.env.flush_all()
        route = f'/billiard/reconciliation/export/xlsx?website_id={qclub.id}&business_date=2026-11-06'
        self.authenticate(None, None)
        self.assertEqual(self.url_open(route).status_code, 403)
        self.authenticate(portal.login, 'offline')
        self.assertEqual(self.url_open(route).status_code, 403)
        self.authenticate(staff.login, 'offline')
        self.assertEqual(self.url_open(route.replace(f'website_id={qclub.id}', f'website_id={aushare.id}')).status_code, 403)
        response = self.url_open(route)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Content-Type'],
                         'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertGreater(len(response.content), 100)
        try:
            import openpyxl
        except ImportError:
            import logging
            logging.getLogger(__name__).warning('Excel 内容未自动核对，人工抽查 (openpyxl unavailable)')
        else:
            workbook = openpyxl.load_workbook(BytesIO(response.content), data_only=True)
            self.assertEqual(workbook.sheetnames, ['Summary', 'Detail'])
            report = self.env['qclub.reconciliation'].with_user(staff).new({
                'website_id': qclub.id, 'business_date': date(2026, 11, 6),
            })
            for row, (category, *_) in enumerate(CATEGORIES, 4):
                self.assertEqual(workbook['Summary'].cell(row, 2).value, report[category])
            self.assertEqual(workbook['Summary'].cell(4, 2).value, 12.5)
            self.assertEqual(workbook['Summary'].cell(6, 2).value, 12.5)
            self.assertEqual(workbook['Summary'].cell(9, 2).value, 12.5)
            self.assertEqual(workbook['Detail'].cell(1, 1).value, 'Booking')
            rows = list(workbook['Detail'].iter_rows(min_row=2, values_only=True))
            self.assertEqual(len(rows), 4)
            self.assertTrue(all(row[0] == booking.name for row in rows))
            self.assertEqual({row[3] for row in rows}, {'Deposits received', 'Deposits applied',
                                                      'On-site EFTPOS', 'Settlement difference retained'})
            self.assertEqual([row[4] for row in rows], [12.5, 12.5, 12.5, 0])
            self.assertTrue(all(isinstance(row[5], datetime) for row in rows))
