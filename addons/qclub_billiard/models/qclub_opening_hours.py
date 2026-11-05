from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

BUSINESS_TZ = "Australia/Adelaide"
WEEKDAYS = [
    ("0", "Monday"), ("1", "Tuesday"), ("2", "Wednesday"), ("3", "Thursday"),
    ("4", "Friday"), ("5", "Saturday"), ("6", "Sunday"),
]


class QclubOpeningHours(models.Model):
    _name = "qclub.opening.hours"
    _description = "Billiard Opening Hours"
    _order = "website_id, weekday, open_hour"

    website_id = fields.Many2one("website", string="Website", required=True, ondelete="cascade", index=True)
    weekday = fields.Selection(WEEKDAYS, required=True)
    open_hour = fields.Integer(string="Opening Hour", required=True)
    close_hour = fields.Integer(string="Closing Hour", required=True)
    open_display = fields.Char(string="Opens", compute="_compute_hour_display")
    close_display = fields.Char(string="Closes", compute="_compute_hour_display")

    _open_hour_range = models.Constraint(
        "CHECK(open_hour >= 0 AND open_hour <= 23)",
        "Opening hour must be between 0 and 23.",
    )
    _close_hour_range = models.Constraint(
        "CHECK(close_hour > open_hour AND close_hour <= open_hour + 24)",
        "Closing hour must be after opening hour and no more than 24 hours later.",
    )

    @api.depends("open_hour", "close_hour")
    def _compute_hour_display(self):
        for hours in self:
            hours.open_display = f"{hours.open_hour:02d}:00"
            hours.close_display = (
                _("%s (+1 day)", f"{hours.close_hour % 24:02d}:00")
                if hours.close_hour >= 24 else f"{hours.close_hour:02d}:00"
            )

    @api.depends("weekday", "open_hour", "close_hour")
    def _compute_display_name(self):
        labels = dict(self._fields["weekday"]._description_selection(self.env))
        for hours in self:
            day = int(hours.weekday or "0")
            hours.display_name = _(
                "%(start_day)s %(start)s – %(end_day)s %(end)s",
                start_day=labels[str(day)], start=f"{hours.open_hour:02d}:00",
                end_day=labels[str((day + hours.close_hour // 24) % 7)],
                end=f"{hours.close_hour % 24:02d}:00",
            )

    @api.constrains("website_id", "weekday", "open_hour", "close_hour")
    def _check_hours(self):
        for hours in self:
            if not 0 <= hours.open_hour <= 23:
                raise ValidationError(_("Opening hour must be between 0 and 23."))
            if not hours.open_hour < hours.close_hour <= hours.open_hour + 24:
                raise ValidationError(_("Closing hour must be after opening hour and no more than 24 hours later."))
            start = int(hours.weekday) * 24 + hours.open_hour
            end = int(hours.weekday) * 24 + hours.close_hour
            others = self.search([("website_id", "=", hours.website_id.id), ("id", "!=", hours.id)])
            for other in others:
                other_start = int(other.weekday) * 24 + other.open_hour
                other_end = int(other.weekday) * 24 + other.close_hour
                if any(start < other_end + shift and other_start + shift < end for shift in (-168, 0, 168)):
                    raise ValidationError(_("Opening hours for the same website must not overlap."))

    @api.model
    def _get_business_intervals(self, website, business_date):
        """Return UTC intervals owned by the local starting date, using first-fold DST rules."""
        website.ensure_one()
        segments = self.sudo().search([
            ("website_id", "=", website.id), ("weekday", "=", str(business_date.weekday())),
        ])
        midnight = datetime.combine(business_date, time())
        tz = ZoneInfo(BUSINESS_TZ)
        return sorted(
            tuple(
                (midnight + timedelta(hours=hour)).replace(tzinfo=tz, fold=0)
                .astimezone(timezone.utc).replace(tzinfo=None)
                for hour in (segment.open_hour, segment.close_hour)
            )
            for segment in segments
        )

    @api.model
    def _load_default_hours(self, website):
        """Load reference hours only for an empty website, with caller permissions."""
        website.ensure_one()
        self.check_access("create")
        hours = self.search([("website_id", "=", website.id)])
        if not hours:
            hours = self.create([
                {"website_id": website.id, "weekday": str(day), "open_hour": opening, "close_hour": closing}
                for day, (opening, closing) in enumerate([
                    (14, 24), (14, 24), (14, 24), (14, 24), (14, 26), (13, 26), (13, 24),
                ])
            ])
        return hours
