from io import BytesIO

from werkzeug.exceptions import BadRequest, Forbidden

from odoo import fields, http
from odoo.http import content_disposition, request
import xlsxwriter

from ..models.qclub_opening_hours import BUSINESS_TZ
from ..models.reconciliation import CATEGORIES, money


class ReconciliationExport(http.Controller):
    @http.route('/billiard/reconciliation/export/xlsx', type='http', auth='public', methods=['GET'])
    def export_xlsx(self, website_id=None, business_date=None, **kwargs):
        user = request.env.user
        if not (user.has_group('qclub_billiard.group_billiard_staff')
                or user.has_group('qclub_billiard.group_billiard_manager')):
            raise Forbidden()
        try:
            website_id = int(website_id)
            day = fields.Date.to_date(business_date)
            if not day:
                raise ValueError()
        except (TypeError, ValueError):
            raise BadRequest('Invalid website or business date') from None
        website = request.env['website'].search([
            ('id', '=', website_id), ('company_id', 'in', request.env.companies.ids),
        ], limit=1)
        if not website:
            raise Forbidden()
        report = request.env['qclub.reconciliation'].new({'website_id': website.id, 'business_date': day})
        report._check_report_access()
        output = BytesIO()
        # Explicit strings and disabled formula/URL interpretation protect user-supplied names.
        with xlsxwriter.Workbook(output, {'in_memory': True, 'strings_to_formulas': False,
                                          'strings_to_urls': False}) as workbook:
            amount_format = workbook.add_format({'num_format': '"$"#,##0.00'})
            date_format = workbook.add_format({'num_format': 'yyyy-mm-dd hh:mm:ss'})
            summary = workbook.add_worksheet('Summary')
            summary.set_column(0, 0, 55)
            summary.set_column(1, 2, 20)
            summary.write_row(0, 0, ['Website', website.name])
            summary.write_row(1, 0, ['Business date', str(day), 'Currency', report.currency_id.name])
            summary.write_row(2, 0, ['Category', 'Amount'])
            for row, (category, label, *_) in enumerate(CATEGORIES, 3):
                summary.write(row, 0, label)
                summary.write_number(row, 1, report[category], amount_format)
            summary.write_row(12, 0, ['Self-check', 'Left', 'Right', 'Balanced'])
            for row, index in enumerate((1, 2), 13):
                summary.write(row, 0, 'Deposit net change' if index == 1 else 'Settlement balance')
                summary.write_number(row, 1, report[f'check{index}_left'], amount_format)
                summary.write_number(row, 2, report[f'check{index}_right'], amount_format)
                summary.write_boolean(row, 3, report[f'check{index}_ok'])
            detail = workbook.add_worksheet('Detail')
            detail.write_row(0, 0, ['Booking', 'Table', 'Customer', 'Category', 'Amount',
                                    f'Event time ({BUSINESS_TZ})'])
            detail.set_column(0, 3, 28)
            detail.set_column(4, 4, 18)
            detail.set_column(5, 5, 27)
            row = 1
            for category, label, event, amount, _ in CATEGORIES:
                bookings = request.env['qclub.booking'].search(report._category_domain(category), order=f'{event}, id')
                for booking in bookings:
                    value = money(booking[amount]) if amount else max(
                        money(booking.paid_amount) - money(booking.actual_table_fee), 0)
                    detail.write_row(row, 0, [booking.name, booking.table_id.name, booking.partner_id.name, label])
                    detail.write_number(row, 4, float(value), amount_format)
                    local_time = fields.Datetime.context_timestamp(report.with_context(tz=BUSINESS_TZ), booking[event])
                    detail.write_datetime(row, 5, local_time.replace(tzinfo=None), date_format)
                    row += 1
            detail.freeze_panes(1, 0)
            detail.autofilter(0, 0, max(row - 1, 1), 5)
        return request.make_response(output.getvalue(), headers=[
            ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Disposition', content_disposition(f'reconciliation-{website.id}-{day}.xlsx')),
        ])
