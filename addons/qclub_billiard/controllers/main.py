import re
from datetime import date as calendar_date, timedelta, timezone
from zoneinfo import ZoneInfo

from werkzeug.exceptions import NotFound

from odoo import fields, http
from odoo.http import request

from ..models.qclub_opening_hours import BUSINESS_TZ


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
        today = fields.Datetime.now().replace(tzinfo=timezone.utc).astimezone(ZoneInfo(BUSINESS_TZ)).date()
        return today, today + timedelta(days=config.max_advance_days)

    @http.route("/billiard/booking", type="http", auth="public", website=True, sitemap=False, methods=["GET"])
    def booking_page(self, **kwargs):
        config = self._website_config()
        minimum, maximum = self._date_bounds(config)
        return request.render("qclub_billiard.booking_page", {
            "min_date": minimum.isoformat(), "max_date": maximum.isoformat(),
            "occupancy_requires_login": config.occupancy_requires_login,
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
