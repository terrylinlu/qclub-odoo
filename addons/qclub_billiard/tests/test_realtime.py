"""RT contracts exercise real transitions and mock only the bus transport."""
import json
from datetime import timedelta
from unittest.mock import patch

from freezegun import freeze_time

from odoo.exceptions import AccessError
from odoo.tests import HttpCase, tagged
from odoo.tests.common import new_test_user

from .test_deposit_payment import TestDepositPayment
from ..models import booking_deposit, qclub_booking, qclub_realtime


@tagged('post_install', '-at_install')
@freeze_time('2026-11-01 00:00:00')
class TestRealtime(TestDepositPayment):
    def _messages(self, send, message_type):
        return [args for args, _kwargs in send.call_args_list if args[1] == message_type]

    def test_rt_005_payload_allowlist_and_channel(self):
        booking = self._book()
        with patch.object(type(self.env['bus.bus']), '_sendone') as send:
            qclub_realtime.notify_board(self.env, booking)
            self.assertEqual(send.call_args.args, (
                (self.env.cr.dbname, 'qclub.staff', self.qclub.id), 'qclub.board_update',
                {'table_id': self.table.id, 'booking_id': booking.id, 'state': 'pending'},
            ))
            for kind in qclub_realtime.ALERT_KINDS:
                qclub_realtime.notify_alert(self.env, booking, kind)
                self.assertEqual(send.call_args.args, (
                    (self.env.cr.dbname, 'qclub.staff', self.qclub.id), 'qclub.alert',
                    {'kind': kind, 'booking_id': booking.id, 'booking_name': booking.name,
                     'table_name': self.table.name, 'start': booking.start.isoformat(),
                     'end': booking.end.isoformat()},
                ))
            with self.assertRaises(ValueError):
                qclub_realtime.notify_alert(self.env, booking, 'unknown')

    def _assert_notification_call(self, mock, expected_env, booking, *extra):
        mock.assert_called_once()
        env, record, *args = mock.call_args.args
        # The bus queues messages on the caller’s transaction. The record returned
        # by create() can carry a different context from the caller.
        self.assertIs(env.cr, expected_env.cr)
        self.assertEqual((env.uid, env.su), (expected_env.uid, expected_env.su))
        self.assertEqual((record._name, record.ids), (booking._name, booking.ids))
        self.assertEqual(args, list(extra))
        self.assertFalse(mock.call_args.kwargs)

    def test_rt_004_helpers_receive_online_booking_and_payment_event(self):
        with patch.object(qclub_booking, 'notify_alert') as alert, patch.object(qclub_booking, 'notify_board') as board:
            booking = self._book()
            self._assert_notification_call(alert, self.env, booking, 'booking_submitted')
            self._assert_notification_call(board, self.env, booking)
        with patch.object(booking_deposit, 'notify_alert') as alert, patch.object(booking_deposit, 'notify_board') as board:
            booking._receive_deposit(self._tx(booking))
            self._assert_notification_call(alert, booking.env, booking, 'deposit_confirmed')
            self._assert_notification_call(board, booking.env, booking)
            alert.reset_mock()
            booking._cancel_booking()
            self._assert_notification_call(alert, booking.env, booking, 'cancelled')

    def test_rt_004_submission_payment_cancel_idempotency(self):
        with patch.object(type(self.env['bus.bus']), '_sendone') as send:
            booking = self._book()
            self.assertEqual([m[2]['kind'] for m in self._messages(send, 'qclub.alert')], ['booking_submitted'])
            tx = self._tx(booking)
            self._done(tx)
            tx._post_process()
            self.assertTrue(booking._cancel_booking())
            self.assertFalse(booking._cancel_booking())
            alerts = self._messages(send, 'qclub.alert')
            self.assertEqual([m[2]['kind'] for m in alerts],
                             ['booking_submitted', 'deposit_confirmed', 'cancelled'])
            self.assertTrue(all(m[0] == (self.env.cr.dbname, 'qclub.staff', self.qclub.id) for m in alerts))
            send.reset_mock()
            self._book(booking_channel='backoffice', start='2026-11-06 04:30:00')
            self.assertFalse(self._messages(send, 'qclub.alert'))

    def test_rt_004_player_accepted_once(self):
        booking = self._book()
        booking.action_confirm()
        post = self.env['qclub.board.post'].create({
            'booking_id': booking.id, 'message': 'Join us', 'level': 'intermediate', 'players_needed': 2,
        })
        player = self.env['res.partner'].create({'name': 'RT player'})
        application = self.env['qclub.board.application'].create({'post_id': post.id, 'partner_id': player.id})
        with patch.object(type(self.env['bus.bus']), '_sendone') as send:
            application._transition('accept', booking.partner_id)
            self.assertEqual([m[2]['kind'] for m in self._messages(send, 'qclub.alert')], ['player_joined'])
            self.assertEqual(self._messages(send, 'qclub.alert')[0][2]['booking_id'], booking.id)
            application._transition('remove', booking.partner_id)
            self.assertEqual(len(self._messages(send, 'qclub.alert')), 1)

    def test_rt_002_arrival_settlement_no_show_refresh_without_alert(self):
        booking = self._book(booking_channel='backoffice')
        booking.action_confirm()
        with patch.object(type(self.env['bus.bus']), '_sendone') as send:
            with freeze_time(booking.start):
                booking.with_user(self.staff).action_arrive()
            booking.with_user(self.staff)._settle(booking.table_fee, None, 'cash')
            other = self._book(start='2026-11-06 04:30:00', booking_channel='backoffice')
            other.action_confirm()
            with freeze_time(other.start + timedelta(minutes=30)):
                other._mark_no_show()
                other._mark_no_show()
            states = [m[2]['state'] for m in self._messages(send, 'qclub.board_update')]
            self.assertEqual(states, ['arrived', 'done', 'pending', 'confirmed', 'no_show'])
            self.assertFalse(self._messages(send, 'qclub.alert'))

    def test_rt_002_expiry_slot_move_and_reversal_refresh(self):
        booking = self._book(booking_channel='backoffice')
        replacement = self.env['qclub.table'].create({
            'name': 'RT replacement', 'website_id': self.qclub.id,
            'type_id': self.table.type_id.id, 'hourly_price': 25,
        })
        with patch.object(type(self.env['bus.bus']), '_sendone') as send:
            booking.write({'table_id': replacement.id})
            self.assertEqual([m[2]['table_id'] for m in self._messages(send, 'qclub.board_update')],
                             [self.table.id, replacement.id])
            send.reset_mock()
            booking._action_expire()
            self.assertEqual([m[2]['state'] for m in self._messages(send, 'qclub.board_update')], ['expired'])
            self.assertFalse(self._messages(send, 'qclub.alert'))
        other = self._book(booking_channel='backoffice')
        other.action_confirm()
        with freeze_time(other.start + timedelta(minutes=30)):
            other._mark_no_show()
            with patch.object(type(self.env['bus.bus']), '_sendone') as send:
                other.with_user(self.manager)._revert_no_show('Customer present')
                self.assertEqual([m[2]['state'] for m in self._messages(send, 'qclub.board_update')], ['arrived'])
                self.assertFalse(self._messages(send, 'qclub.alert'))

    def test_rt_001_rt_003_board_current_snapshot_and_incremental_read(self):
        booking = self._book(booking_channel='backoffice')
        booking.action_confirm()
        tables = self.env['qclub.table'].with_user(self.staff)
        with freeze_time(booking.start - timedelta(seconds=1)):
            self.assertFalse(tables.get_table_board([self.table.id])[0]['booking'])
        with freeze_time(booking.start):
            row = tables.get_table_board([self.table.id])[0]
            self.assertEqual(row['booking']['id'], booking.id)
            self.assertEqual(row['booking']['name'], booking.name)
            self.assertEqual(row['booking']['customer'], booking.partner_id.name)
            self.assertEqual(row['booking']['end'], booking.end.isoformat() + 'Z')
            self.assertEqual(row['business_date'], booking.business_date.isoformat())
        with freeze_time(booking.end):
            self.assertFalse(tables.get_table_board([self.table.id])[0]['booking'])
        self.assertEqual(tables.get_table_board([]), [])
        internal = new_test_user(self.env, login='rt-internal', groups='base.group_user')
        with self.assertRaises(AccessError):
            tables.with_user(internal).get_table_board()
        action = self.env.ref('qclub_billiard.qclub_table_board_action')
        self.assertEqual(action.tag, 'qclub_table_board')

    def test_rt_003_overnight_and_dst_snapshot(self):
        for start, now in [('2026-04-04 14:30:00', '2026-04-04 15:00:00'),
                           ('2026-10-03 15:30:00', '2026-10-03 16:00:00')]:
            with freeze_time(start) as clock:
                clock.tick(delta=-timedelta(days=1))
                booking = self._book(start=start, booking_channel='backoffice')
                booking.action_confirm()
            with freeze_time(now):
                row = self.env['qclub.table'].with_user(self.staff).get_table_board([self.table.id])[0]
                self.assertEqual(row['booking']['id'], booking.id)
                self.assertEqual(row['business_date'], booking.business_date.isoformat())

    def test_rt_006_subscription_watermark_does_not_create_history(self):
        model = self.env['qclub.table'].with_user(self.staff)
        before = self.env['bus.bus'].search_count([])
        data = model.get_staff_realtime_subscription()
        self.assertIsInstance(data['last_notification_id'], int)
        self.assertIn(f'qclub.staff:{self.qclub.id}', data['channels'])
        self.assertEqual(self.env['bus.bus'].search_count([]), before)

    def test_rt_007_realtime_independent_of_email_and_rpc_isolation(self):
        self.config.write({'notify_deposit_confirmed': False, 'notify_booking_received': False})
        with patch.object(type(self.env['bus.bus']), '_sendone') as send:
            booking = self._book()
            self._done(self._tx(booking))
            self.assertEqual([m[2]['kind'] for m in self._messages(send, 'qclub.alert')],
                             ['booking_submitted', 'deposit_confirmed'])
        foreign_type = self.env['qclub.table.type'].create({'name': 'RT foreign', 'website_id': self.aushare.id})
        foreign_table = self.env['qclub.table'].create({
            'name': 'RT foreign', 'website_id': self.aushare.id, 'type_id': foreign_type.id, 'hourly_price': 20,
        })
        tables = self.env['qclub.table'].with_user(self.staff)
        self.assertEqual(tables.get_table_board([foreign_table.id]), [])
        with self.assertRaises(AccessError):
            tables.with_context(allowed_company_ids=self.aushare.company_id.ids).get_staff_realtime_subscription()

    def test_rt_007_same_company_rpc_lists_both_websites(self):
        self.aushare.company_id = self.qclub.company_id
        channels = self.env['qclub.table'].with_user(self.staff).get_staff_realtime_subscription()['channels']
        self.assertIn(f'qclub.staff:{self.qclub.id}', channels)
        self.assertIn(f'qclub.staff:{self.aushare.id}', channels)


