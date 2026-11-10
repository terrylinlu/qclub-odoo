"""Read-only customer overview, scoped to the current website and partner."""
from urllib.parse import urlencode

from odoo import _, fields, http
from odoo.http import request

from .main import BilliardBooking
from ..models.qclub_board import board_display_name


class BilliardAccount(BilliardBooking):
    def _own_domain(self):
        return [("website_id", "=", request.website.id),
                ("partner_id", "=", request.env.user.partner_id.id)]

    @http.route("/billiard/booking/reminders", type="jsonrpc", auth="public", website=True, methods=["POST"])
    def reminders(self, **kwargs):
        config = self._website_config()
        if request.env.user._is_public():
            return {"dates": []}
        minimum, maximum = self._date_bounds(config)
        domain = self._own_domain() + [
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
        # Pick the latest fifty first; present upcoming reservations before history.
        bookings = Booking.search(own_domain, order="start desc, id desc", limit=50)
        upcoming = bookings.filtered(lambda booking: booking.start >= now)
        history = bookings.filtered(lambda booking: booking.start < now)
        bookings = sorted(upcoming, key=lambda booking: booking.start) + list(history)
        posts = request.env["qclub.board.post"].sudo().search(own_domain, order="id desc", limit=50)
        applications = request.env["qclub.board.application"].sudo().search(own_domain, order="id desc", limit=50)
        # The relation domains keep the customer predicate even for other authors' replies.
        relevant = site_domain + ["|", "|", ("post_id.partner_id", "=", partner),
                                  ("post_id", "in", request.env["qclub.board.reply"].sudo().search(
                                      own_domain).post_id.ids),
                                  ("post_id", "in", request.env["qclub.board.application"].sudo().search(
                                      own_domain).post_id.ids)]
        replies = request.env["qclub.board.reply"].sudo().search(relevant, order="id desc", limit=50)

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
                "number": booking.name, "time": booking._time_label(), "table": booking.table_id.name,
                "state": booking_labels[booking.state], "url": link(booking, post),
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
                "accepted": Application.search_count(counts + [("state", "=", "accepted")]),
                "needed": post.players_needed,
                "pending": Application.search_count(counts + [("state", "=", "pending")]),
                "url": link(post.booking_id, post),
            })
        return request.render("qclub_billiard.my_billiard", {
            "page_name": "billiard", "bookings": booking_rows, "posts": post_rows,
            "applications": [{"name": board_display_name(item.post_id.partner_id, False),
                              "time": item.post_id.booking_id._time_label(),
                              "table": item.post_id.booking_id.table_id.name,
                              "state": application_labels[item.state],
                              "url": link(item.post_id.booking_id, item.post_id)} for item in applications],
            "messages": [{"name": board_display_name(item.partner_id, False), "message": item.message,
                          "time": item.post_id.booking_id._time_label(),
                          "url": link(item.post_id.booking_id, item.post_id)} for item in replies],
        })
