import re
from datetime import date as calendar_date, timedelta
from urllib.parse import urlencode

from werkzeug.exceptions import NotFound

from odoo import _, fields, http
from odoo.exceptions import ValidationError
from odoo.http import request

from ..models.qclub_booking import BookingConflict
from ..models.qclub_opening_hours import business_today


class BilliardBooking(http.Controller):
    def _website_config(self):
        config = request.env["qclub.config"].sudo().search([
            ("website_id", "=", request.website.id), ("online_booking", "=", True),
        ], limit=1)
        if not config:
            error = NotFound()
            # Odoo normally wraps JSON-RPC exceptions in HTTP 200. Preserve the
            # actual HTTP 404 for this website gate, including the JSON-RPC route.
            error.error_response = error.get_response()
            raise error
        return config

    def _date_bounds(self, config):
        today = business_today()
        return today, today + timedelta(days=config.max_advance_days)

    @http.route("/billiard/booking", type="http", auth="public", website=True, sitemap=False, methods=["GET"])
    def booking_page(self, **kwargs):
        config = self._website_config()
        minimum, maximum = self._date_bounds(config)
        selected_date = kwargs.get("date", "")
        try:
            restored_day = calendar_date.fromisoformat(selected_date)
            if not minimum <= restored_day <= maximum:
                raise ValueError
            selected_date = restored_day.isoformat()
        except (TypeError, ValueError):
            selected_date = minimum.isoformat()
        return request.render("qclub_billiard.booking_page", {
            "selected_date": selected_date, "csrf_token": request.csrf_token(),
            "max_hours": config.max_consecutive_hours,
            "login_url": self._login_url(kwargs) if kwargs else "/web/login?redirect=/billiard/booking",
            "min_date": minimum.isoformat(), "max_date": maximum.isoformat(),
            "occupancy_requires_login": config.occupancy_requires_login,
            "board_enabled": config.online_board,
            "show_grid_prices": config.show_grid_prices,
            "board_post": self._board_parameter(kwargs.get("post")),
            "board_booking": self._board_parameter(kwargs.get("booking")),
            "is_public": request.env.user._is_public(),
            "login_required": config.occupancy_requires_login and request.env.user._is_public(),
        })

    @http.route("/billiard/booking/occupancy", type="jsonrpc", auth="public", website=True, methods=["POST"])
    def occupancy(self, date=None, **kwargs):
        config = self._website_config()
        if config.occupancy_requires_login and request.env.user._is_public():
            return {"error": "login_required"}
        if not isinstance(date, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date):
            return {"error": "invalid_date"}
        try:
            business_date = calendar_date.fromisoformat(date)
        except ValueError:
            return {"error": "invalid_date"}
        minimum, maximum = self._date_bounds(config)
        if not minimum <= business_date <= maximum:
            return {"error": "invalid_date"}
        return request.env["qclub.booking"]._get_occupancy(request.website, business_date)

    def _board_parameter(self, value):
        if isinstance(value, (str, int)) and not isinstance(value, bool) and re.fullmatch(r"[1-9][0-9]{0,9}", str(value)):
            return str(value)
        return ""

    def _login_url(self, values):
        params = {key: values[key] for key in ("date", "table", "start", "hours") if values.get(key)}
        for key in ("post", "booking"):
            value = self._board_parameter(values.get(key))
            if value:
                params[key] = value
        if any(key in params for key in ("post", "booking")) and "date" in params:
            try:
                day = calendar_date.fromisoformat(params["date"])
                minimum, maximum = self._date_bounds(self._website_config())
                if not minimum <= day <= maximum:
                    raise ValueError
                params["date"] = day.isoformat()
            except (TypeError, ValueError):
                params.pop("date", None)
        target = "/billiard/booking?" + urlencode(params)
        return "/web/login?" + urlencode({"redirect": target})

    @http.route("/billiard/booking/quote", type="jsonrpc", auth="public", website=True, methods=["POST"])
    def quote(self, table=None, start=None, hours=None, **kwargs):
        config = self._website_config()
        if config.occupancy_requires_login and request.env.user._is_public():
            return {"error": "login_required"}
        return self._online_result(table, start, hours)

    def _online_result(self, table, start, hours, submit=False):
        Booking = request.env["qclub.booking"].sudo()
        try:
            with request.env.cr.savepoint():
                result = Booking._quote_online(request.website, table, start, hours)
                if submit:
                    booking = Booking.create({
                        "table_id": table, "start": start.replace("T", " ").removesuffix("Z"),
                        "duration_hours": hours, "partner_id": request.env.user.partner_id.id,
                        "booking_channel": "online",
                    })
                    booking._queue_booking_email()
                    result.update({"confirmation_url": "/billiard/booking/confirmation/" + booking.name,
                                   "time_label": booking._time_label()})
                return result
        except BookingConflict as error:
            if error.booking:
                booking = error.booking
                return {"error": "own_hold",
                        "message": _("You already hold this time slot (%s, awaiting deposit).", booking.name),
                        "confirmation_url": "/billiard/booking/confirmation/" + booking.name}
            config = self._website_config()
            return {"error": "conflict", "message":
                    _("This time slot has just been taken. Please choose another.") + "\n" +
                    _("Slots awaiting a deposit are released automatically if not paid within %s minutes.",
                      config.lock_minutes)}
        except ValidationError as error:
            return {"error": "validation", "message": str(error)}

    @http.route("/billiard/booking/submit", type="jsonrpc", auth="public", website=True, methods=["POST"])
    def submit(self, table=None, start=None, hours=None, csrf_token=None, date=None, **kwargs):
        self._website_config()
        if request.env.user._is_public():
            return {"error": "login_required", "login_url": self._login_url({
                "date": date, "table": table, "start": start, "hours": hours,
            })}
        if not isinstance(csrf_token, str) or not request.validate_csrf(csrf_token):
            return {"error": "csrf", "message": _("Your session has expired. Please reload the page.")}
        return self._online_result(table, start, hours, submit=True)

    @http.route("/billiard/booking/confirmation/<string:name>", type="http", auth="public",
                website=True, sitemap=False, methods=["GET"])
    def confirmation(self, name, **kwargs):
        self._website_config()
        if request.env.user._is_public():
            raise NotFound()
        booking = request.env["qclub.booking"].sudo().search([
            ("name", "=", name), ("website_id", "=", request.website.id),
            ("partner_id", "=", request.env.user.partner_id.id),
        ], limit=1)
        if not booking:
            raise NotFound()
        config = self._website_config()
        find_players = (config.online_board and booking.state == "confirmed"
                        and booking.start > fields.Datetime.now()
                        and not request.env["qclub.board.post"].sudo().search_count([("booking_id", "=", booking.id)]))
        return request.render("qclub_billiard.booking_confirmation", {
            "find_players_url": "/billiard/booking?" + urlencode({"date": booking.business_date.isoformat(), "booking": booking.id}) if find_players else False,
            "booking": booking, "time_label": booking._time_label(),
            "remaining": max(0, int((booking.lock_expire - fields.Datetime.now()).total_seconds()))
            if booking.state == "pending" and booking.lock_expire else 0,
        })
