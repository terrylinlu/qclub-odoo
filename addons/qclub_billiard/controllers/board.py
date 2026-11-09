import re
from datetime import date as calendar_date

from psycopg2.errors import UniqueViolation
from werkzeug.exceptions import NotFound

from odoo import _, fields, http
from odoo.exceptions import ValidationError
from odoo.http import request

from .main import BilliardBooking
from ..models.qclub_board import COMMUNITY_GUIDELINES


def positive_id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    if not re.fullmatch(r"[1-9][0-9]{0,9}", str(value)):
        return None
    return int(value)


class BilliardBoard(BilliardBooking):
    def _board_config(self):
        config = self._website_config()
        if not config.online_board:
            error = NotFound()
            error.error_response = error.get_response()
            raise error
        return config

    def _board_login_required(self, config):
        return config.board_requires_login and request.env.user._is_public()

    def _own_booking(self, booking):
        identifier = positive_id(booking)
        if not identifier or request.env.user._is_public():
            return request.env["qclub.booking"].sudo().browse()
        return request.env["qclub.booking"].sudo().search([
            ("id", "=", identifier), ("partner_id", "=", request.env.user.partner_id.id),
            ("website_id", "=", request.website.id),
        ], limit=1)

    def _terms(self):
        return request.env["qclub.board.terms"].sudo().search([
            ("website_id", "=", request.website.id), ("partner_id", "=", request.env.user.partner_id.id),
        ], limit=1)

    @http.route("/billiard/booking/board", type="jsonrpc", auth="public", website=True, methods=["POST"])
    def board(self, date=None, **kwargs):
        config = self._board_config()
        if self._board_login_required(config):
            return {"error": "login_required"}
        try:
            if not isinstance(date, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date):
                raise ValueError
            day = calendar_date.fromisoformat(date)
            minimum, maximum = self._date_bounds(config)
            if not day or not minimum <= day <= maximum:
                raise ValueError
        except ValueError:
            return {"error": "invalid_date"}
        public = request.env.user._is_public()
        posts = request.env["qclub.board.post"].sudo().search([
            ("website_id", "=", request.website.id), ("booking_id.business_date", "=", day),
            ("state", "=", "open"), ("booking_id.state", "=", "confirmed"),
            ("booking_id.start", ">", fields.Datetime.now()),
        ], order="id")
        own = []
        if not public:
            bookings = request.env["qclub.booking"].sudo().search([
                ("website_id", "=", request.website.id), ("partner_id", "=", request.env.user.partner_id.id),
                ("business_date", "=", day), ("state", "in", ["pending", "confirmed"]),
                ("start", ">", fields.Datetime.now()),
            ])
            for booking in bookings:
                post = request.env["qclub.board.post"].sudo().search([("booking_id", "=", booking.id)], limit=1)
                own.append({"booking_id": booking.id, "table_id": booking.table_id.id,
                            "start": booking.start.isoformat() + "Z", "hours": booking.duration_hours,
                            "state": booking.state, "post_id": post.id or None,
                            "table_name": booking.table_id.name, "time_label": booking._time_label()})
        return {"posts": [post._summary(public) for post in posts], "own_bookings": own,
                "terms": COMMUNITY_GUIDELINES, "terms_accepted": False if public else bool(self._terms()),
                "max_players": config.board_max_players,
                "date_label": day.strftime("%a %-d %b")}

    @http.route("/billiard/booking/post", type="jsonrpc", auth="public", website=True, methods=["POST"])
    def post(self, post=None, **kwargs):
        config = self._board_config()
        if self._board_login_required(config):
            return {"error": "login_required"}
        identifier = positive_id(post)
        record = request.env["qclub.board.post"].sudo().search([
            ("id", "=", identifier), ("website_id", "=", request.website.id),
        ], limit=1) if identifier else request.env["qclub.board.post"].sudo().browse()
        if not record:
            return {"error": "not_found", "message": _("This post is unavailable.")}
        return dict(record._summary(request.env.user._is_public()), message=record.message,
                    state="open" if record._is_open() else "closed",
                    date=record.booking_id.business_date.isoformat())

    @http.route("/billiard/booking/post/create", type="jsonrpc", auth="public", website=True, methods=["POST"])
    def create_post(self, booking_id=None, message=None, level=None, players_needed=None,
                    accept_terms=False, csrf_token=None, date=None, **kwargs):
        self._board_config()
        if request.env.user._is_public():
            return {"error": "login_required", "login_url": self._login_url({"date": date, "booking": booking_id})}
        if not isinstance(csrf_token, str) or not request.validate_csrf(csrf_token):
            return {"error": "csrf", "message": _("Your session has expired. Please reload the page.")}
        booking = self._own_booking(booking_id)
        if not booking:
            return {"error": "validation", "message": _("This booking is unavailable.")}
        if (not isinstance(message, str) or not message.strip() or len(message.strip()) > 500
                or level not in ("any", "beginner", "intermediate", "advanced")
                or type(players_needed) is not int):
            return {"error": "validation", "message": _("Please check your message, level and number of players.")}
        try:
            with request.env.cr.savepoint():
                request.env.cr.execute("SELECT id FROM qclub_booking WHERE id = %s FOR UPDATE", [booking.id])
                booking.invalidate_recordset(["state", "start"])
                terms = self._terms()
                if not terms and accept_terms is not True:
                    raise ValidationError(_("Please agree to the Community Guidelines."))
                post = request.env["qclub.board.post"].sudo().create({
                    "booking_id": booking.id, "message": message.strip(), "level": level,
                    "players_needed": players_needed,
                })
                if not terms:
                    try:
                        with request.env.cr.savepoint():
                            request.env["qclub.board.terms"].sudo().create({
                                "website_id": request.website.id, "partner_id": request.env.user.partner_id.id,
                            })
                    except UniqueViolation:
                        # Another concurrent first post accepted the same terms.
                        # Keep this post and the original acceptance timestamp.
                        pass
                return {"id": post.id}
        except UniqueViolation:
            return {"error": "duplicate", "message": _("A post already exists for this booking.")}
        except ValidationError as error:
            return {"error": "validation", "message": str(error)}