@tagged('post_install', '-at_install')
class TestRealtimeHttp(HttpCase):
    def test_rt_007_http_subscription_and_poll_enforce_company_boundary(self):
        websites = self.env['website'].search([('name', 'in', ['Q Club', 'AUSHARE'])])
        qclub = websites.filtered(lambda site: site.name == 'Q Club')
        aushare = websites.filtered(lambda site: site.name == 'AUSHARE')
        users = []
        for login, website in [('rt-http-qclub', qclub), ('rt-http-aushare', aushare)]:
            users.append(new_test_user(
                self.env, login=login, password='rt-test', groups='qclub_billiard.group_billiard_staff',
                company_id=website.company_id.id, company_ids=[(6, 0, website.company_id.ids)],
            ))
            self.env['bus.bus'].sudo().create({
                'channel': json.dumps([self.env.cr.dbname, 'qclub.staff', website.id], separators=(',', ':')),
                'message': json.dumps({'type': 'qclub.alert', 'payload': {'booking_name': login}}),
            })
        self.env.flush_all()
        for user, website in zip(users, [qclub, aushare]):
            self.authenticate(user.login, 'rt-test')
            result = self._peek_channels([f'qclub.staff:{site.id}' for site in websites])
            staff_channels = [channel for channel in result['channels'] if channel[1] == 'qclub.staff']
            self.assertEqual(staff_channels, [[self.env.cr.dbname, 'qclub.staff', website.id]])
            alerts = [notification['message']['payload']['booking_name']
                      for notification in result['notifications']
                      if notification['message']['type'] == 'qclub.alert']
            self.assertEqual(alerts, [user.login])

    def _peek_channels(self, channels):
        response = self.url_open('/websocket/peek_notifications', data=json.dumps({
            'jsonrpc': '2.0', 'method': 'call', 'id': 1,
            'params': {'channels': channels, 'last': 0, 'is_first_poll': True},
        }), headers={'Content-Type': 'application/json'})
        body = response.json()
        self.assertNotIn('error', body)
        return body['result']

    def test_rt_007_http_filters_channel_requests_and_supports_same_company(self):
        qclub = self.env['website'].search([('name', '=', 'Q Club')], limit=1)
        aushare = self.env['website'].search([('name', '=', 'AUSHARE')], limit=1)
        aushare.company_id = qclub.company_id
        for group, expected_site_ids in [
            ('base.group_user', set()),
            ('qclub_billiard.group_billiard_staff', {qclub.id, aushare.id}),
        ]:
            user = new_test_user(self.env, login=f'rt-http-{group}', password='rt-test', groups=group,
                                 company_id=qclub.company_id.id, company_ids=[(6, 0, qclub.company_id.ids)])
            self.authenticate(user.login, 'rt-test')
            channels = self._peek_channels([
                f'qclub.staff:{qclub.id}', f'qclub.staff:{aushare.id}', 'qclub.staff:garbage', 'unrelated',
            ])['channels']
            self.assertIn([self.env.cr.dbname, 'unrelated'], channels)
            self.assertFalse(any(isinstance(channel[1], str) and channel[1].startswith('qclub.staff:')
                                 for channel in channels))
            self.assertEqual({channel[2] for channel in channels if channel[1] == 'qclub.staff'}, expected_site_ids)
