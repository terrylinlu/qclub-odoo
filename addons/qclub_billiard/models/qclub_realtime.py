"""Staff notifications and read-only table board projections."""
from datetime import timezone
from zoneinfo import ZoneInfo

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from .qclub_opening_hours import BUSINESS_TZ, business_date_of_utc

ALERT_MESSAGES = {
    'booking_submitted': 'New booking %s awaiting deposit',
    'deposit_confirmed': 'Deposit received for booking %s',
    'cancelled': 'Booking %s cancelled',
    'player_joined': 'New player accepted for booking %s',
}
ALERT_KINDS = frozenset(ALERT_MESSAGES)
CHANNEL_PREFIX = 'qclub.staff:'
ADELAIDE = ZoneInfo(BUSINESS_TZ)
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')


def staff_channel(env, website_id):
    # Explicit tuples bypass bus.bus's automatic database prefixing.
    return (env.cr.dbname, 'qclub.staff', website_id)


def notify_board(env, booking):
    booking.ensure_one()
    env['bus.bus']._sendone(staff_channel(env, booking.website_id.id), 'qclub.board_update', {
        'table_id': booking.table_id.id, 'booking_id': booking.id, 'state': booking.state,
    })


def notify_alert(env, booking, kind):
    booking.ensure_one()
    if kind not in ALERT_KINDS:
        raise ValueError('Unknown staff alert kind')
    env['bus.bus']._sendone(staff_channel(env, booking.website_id.id), 'qclub.alert', {
        'kind': kind, 'booking_id': booking.id, 'booking_name': booking.name,
        'table_name': booking.table_id.name, 'start': booking.start.isoformat(), 'end': booking.end.isoformat(),
    })
    staff = staff_users(env, booking.website_id)
    if staff:
        sentence = ALERT_MESSAGES[kind] % booking.name
        start, end = (_alert_time_label(value) for value in (booking.start, booking.end))
        booking.sudo().with_context(qclub_staff_alert_inbox=True).message_notify(
            partner_ids=staff.partner_id.ids,
            subject=booking.name,
            body=f'{sentence} · {booking.table_id.name} · {start} – {end}',
            author_id=env.ref('base.partner_root').id,
            notify_author=True,
            notify_skip_followers=True,
        )


def _alert_time_label(value):
    local = value.replace(tzinfo=timezone.utc).astimezone(ADELAIDE)
    period = 'am' if local.hour < 12 else 'pm'
    return f'{local.day} {MONTHS[local.month - 1]}, {local.hour % 12 or 12}:{local.minute:02d} {period}'


def staff_users(env, website):
    """Reverse the WebSocket staff and allowed-company checks."""
    group_ids = [env.ref(f'qclub_billiard.group_billiard_{role}').id for role in ('staff', 'manager')]
    domain = [('active', '=', True), ('all_group_ids', 'in', group_ids)]
    if website.company_id:
        domain.append(('company_ids', 'in', website.company_id.ids))
    return env['res.users'].sudo().search(domain)


def staff_websites(env):
    """Use the same company boundary as internal booking record rules."""
    if not env.user.has_group('qclub_billiard.group_billiard_staff'):
        raise AccessError(_('Only billiard staff can access the table board.'))
    return env['website'].sudo().search([
        '|', ('company_id', '=', False), ('company_id', 'in', env.companies.ids),
    ])


class RealtimeTable(models.Model):
    _inherit = 'qclub.table'

    @api.model
    def get_staff_realtime_subscription(self):
        websites = staff_websites(self.env)
        return {
            'channels': [f'{CHANNEL_PREFIX}{website.id}' for website in websites],
            'last_notification_id': self.env['bus.bus'].sudo()._bus_last_id(),
        }

    @api.model
    def get_table_board(self, table_ids=None):
        websites = staff_websites(self.env)
        domain = [('website_id', 'in', websites.ids)]
        if table_ids is not None:
            domain.append(('id', 'in', table_ids))
        tables = self.search(domain)
        now = fields.Datetime.now()
        day = business_date_of_utc(now)
        bookings = self.env['qclub.booking'].search([
            ('table_id', 'in', tables.ids), ('website_id', 'in', websites.ids),
            '|', ('state', '=', 'arrived'),
            '&', ('state', '=', 'confirmed'),
            '&', ('business_date', '=', day), '&', ('start', '<=', now), ('end', '>', now),
        ], order='start, id')
        # An arrived customer remains on the board until staff settle the booking.
        by_table = {}
        for booking in bookings:
            current = by_table.get(booking.table_id.id)
            if not current or booking.state == 'arrived':
                by_table[booking.table_id.id] = booking
        upcoming_by_table = {}
        upcoming = self.env['qclub.booking'].search([
            ('table_id', 'in', tables.ids), ('website_id', 'in', websites.ids),
            ('state', '=', 'confirmed'), ('business_date', '=', day), ('start', '>', now),
        ], order='start')
        for booking in upcoming:
            upcoming_by_table.setdefault(booking.table_id.id, []).append({
                'id': booking.id, 'start': booking.start.isoformat() + 'Z',
                'end': booking.end.isoformat() + 'Z',
            })
        return [{
            'id': table.id, 'name': table.name, 'website_id': table.website_id.id,
            'website_name': table.website_id.name, 'business_date': day.isoformat(),
            'booking': ({'id': booking.id, 'name': booking.name, 'customer': booking.partner_id.name,
                         'end': booking.end.isoformat() + 'Z', 'state': booking.state}
                        if (booking := by_table.get(table.id)) else False),
            'upcoming': upcoming_by_table.get(table.id, []),
        } for table in tables]


class RealtimeWebsocket(models.AbstractModel):
    _inherit = 'ir.websocket'

    def _build_bus_channel_list(self, channels):
        requested = set()
        other_channels = []
        for channel in channels:
            if isinstance(channel, str) and channel.startswith(CHANNEL_PREFIX):
                suffix = channel[len(CHANNEL_PREFIX):]
                if suffix.isdecimal():
                    requested.add(int(suffix))
            else:
                other_channels.append(channel)
        result = super()._build_bus_channel_list(other_channels)
        if requested and self.env.user.has_group('qclub_billiard.group_billiard_staff'):
            # WebSocket requests have no RPC company context. Check against all
            # companies the user may access, never a client-provided company list.
            env = self.env(context=dict(self.env.context, allowed_company_ids=self.env.user.company_ids.ids))
            for website in staff_websites(env):
                if website.id in requested:
                    result.append(staff_channel(env, website.id))
        return result
