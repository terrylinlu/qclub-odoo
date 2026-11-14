from datetime import datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from freezegun import freeze_time
from lxml import html
from odoo import Command, fields
from odoo.tests import tagged
from odoo.tools import SQL
from odoo.tools.misc import format_amount
from odoo.tools.safe_eval import safe_eval
from odoo.tests.common import new_test_user
from odoo.addons.payment.tests.http_common import PaymentHttpCommon


@tagged('post_install', '-at_install')
@freeze_time('2026-11-01 00:00:00')
class TestCancelRefundHttp(PaymentHttpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.enable_post_process_patcher = False
        cls.qclub = cls.env['website'].search([('name', '=', 'Q Club')], limit=1)
        cls.aushare = cls.env['website'].search([('name', '=', 'AUSHARE')], limit=1)
        cls.owner = new_test_user(cls.env, login='deposit-owner', password='offline', groups='base.group_portal')
        cls.other = new_test_user(cls.env, login='deposit-other', password='offline', groups='base.group_portal')
        cls.config = cls.env['qclub.config']._get_for_website(cls.qclub)
        cls.config.write({'online_booking': True, 'lock_minutes': 10, 'max_advance_days': 14})
        cls.env['qclub.opening.hours']._load_default_hours(cls.qclub)
        kind = cls.env['qclub.table.type'].create({'name': 'Pay HTTP', 'website_id': cls.qclub.id})
        cls.table = cls.env['qclub.table'].create({'name': 'Pay HTTP', 'type_id': kind.id,
                                                 'website_id': cls.qclub.id, 'hourly_price': 20})
        cls.provider = cls.dummy_provider.copy({
            'company_id': cls.qclub.company_id.id, 'website_id': cls.qclub.id,
            'code': 'none', 'state': 'test', 'is_published': True,
            'payment_method_ids': [Command.set(cls.pm_unknown.ids)],
            'available_currency_ids': [Command.set(cls.qclub.company_id.currency_id.ids)],
        })
        cls.payment_methods = cls.provider.payment_method_ids
        cls.payment_method = cls.payment_methods[:1]
        cls.payment_method_id = cls.payment_method.id
        cls.payment_method_code = cls.payment_method.code
        cls.payment_method.write({'active': True})

    def setUp(self):
        super().setUp()
        self.startPatcher(patch.object(type(self.provider), '_send_api_request',
                                     side_effect=AssertionError('Network forbidden in deposit HTTP tests')))
        self._website(self.qclub)
        self.booking = self.env['qclub.booking'].create({
            'table_id': self.table.id, 'partner_id': self.owner.partner_id.id,
            'start': '2026-11-06 03:30:00', 'duration_hours': 1, 'booking_channel': 'online',
        })
        self.path = '/billiard/booking/confirmation/' + self.booking.name
        self.route = f'/billiard/booking/{self.booking.id}/transaction'
        self.params = {'provider_id': self.provider.id, 'payment_method_id': self.payment_method.id,
                       'token_id': None, 'flow': 'redirect', 'tokenization_requested': False,
                       'landing_route': '/untrusted', 'amount': 1}

    def _website(self, website):
        self.env['website'].search([('domain', '=', self.base_url())]).write({'domain': False})
        self.env.flush_all()
        website.domain = self.base_url()
        self.env.flush_all()
        self.env.registry.clear_cache()
        self.opener.cookies.clear()

    def _call(self, suffix, params=None):
        self.env.flush_all()
        return self.url_open(f'/billiard/booking/{self.booking.id}/cancel/{suffix}', json={
            'jsonrpc': '2.0', 'id': 1, 'method': 'call', 'params': params or {},
        })

    def _token(self):
        page = self.url_open(self.path)
        buttons = html.fromstring(page.content).xpath('//*[contains(@class, "o_qclub_cancel")]')
        self.assertEqual(len(buttons), 1)
        return buttons[0].get('data-csrf-token')

    def _pay(self):
        tx = self.env['payment.transaction'].create({
            'provider_id': self.provider.id, 'payment_method_id': self.payment_method.id,
            'amount': self.booking.deposit_amount, 'currency_id': self.booking.currency_id.id,
            'partner_id': self.owner.partner_id.id, 'operation': 'online_redirect',
            'qclub_booking_id': self.booking.id,
        })
        tx._set_done()
        tx._post_process()
        return tx

    def test_web_009_cancelled_booking_hides_cancellation_window_warning(self):
        self.config.free_cancel_hours = 24
        with freeze_time('2026-11-06 03:00:00'):
            booking = self.env['qclub.booking'].create({
                'table_id': self.table.id, 'partner_id': self.owner.partner_id.id,
                'start': '2026-11-06 04:30:00', 'duration_hours': 1, 'booking_channel': 'online',
            })
            self.assertTrue(booking.created_in_cancel_window)
            self.assertEqual(booking.state, 'pending')
            path = '/billiard/booking/confirmation/' + booking.name
            warning = 'This booking cannot be cancelled free of charge.'
            self.env.flush_all()
            self.authenticate(self.owner.login, 'offline')
            response = self.url_open(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn(warning, html.fromstring(response.content).text_content())

            self.assertTrue(booking._cancel_booking())
            self.assertEqual(booking.state, 'cancelled')
            self.assertTrue(booking.created_in_cancel_window)
            self.env.flush_all()
            response = self.url_open(path)
            self.assertEqual(response.status_code, 200)
            page = html.fromstring(response.content)
            self.assertTrue(page.xpath('//*[@id="wrap"]//p[normalize-space(.)="Cancelled"]'))
            self.assertNotIn(warning, page.text_content())

    def test_rf_007_confirmation_shows_forfeited_deposit(self):
        self._pay()
        self.authenticate(self.owner.login, 'offline')
        with freeze_time(self.booking.start - timedelta(hours=1)):
            token = self._token()
            self.assertTrue(self._call('confirm', {'csrf_token': token}).json()['result']['cancelled'])
            self.booking.invalidate_recordset()
            self.assertEqual(self.booking.deposit_state, 'forfeited')
            response = self.url_open(self.path)
        self.assertEqual(response.status_code, 200)
        amount = format_amount(self.env, self.booking.paid_amount, self.booking.currency_id)
        page = html.fromstring(response.content)
        result = page.xpath('//*[@id="wrap"]//p[normalize-space(.)="Cancelled"]/following-sibling::*[1]')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].tag, 'p')
        self.assertEqual(result[0].text_content(), f'Your {amount} deposit is non-refundable.')

    def test_rf_007_confirmation_shows_refunded_deposit(self):
        tx = self._pay()
        self.authenticate(self.owner.login, 'offline')
        token = self._token()

        def done(refund):
            refund._set_done()

        with patch.object(type(tx), '_send_refund_request', done):
            self.assertTrue(self._call('confirm', {'csrf_token': token}).json()['result']['cancelled'])
        self.booking.invalidate_recordset()
        self.assertEqual(self.booking.deposit_state, 'refunded')
        response = self.url_open(self.path)
        self.assertEqual(response.status_code, 200)
        amount = format_amount(self.env, self.booking.paid_amount, self.booking.currency_id)
        page = html.fromstring(response.content)
        result = page.xpath('//*[@id="wrap"]//p[normalize-space(.)="Cancelled"]/following-sibling::*[1]')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].tag, 'p')
        self.assertEqual(result[0].text_content(), f'Your deposit of {amount} has been refunded in full.')

    def test_rf_003_owner_buttons_and_server_outcomes(self):
        self.authenticate(self.owner.login, 'offline')
        self._token()
        self.assertIn('Cancel booking', self.url_open('/my/billiard').text)
        self.assertEqual(self._call('outcome').json()['result']['text'], 'This booking has no deposit to refund.')
        self._pay()
        text = self._call('outcome').json()['result']['text']
        self.assertIn('You will receive a full refund of', text)
        self.assertIn('10.00', text)
        with freeze_time(self.booking.start - timedelta(hours=1)):
            text = self._call('outcome').json()['result']['text']
            self.assertIn('non-refundable', text)
            self.assertIn('10.00', text)

    def test_rf_003_owner_website_started_and_csrf_guards(self):
        for user in (self.other, None):
            self.authenticate(user.login if user else None, 'offline' if user else None)
            for suffix in ('outcome', 'confirm'):
                response = self._call(suffix)
                self.assertTrue(response.status_code != 200 or 'error' in response.json())
        self.authenticate(self.owner.login, 'offline')
        self.assertIn('error', self._call('confirm', {'csrf_token': 'invalid'}).json())
        token = self._token()
        with freeze_time(self.booking.start):
            self.assertNotIn('o_qclub_cancel', self.url_open(self.path).text)
            for suffix in ('outcome', 'confirm'):
                self.assertIn('error', self._call(suffix, {'csrf_token': token}).json())
        self._website(self.aushare)
        self.authenticate(self.owner.login, 'offline')
        for suffix in ('outcome', 'confirm'):
            self.assertEqual(self._call(suffix).status_code, 404)

    def test_rf_001_rf_003_confirm_double_submit_refunds_once(self):
        tx = self._pay()
        self.authenticate(self.owner.login, 'offline')
        token = self._token()
        def done(refund):
            refund._set_done()
        with patch.object(type(tx), '_send_refund_request', done):
            for _ in range(2):
                self.assertTrue(self._call('confirm', {'csrf_token': token}).json()['result']['cancelled'])
        self.booking.invalidate_recordset()
        tx.invalidate_recordset()
        self.assertEqual(self.booking.state, 'cancelled')
        self.assertEqual(len(tx.child_transaction_ids), 1)
        self.assertEqual(self.booking.deposit_state, 'refunded')
        self.assertNotIn('o_qclub_cancel', self.url_open(self.path).text)

    def test_brd_031_upcoming_bookings_never_hidden(self):
        self.booking.action_confirm()
        Booking = self.env['qclub.booking']
        cancelled = Booking.browse()
        for _ in range(60):
            booking = Booking.create({
                'table_id': self.table.id, 'partner_id': self.owner.partner_id.id,
                'start': self.booking.start + timedelta(hours=1), 'duration_hours': 1,
                'booking_channel': 'backoffice',
            })
            booking.action_cancel()
            cancelled += booking
        self.env.flush_all()
        self.authenticate(self.owner.login, 'offline')
        response = self.url_open('/my/billiard')
        self.assertEqual(response.status_code, 200)
        page = html.fromstring(response.content)
        rows = page.xpath('//*[@id="qclub_my_bookings"]/article')
        self.assertEqual(len(rows), 20)
        self.assertEqual(rows[0].xpath('.//div[contains(@class, "o_qclub_row_heading")]/a/text()'),
                         [self.booking.name])
        self.assertIn('Confirmed', rows[0].text_content())
        self.assertEqual(len(rows[0].xpath('.//button[contains(@class, "o_qclub_cancel")]')), 1)
        other_rows = rows[1:]
        self.assertEqual(len(other_rows), 19)
        self.assertTrue(all('Cancelled' in row.text_content() for row in other_rows))
        expected = list(reversed(cancelled.mapped('name')))[:19]
        self.assertEqual([row.xpath('.//div[contains(@class, "o_qclub_row_heading")]/a/text()')[0]
                          for row in other_rows], expected)
        badge = page.xpath('//*[@id="qclub_tab_bookings"]/span')[0]
        self.assertEqual(int(badge.text_content().strip()), 61)

    def test_brd_031_paging_and_order(self):
        self.config.online_board = True
        self.booking.action_confirm()
        own = self.booking
        own_posts = self.env['qclub.board.post']
        requests = self.env['qclub.board.application']
        messages = self.env['qclub.board.reply']
        other_bookings = self.env['qclub.booking']

        def booking(partner, start, label):
            table = self.table.copy({'name': label})
            record = self.env['qclub.booking'].create({
                'table_id': table.id, 'partner_id': partner.id, 'start': start,
                'duration_hours': 1, 'booking_channel': 'backoffice',
            })
            record.action_confirm()
            return record

        def post(record, label):
            return self.env['qclub.board.post'].create({
                'booking_id': record.id, 'players_needed': 2, 'message': label,
            })

        # Create in reverse time order, so id order cannot accidentally pass the test.
        future = [datetime(2026, 11, 6, 3, 30) + timedelta(days=i // 6, hours=i % 6)
                  for i in range(1, 25)]
        cancelled = []
        for i, start in enumerate(reversed(future)):
            own += booking(self.owner.partner_id, start, f'Own future {i}')
        for i in range(10):
            record = booking(self.owner.partner_id, datetime(2026, 11, 12, 3, 30), f'Own cancelled {i}')
            own += record
            cancelled.append(record)
        for i in range(10):
            own += booking(self.owner.partner_id, datetime(2026, 11, 2, 3, 30) + timedelta(hours=i % 6),
                           f'Own past {i}')
        for i, record in enumerate(own):
            item = post(record, f'Own post {i}')
            own_posts += item
            with freeze_time(datetime(2026, 11, 1, 0, 0) + timedelta(minutes=i)):
                messages += self.env['qclub.board.reply'].create({
                    'post_id': item.id, 'partner_id': self.other.partner_id.id, 'message': f'Message {i:02d}',
                })
        self.env.flush_all()
        # Creation time deliberately runs opposite to id order.
        for i, reply in enumerate(messages):
            self.env.cr.execute(SQL('UPDATE qclub_board_reply SET create_date = %s WHERE id = %s',
                                    datetime(2026, 11, 1) + timedelta(minutes=44 - i), reply.id))
        messages.invalidate_recordset(['create_date'])
        for record in cancelled:
            record.action_cancel()
        for i in reversed(range(25)):
            record = booking(self.other.partner_id,
                             datetime(2026, 11, 7, 3, 30) + timedelta(days=i // 6, hours=i % 6),
                             f'Request table {i}')
            other_bookings += record
            item = post(record, f'Request post {i}')
            requests += self.env['qclub.board.application'].create({
                'post_id': item.id, 'partner_id': self.owner.partner_id.id,
            })
            if i >= 22:
                record.action_cancel()
        private_booking = booking(self.other.partner_id, datetime(2026, 11, 10, 3, 30), 'Private table')
        private_post = post(private_booking, 'PRIVATE unrelated post')
        self.env['qclub.board.reply'].create({
            'post_id': private_post.id, 'partner_id': self.other.partner_id.id,
            'message': 'PRIVATE unrelated reply',
        })
        self.env.flush_all()
        # Creation times oppose id order and booking-time order; pairs also test id ties.
        for records in (own, own_posts, requests):
            for i, record in enumerate(records):
                self.env.cr.execute(SQL('UPDATE %s SET create_date = %s WHERE id = %s',
                                        SQL.identifier(record._table),
                                        datetime(2026, 11, 1) - timedelta(minutes=i // 2), record.id))
            records.invalidate_recordset(['create_date'])
        self.authenticate(self.owner.login, 'offline')
        sections = {'bookings': 'qclub_my_bookings', 'posts': 'qclub_my_posts',
                    'requests': 'qclub_my_applications', 'messages': 'qclub_my_messages'}
        def fetch(query=''):
            response = self.url_open('/my/billiard' + query)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('PRIVATE unrelated', response.text)
            for record in other_bookings | private_booking:
                self.assertNotIn('/confirmation/' + record.name, response.text)
            return html.fromstring(response.content)

        with freeze_time('2026-11-05 00:00:00'):
            now = fields.Datetime.now()
            upcoming = own.filtered(lambda b: b.start >= now and b.state in ('pending', 'confirmed', 'arrived'))
            ordered = upcoming.sorted(lambda b: (b.start, b.id)) + (own - upcoming).sorted(
                lambda b: (b.create_date, b.id), reverse=True)
            open_posts = own_posts.filtered(lambda p: p._is_open())
            ordered_posts = open_posts.sorted(lambda p: (p.booking_id.start, p.id)) + (own_posts - open_posts).sorted(
                lambda p: (p.create_date, p.id), reverse=True)
            open_requests = requests.filtered(lambda r: r.post_id._is_open())
            ordered_requests = open_requests.sorted(lambda r: (r.post_id.booking_id.start, r.id)) + (
                requests - open_requests).sorted(lambda r: (r.create_date, r.id), reverse=True)
            ordered_messages = messages.sorted(lambda r: (r.create_date, r.id), reverse=True)
            expected = {
                'bookings': ordered.mapped('name'), 'posts': ordered_posts.mapped('message'),
                'requests': ordered_requests.mapped('post_id.message'), 'messages': ordered_messages.mapped('message'),
            }
            for page_number in (1, 2, 3):
                doc = fetch('?' + '&'.join(f'{tab}_page={page_number}' for tab in sections))
                for tab, section in sections.items():
                    rows = doc.xpath(f'//*[@id="{section}"]/article')
                    # Requests have 25 rows, so an out-of-range page falls back to page 1.
                    current = page_number if page_number <= (len(expected[tab]) + 19) // 20 else 1
                    wanted = expected[tab][(current - 1) * 20:current * 20]
                    self.assertEqual(len(rows), len(wanted), (tab, page_number))
                    if tab == 'bookings':
                        for row in rows:
                            self.assertIn('Booked on', row.text_content())
                        actual = [row.xpath('.//div[contains(@class, "o_qclub_row_heading")]/a/text()')[0]
                                  for row in rows]
                    else:
                        actual = [row.xpath('.//p[contains(@class, "o_qclub_user_text")]')[0].text_content().strip()
                                  for row in rows]
                    self.assertEqual(actual, wanted, (tab, page_number))
                    badge = doc.xpath(f'//*[@id="qclub_tab_{tab}"]/span')[0]
                    self.assertEqual(int(badge.text_content()), len(expected[tab]))
                    links = doc.xpath(f'//*[@id="{section}"]//nav[contains(@class, "o_qclub_pager")]//a/@href')
                    self.assertTrue(links)
                    for href in links:
                        parts = urlsplit(href)
                        self.assertEqual(parts.fragment, tab)
                        args = parse_qs(parts.query)
                        for other_tab in sections:
                            if other_tab != tab:
                                other_page = page_number if other_tab != 'requests' or page_number < 3 else 1
                                self.assertEqual(args[f'{other_tab}_page'], [str(other_page)])
            for invalid in ('0', '-1', 'bad', '1.5', '999999999999999999999'):
                doc = fetch(f'?bookings_page={invalid}&posts_page=2')
                rows = doc.xpath('//*[@id="qclub_my_bookings"]/article')
                self.assertEqual(len(rows), 20)
                self.assertIn(ordered[0].name, rows[0].text_content())
                self.assertEqual(len(doc.xpath('//*[@id="qclub_my_posts"]/article')), 20)

    def test_adm_002_upcoming_default_filter_and_order(self):
        context = safe_eval(self.env.ref('qclub_billiard.qclub_booking_action').context)
        self.assertEqual(context.get('search_default_upcoming'), 1)
        self.assertFalse(context.get('search_default_active'))
        view = html.fromstring(self.env.ref('qclub_billiard.qclub_booking_view_list').arch_db)
        self.assertEqual(view.get('default_order'), 'start asc')
        view = html.fromstring(self.env.ref('qclub_billiard.qclub_booking_view_search').arch_db)
        node = view.xpath('//filter[@name="upcoming"]')[0]
        self.assertEqual(node.get('string'), 'Upcoming')
        # The browser evaluates datetime.now() in local time, then explicitly converts to UTC.
        self.assertIn('.to_utc()', node.get('domain'))
        now = fields.Datetime.now()
        clock = SimpleNamespace(datetime=SimpleNamespace(now=lambda: SimpleNamespace(to_utc=lambda: now)))
        domain = safe_eval(node.get('domain'), {'datetime': clock})
        self.assertEqual(domain, [('start', '>=', fields.Datetime.to_string(now)),
                                  ('state', 'in', ['pending', 'confirmed', 'arrived'])])
