"""Read-only customer overview, scoped to the current website and partner."""
from urllib.parse import urlencode

from odoo import _, fields, http
from odoo.http import request
from odoo.exceptions import ValidationError
from werkzeug.exceptions import NotFound

from .board import BilliardBoard
from ..models.qclub_board import board_display_name, board_posted_label


ACCOUNT_TABS = ('bookings', 'posts', 'requests', 'messages')
ACCOUNT_PAGE_SIZE = 20


def _account_page_number(value):
    try:
        text = str(value)
        return int(text) if text.isascii() and text.isdecimal() and int(text) > 0 else 1
    except (ValueError, TypeError):
        return 1


def _account_pager(tab, total, page_numbers):
    page = page_numbers[tab]
    page_count = max(1, (total + ACCOUNT_PAGE_SIZE - 1) // ACCOUNT_PAGE_SIZE)

    def link(number):
        params = {f'{key}_page': value for key, value in page_numbers.items()}
        params[f'{tab}_page'] = number
        return '/my/billiard?' + urlencode(params) + '#' + tab

    first = max(1, min(page - 2, page_count - 4))
    numbers = sorted({1, page_count, *range(first, min(first + 5, page_count + 1))})
    links = []
    for number in numbers:
        if links and number - links[-1]['number'] > 1:
            links.append({'number': number - 1, 'url': None})
        links.append({'number': number, 'url': link(number)})
    return {
        'total': total, 'current': page, 'page_count': page_count, 'pages': links,
        'previous': link(page - 1) if page > 1 else None,
        'next': link(page + 1) if page < page_count else None,
        'label': {'bookings': _('My bookings pages'), 'posts': _('My posts pages'),
                  'requests': _('My join requests pages'), 'messages': _('Messages pages')}[tab],
    }


def _status_class(state):
    if state in {"confirmed", "arrived", "open", "accepted"}:
        return "text-bg-success"
    if state in {"pending", "waiting"}:
        return "text-bg-warning"
    return "text-bg-secondary"


class BilliardAccount(BilliardBoard):
    def _own_domain(self):
        return [("website_id", "=", request.website.id),
                ("partner_id", "=", request.env.user.partner_id.id)]

    @http.route("/billiard/booking/reminders", type="jsonrpc", auth="public", website=True, methods=["POST"])
    def reminders(self, **kwargs):
        config = self._website_config()
        # Same visibility as the public occupancy grid; only dates leave the server.
        if config.occupancy_requires_login and request.env.user._is_public():
            return {"dates": []}
        minimum, maximum = self._date_bounds(config)
        domain = [
            ("website_id", "=", request.website.id),
            ("business_date", ">=", minimum), ("business_date", "<=", maximum),
            "|", ("state", "in", ["confirmed", "arrived"]),
            "&", ("state", "=", "pending"), ("lock_expire", ">", fields.Datetime.now()),
        ]
        bookings = request.env["qclub.booking"].sudo().search(domain)
        return {"dates": sorted({booking.business_date.isoformat() for booking in bookings})}

    @http.route("/my/billiard", type="http", auth="public", website=True, sitemap=False, methods=["GET"])
    def my_billiard(self, **kwargs):
        config = self._website_config()
        if request.env.user._is_public():
            return request.redirect("/web/login?" + urlencode({"redirect": "/my/billiard"}))
        own_domain = self._own_domain()
        site_domain = [("website_id", "=", request.website.id)]
        partner = request.env.user.partner_id.id
        now = fields.Datetime.now()
        Booking = request.env["qclub.booking"].sudo()
        page_numbers = {tab: _account_page_number(kwargs.get(f'{tab}_page', 1)) for tab in ACCOUNT_TABS}
        tab_counts = {}

        def page_records(tab, model, domain, upcoming=None, other=None, start_field='start'):
            total = tab_counts[tab] = model.search_count(domain)
            if page_numbers[tab] > max(1, (total + ACCOUNT_PAGE_SIZE - 1) // ACCOUNT_PAGE_SIZE):
                page_numbers[tab] = 1
            offset = (page_numbers[tab] - 1) * ACCOUNT_PAGE_SIZE
            if upcoming is None:
                return model.search(domain, order='create_date desc, id desc',
                                    offset=offset, limit=ACCOUNT_PAGE_SIZE)
            upcoming_count = model.search_count(domain + upcoming)
            records = model.browse()
            if offset < upcoming_count:
                records = model.search(domain + upcoming, order=f'{start_field} asc, id asc',
                                       offset=offset, limit=ACCOUNT_PAGE_SIZE)
            remaining = ACCOUNT_PAGE_SIZE - len(records)
            if remaining:
                records += model.search(domain + other, order=f'{start_field} desc, id desc',
                                        offset=max(0, offset - upcoming_count), limit=remaining)
            return records

        active_states = ['pending', 'confirmed', 'arrived']
        bookings = page_records('bookings', Booking, own_domain,
                                [('start', '>=', now), ('state', 'in', active_states)],
                                ['|', ('start', '<', now), ('state', 'not in', active_states)])
        posts = page_records('posts', request.env['qclub.board.post'].sudo(), own_domain,
                             [('booking_start', '>=', now), ('booking_id.state', '=', 'confirmed'), ('state', '=', 'open')],
                             ['|', '|', ('booking_start', '<', now), ('booking_id.state', '!=', 'confirmed'),
                              ('state', '!=', 'open')], start_field='booking_start')
        applications = page_records('requests', request.env['qclub.board.application'].sudo(), own_domain,
                                    [('booking_start', '>=', now), ('post_id.booking_id.state', '=', 'confirmed'),
                                     ('post_id.state', '=', 'open')],
                                    ['|', '|', ('booking_start', '<', now),
                                     ('post_id.booking_id.state', '!=', 'confirmed'), ('post_id.state', '!=', 'open')],
                                    start_field='booking_start')
        # The relation domains keep the customer predicate even for other authors' replies.
        relevant = site_domain + ["|", "|", ("post_id.partner_id", "=", partner),
                                  ("post_id", "in", request.env["qclub.board.reply"].sudo().search(
                                      own_domain).post_id.ids),
                                  ("post_id", "in", request.env["qclub.board.application"].sudo().search(
                                      own_domain).post_id.ids)]
        replies = page_records('messages', request.env['qclub.board.reply'].sudo(),
                               relevant + [('hidden', '=', False)])
        pagers = {tab: _account_pager(tab, tab_counts[tab], page_numbers) for tab in ACCOUNT_TABS}

        def link(booking, post=None, find=False):
            params = {"date": booking.business_date.isoformat()}
            if post:
                params["post"] = post.id
            elif find:
                params["booking"] = booking.id
            return "/billiard/booking?" + urlencode(params)

        booking_labels = dict(Booking._fields["state"]._description_selection(request.env))
        application_labels = dict(request.env["qclub.board.application"]._fields["state"]._description_selection(request.env))
        booking_rows = []
        for booking in bookings:
            post = request.env["qclub.board.post"].sudo().search(
                site_domain + [("partner_id", "=", partner), ("booking_id", "=", booking.id)], limit=1)
            booking_rows.append({
                "cancel_id": booking.id if booking._can_cancel() else None,
                "number": booking.name, "time": booking._time_label(), "table": booking.table_id.name,
                "state": booking_labels[booking.state], "state_class": _status_class(booking.state), "url": link(booking, post),
                "confirmation": "/billiard/booking/confirmation/" + booking.name,
                "find": link(booking, find=True) if config.online_board and not post
                and booking.state == "confirmed" and booking.start > now else None,
            })
        post_rows = []
        for post in posts:
            counts = site_domain + [("post_id", "=", post.id), ("post_id.partner_id", "=", partner)]
            Application = request.env["qclub.board.application"].sudo()
            post_rows.append({
                "time": post.booking_id._time_label(), "table": post.booking_id.table_id.name,
                "state": _("Open") if post._is_open() else _("Closed"),
                "state_class": _status_class("open" if post._is_open() else "closed"),
                "accepted": Application.search_count(counts + [("state", "=", "accepted")]),
                "posted": board_posted_label(post),
                "needed": post.players_needed, "message": post._customer_message(),
                "pending": Application.search_count(counts + [("state", "=", "pending")]),
                "url": link(post.booking_id, post),
            })
        return request.render("qclub_billiard.my_billiard", {
            "page_name": "billiard", "bookings": booking_rows, "posts": post_rows, "pagers": pagers,
            "applications": [{"name": board_display_name(item.post_id.partner_id, False),
                              "posted": board_posted_label(item),
                          "time": item.post_id.booking_id._time_label(),
                              "table": item.post_id.booking_id.table_id.name,
                              "state": application_labels[item.state],
                              "state_class": _status_class(item.state),
                              "message": item.post_id._customer_message(),
                              "url": link(item.post_id.booking_id, item.post_id)} for item in applications],
            "messages": [{"name": board_display_name(item.partner_id, False), "message": item.message,
                          "posted": board_posted_label(item),
                          "time": item.post_id.booking_id._time_label(),
                          "url": link(item.post_id.booking_id, item.post_id)} for item in replies],
        })

    def _cancellation_booking(self, booking_id):
        self._website_config()
        if request.env.user._is_public():
            raise NotFound()
        booking = request.env['qclub.booking'].sudo().search(
            self._own_domain() + [('id', '=', booking_id)], limit=1)
        if not booking:
            raise NotFound()
        return booking

    @http.route('/billiard/booking/<int:booking_id>/cancel/outcome', type='jsonrpc', auth='public',
                website=True, methods=['POST'])
    def cancellation_outcome(self, booking_id):
        booking = self._cancellation_booking(booking_id)
        return {'text': booking._cancellation_outcome()['text']}

    @http.route('/billiard/booking/<int:booking_id>/cancel/confirm', type='jsonrpc', auth='public',
                website=True, methods=['POST'])
    def cancellation_confirm(self, booking_id, csrf_token=None):
        booking = self._cancellation_booking(booking_id)
        if not isinstance(csrf_token, str) or not request.validate_csrf(csrf_token):
            raise ValidationError(_('Your session has expired. Please reload the page.'))
        # Ownership and website are checked before sudo; no refund choice is accepted.
        booking._cancel_booking()
        return {'cancelled': True}
