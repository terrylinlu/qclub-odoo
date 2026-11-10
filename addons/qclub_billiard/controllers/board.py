import re
from datetime import date as calendar_date, timedelta

from psycopg2.errors import UniqueViolation
from werkzeug.exceptions import NotFound

from odoo import _, fields, http
from odoo.exceptions import ValidationError
from odoo.http import request

from .main import BilliardBooking
from ..models.qclub_board import COMMUNITY_GUIDELINES, board_display_name, board_posted_label


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

    def _board_action_guard(self):
        """Called after login/CSRF, before any of the four actions validate content."""
        partner = request.env.user.partner_id
        if request.env["qclub.board.ban"].sudo()._is_banned(request.website, partner):
            return {"error": "banned", "message": _("Your account can't post on the board. Please contact Q Club.")}
        since = fields.Datetime.now() - timedelta(seconds=60)
        total = 0
        for model, customer_field in (("qclub.board.post", "partner_id"), ("qclub.board.reply", "partner_id"),
                                      ("qclub.board.application", "partner_id"), ("qclub.board.report", "reporter_id")):
            total += request.env[model].sudo().search_count([
                ("website_id", "=", request.website.id), (customer_field, "=", partner.id),
                ("create_date", ">=", since),
            ])
        if total >= self._board_config().board_rate_limit:
            return {"error": "rate_limit", "message": _("You're doing that too often. Please try again shortly.")}
        return None

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
        return dict(record._summary(request.env.user._is_public()), message=record._customer_message(), hidden=record.hidden,
                    posted_label=board_posted_label(record),
                    state="open" if record._is_open() else "closed",
                    date=record.booking_id.business_date.isoformat(), **self._join_detail(record))

    @http.route("/billiard/booking/post/create", type="jsonrpc", auth="public", website=True, methods=["POST"])
    def create_post(self, booking_id=None, message=None, level=None, players_needed=None,
                    accept_terms=False, csrf_token=None, date=None, **kwargs):
        self._board_config()
        if request.env.user._is_public():
            return {"error": "login_required", "login_url": self._login_url({"date": date, "booking": booking_id})}
        if not isinstance(csrf_token, str) or not request.validate_csrf(csrf_token):
            return {"error": "csrf", "message": _("Your session has expired. Please reload the page.")}
        guard = self._board_action_guard()
        if guard:
            return guard
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

    def _join_detail(self, post):
        public = request.env.user._is_public()
        owner = not public and request.env.user.partner_id == post.partner_id
        applications = request.env["qclub.board.application"].sudo().search([("post_id", "=", post.id)])
        replies = request.env["qclub.board.reply"].sudo().search([("post_id", "=", post.id)])

        def item(application):
            return {"id": application.id, "message": application.message or "", "state": application.state,
                    "display_name": board_display_name(application.partner_id, public),
                    "posted_label": board_posted_label(application)}

        result = {
            "is_owner": owner,
            "replies": [{"id": reply.id, "display_name": "" if reply.hidden else board_display_name(reply.partner_id, public),
                         "posted_label": "" if reply.hidden else board_posted_label(reply),
                         "message": _("This reply was removed.") if reply.hidden else reply.message} for reply in replies],
            "accepted": [{"display_name": board_display_name(application.partner_id, public)}
                         for application in applications if application.state == "accepted"],
            "application": None,
            "terms": COMMUNITY_GUIDELINES, "terms_accepted": False if public else bool(self._terms()),
        }
        if owner:
            result["applications"] = [item(application) for application in applications]
        elif not public:
            own = applications.filtered(lambda application: application.partner_id == request.env.user.partner_id)
            if own:
                result["application"] = item(own[-1])
        return result

    def _join_action(self, operation, post=None, application=None, message=None,
                     action=None, accept_terms=False, csrf_token=None):
        self._board_config()
        if request.env.user._is_public():
            return {"error": "login_required"}
        if not isinstance(csrf_token, str) or not request.validate_csrf(csrf_token):
            return {"error": "csrf", "message": _("Your session has expired. Please reload the page.")}
        if operation in ("reply", "apply"):
            guard = self._board_action_guard()
            if guard:
                return guard
        partner = request.env.user.partner_id
        try:
            with request.env.cr.savepoint():
                if operation in ("reply", "apply"):
                    identifier = positive_id(post)
                    record = request.env["qclub.board.post"].sudo().search([
                        ("id", "=", identifier), ("website_id", "=", request.website.id),
                    ], limit=1) if identifier else None
                    if not record:
                        raise ValidationError(_("This post is unavailable."))
                    if message is None and operation == "apply":
                        message = ""
                    maximum = 500 if operation == "reply" else 200
                    if not isinstance(message, str) or len(message.strip()) > maximum or (
                        operation == "reply" and not message.strip()
                    ):
                        raise ValidationError(_("Please check your message length."))
                    if not self._terms():
                        if accept_terms is not True:
                            raise ValidationError(_("Please agree to the Community Guidelines."))
                        try:
                            with request.env.cr.savepoint():
                                request.env["qclub.board.terms"].sudo().create({
                                    "website_id": request.website.id, "partner_id": partner.id,
                                })
                        except UniqueViolation:
                            pass
                    model = "qclub.board.reply" if operation == "reply" else "qclub.board.application"
                    created = request.env[model].sudo().create({
                        "post_id": record.id, "partner_id": partner.id, "message": message.strip(),
                    })
                    return {"id": created.id}
                identifier = positive_id(application)
                record = request.env["qclub.board.application"].sudo().search([
                    ("id", "=", identifier), ("website_id", "=", request.website.id),
                ], limit=1) if identifier else None
                if not record:
                    raise ValidationError(_("This application is unavailable."))
                if operation == "decide" and action not in ("accept", "decline", "remove"):
                    raise ValidationError(_("This application cannot be changed."))
                record._transition("withdraw" if operation == "withdraw" else action, partner)
                return {"ok": True}
        except UniqueViolation:
            return {"error": "duplicate", "message": _("You have already applied to this post.")}
        except ValidationError as error:
            return {"error": "validation", "message": str(error)}

    @http.route("/billiard/booking/post/reply", type="jsonrpc", auth="public", website=True, methods=["POST"])
    def reply(self, post=None, message=None, accept_terms=False, csrf_token=None, **kwargs):
        return self._join_action("reply", post=post, message=message, accept_terms=accept_terms, csrf_token=csrf_token)

    @http.route("/billiard/booking/post/apply", type="jsonrpc", auth="public", website=True, methods=["POST"])
    def apply(self, post=None, message=None, accept_terms=False, csrf_token=None, **kwargs):
        return self._join_action("apply", post=post, message=message, accept_terms=accept_terms, csrf_token=csrf_token)

    @http.route("/billiard/booking/post/withdraw", type="jsonrpc", auth="public", website=True, methods=["POST"])
    def withdraw(self, application=None, csrf_token=None, **kwargs):
        return self._join_action("withdraw", application=application, csrf_token=csrf_token)

    @http.route("/billiard/booking/application/decide", type="jsonrpc", auth="public", website=True, methods=["POST"])
    def decide(self, application=None, action=None, csrf_token=None, **kwargs):
        return self._join_action("decide", application=application, action=action, csrf_token=csrf_token)

    @http.route("/billiard/booking/post/report", type="jsonrpc", auth="public", website=True, methods=["POST"])
    def report(self, post=None, reply=None, reason=None, note=None, csrf_token=None, **kwargs):
        self._board_config()
        if request.env.user._is_public():
            return {"error": "login_required"}
        if not isinstance(csrf_token, str) or not request.validate_csrf(csrf_token):
            return {"error": "csrf", "message": _("Your session has expired. Please reload the page.")}
        guard = self._board_action_guard()
        if guard:
            return guard
        if (bool(post) == bool(reply) or reason not in ("spam", "abuse", "personal_information", "other")
                or (note is not None and (not isinstance(note, str) or len(note) > 500))):
            return {"error": "validation", "message": _("Please check your report and note (maximum 500 characters).")}
        model = "qclub.board.post" if post else "qclub.board.reply"
        identifier = positive_id(post if post else reply)
        domain = [("id", "=", identifier), ("website_id", "=", request.website.id), ("hidden", "=", False)]
        target = request.env[model].sudo().search(domain, limit=1) if identifier else None
        if not target:
            return {"error": "validation", "message": _("This content is unavailable.")}
        try:
            with request.env.cr.savepoint():
                report = request.env["qclub.board.report"].sudo().create({
                    "website_id": request.website.id, "reporter_id": request.env.user.partner_id.id,
                    "post_id" if post else "reply_id": target.id, "reason": reason, "note": note or "",
                })
                return {"id": report.id}
        except UniqueViolation:
            return {"error": "duplicate", "message": _("You have already reported this content.")}
        except ValidationError as error:
            return {"error": "validation", "message": str(error)}
