from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .qclub_opening_hours import BUSINESS_TZ

ACTIVE_STATES = ("pending", "confirmed", "arrived")
ALLOWED_TRANSITIONS = {
    "pending": {"confirmed", "expired", "cancelled"},
    "confirmed": {"arrived", "cancelled", "no_show"},
    "arrived": {"done"},
}
SNAPSHOT_FIELDS = ("hourly_price", "deposit_ratio", "free_cancel_hours", "no_show_wait_minutes")
DERIVED_FIELDS = ("end", "business_date", "table_fee", "deposit_amount")


class QclubBooking(models.Model):
    _name = "qclub.booking"
    _description = "Billiard Booking"
    _order = "start, id"

    name = fields.Char(required=True, readonly=True, default="New", copy=False)
    table_id = fields.Many2one("qclub.table", required=True, ondelete="restrict", index=True)
    website_id = fields.Many2one(related="table_id.website_id", store=True, index=True)
    partner_id = fields.Many2one("res.partner", string="Customer", required=True, ondelete="restrict")
    start = fields.Datetime(required=True, index=True)
    start_date = fields.Date("Date", compute="_compute_start_parts", readonly=False)
    start_hour = fields.Selection([
        (str(hour), f"{hour % 12 or 12}:00 {'AM' if hour < 12 else 'PM'}") for hour in range(24)
    ], string="Start Time", compute="_compute_start_parts", readonly=False)
    duration_hours = fields.Integer(string="Number of Hours", required=True, default=1)
    end = fields.Datetime(compute="_compute_end", store=True, readonly=True)
    business_date = fields.Date(compute="_compute_business_date", store=True, index=True)
    state = fields.Selection([
        ("pending", "Awaiting Deposit"), ("confirmed", "Confirmed"), ("arrived", "Arrived"),
        ("done", "Completed"), ("cancelled", "Cancelled"), ("expired", "Expired"), ("no_show", "No-show"),
    ], required=True, readonly=True, default="pending", index=True, copy=False)
    lock_expire = fields.Datetime(readonly=True, copy=False)
    hourly_price = fields.Monetary(readonly=True)
    deposit_ratio = fields.Float(string="Deposit Percentage", readonly=True)
    free_cancel_hours = fields.Integer(readonly=True)
    no_show_wait_minutes = fields.Integer(readonly=True)
    currency_id = fields.Many2one(related="website_id.company_id.currency_id")
    table_fee = fields.Monetary(compute="_compute_amounts", store=True)
    deposit_amount = fields.Monetary(compute="_compute_amounts", store=True)

    _name_unique = models.Constraint("UNIQUE(name)", "Booking numbers must be unique.")

    @api.depends("start")
    def _compute_start_parts(self):
        for booking in self:
            if booking.start:
                local = booking.start.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(BUSINESS_TZ))
                booking.start_date = local.date()
                booking.start_hour = str(local.hour)
            else:
                booking.start_date = False
                booking.start_hour = False

    @api.model
    def _first_start_on_date(self, website, day, include_previous=True):
        """Find a future whole hour on a calendar date, using first-fold DST rules."""
        now = fields.Datetime.now()
        today = now.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(BUSINESS_TZ)).date()
        config = self.env["qclub.config"].sudo()._get_for_website(website)
        latest = today + timedelta(days=config.max_advance_days)
        owners = (day - timedelta(days=1), day) if include_previous else (day,)
        intervals = [
            interval for owner in owners if owner <= latest
            for interval in self.env["qclub.opening.hours"]._get_business_intervals(website, owner)
        ]
        candidates = sorted({
            datetime.combine(day, time(hour)).replace(tzinfo=ZoneInfo(BUSINESS_TZ), fold=0)
            .astimezone(timezone.utc).replace(tzinfo=None)
            for hour in range(24)
        })
        for candidate in candidates:
            if candidate > now and any(start <= candidate and candidate + timedelta(hours=1) <= end
                                       for start, end in intervals):
                return candidate
        return False

    @api.model
    def _first_available_start(self, website, from_date=None):
        """Return the earliest future opening hour within the advance booking limit."""
        website.ensure_one()
        today = fields.Datetime.now().replace(tzinfo=timezone.utc).astimezone(ZoneInfo(BUSINESS_TZ)).date()
        config = self.env["qclub.config"].sudo()._get_for_website(website)
        latest = today + timedelta(days=config.max_advance_days)
        day = max(fields.Date.to_date(from_date) if from_date else today, today)
        while day <= latest:
            candidate = self._first_start_on_date(website, day)
            if candidate:
                return candidate
            day += timedelta(days=1)
        return False

    @api.onchange("start_date", "start_hour", "duration_hours", "table_id")
    def _onchange_start_slot(self):
        if not self.table_id or self.state not in ("pending", "confirmed"):
            return
        day, hour = self.start_date, self.start_hour
        message = False
        if day:
            previous_day = (
                self.start.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(BUSINESS_TZ)).date()
                if self.start else False
            )
            if day != previous_day:
                today = fields.Datetime.now().replace(tzinfo=timezone.utc).astimezone(ZoneInfo(BUSINESS_TZ)).date()
                # A future date defaults to its own opening (Saturday 13:00),
                # while today's next hour may belong to yesterday's late session.
                candidate = self._first_start_on_date(self.table_id.website_id, day, include_previous=day == today)
                if candidate:
                    self.start = candidate
                    hour = self.start_hour
                else:
                    message = _("There is no available opening hour on the selected date.")
            if hour is not False:
                self.start = datetime.combine(day, time(int(hour))).replace(
                    tzinfo=ZoneInfo(BUSINESS_TZ), fold=0,
                ).astimezone(timezone.utc).replace(tzinfo=None)
        if self.start:
            if self.start <= fields.Datetime.now():
                message = _("The booking start must be strictly after now.")
            elif self.duration_hours > 0:
                local_day = self.start.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(BUSINESS_TZ)).date()
                end = self.start + timedelta(hours=self.duration_hours)
                if not any(start <= self.start < end <= stop
                           for owner in (local_day - timedelta(days=1), local_day)
                           for start, stop in self.env["qclub.opening.hours"]._get_business_intervals(
                               self.table_id.website_id, owner,
                           )):
                    message = _("The booking must be fully within one business opening interval.")
        if message:
            return {"warning": {"title": _("Booking time"), "message": message}}

    @api.onchange("table_id")
    def _onchange_table_id(self):
        for booking in self:
            if booking._origin.id:
                continue
            table = booking.table_id
            if not table:
                booking.update({field: 0 for field in SNAPSHOT_FIELDS})
                continue
            config = self.env["qclub.config"].sudo()._get_for_website(table.website_id)
            booking.update({
                "hourly_price": table.hourly_price,
                "deposit_ratio": config.deposit_ratio,
                "free_cancel_hours": config.free_cancel_hours,
                "no_show_wait_minutes": config.no_show_wait_minutes,
            })
            if not booking.start:
                booking.start = booking._first_available_start(table.website_id)

    @api.depends("start", "duration_hours")
    def _compute_end(self):
        for booking in self:
            booking.end = booking.start + timedelta(hours=booking.duration_hours) if booking.start else False

    @api.depends("start", "end", "table_id")
    def _compute_business_date(self):
        hours = self.env["qclub.opening.hours"]
        for booking in self:
            booking.business_date = False
            if not booking.start or not booking.end or not booking.table_id:
                continue
            local_day = booking.start.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(BUSINESS_TZ)).date()
            for day in (local_day, local_day - timedelta(days=1)):
                if any(start <= booking.start < booking.end <= end
                       for start, end in hours._get_business_intervals(booking.table_id.website_id, day)):
                    booking.business_date = day
                    break

    @api.depends("hourly_price", "duration_hours", "deposit_ratio", "currency_id")
    def _compute_amounts(self):
        for booking in self:
            booking.table_fee = booking.hourly_price * booking.duration_hours
            amount = booking.table_fee * booking.deposit_ratio / 100
            booking.deposit_amount = booking.currency_id.round(amount) if booking.currency_id else 0

    def _config(self):
        self.ensure_one()
        return self.env["qclub.config"].sudo()._get_for_website(self.website_id)

    def _check_slot(self):
        for booking in self:
            config = booking._config()
            if not 1 <= booking.duration_hours <= config.max_consecutive_hours:
                raise ValidationError(_(
                    "The number of hours must be between 1 and %s.", config.max_consecutive_hours,
                ))
            for instant in (booking.start, booking.end):
                local = instant.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(BUSINESS_TZ))
                if local.minute or local.second or local.microsecond:
                    raise ValidationError(_("Booking start and end must be whole hours in Australia/Adelaide."))
            if not booking.business_date:
                raise ValidationError(_("The booking must be fully within one business opening interval."))
        self._check_conflicts()

    def _check_future(self):
        now = fields.Datetime.now()
        today = now.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(BUSINESS_TZ)).date()
        for booking in self:
            if booking.start <= now:
                raise ValidationError(_("The booking start must be strictly after now."))
            latest = today + timedelta(days=booking._config().max_advance_days)
            if booking.business_date and booking.business_date > latest:
                raise ValidationError(_("The booking is beyond the maximum advance booking date."))

    def _check_conflicts(self):
        for booking in self:
            if booking.state in ACTIVE_STATES and self.sudo().search_count([
                ("id", "!=", booking.id), ("table_id", "=", booking.table_id.id),
                ("state", "in", ACTIVE_STATES), ("start", "<", booking.end), ("end", ">", booking.start),
            ], limit=1):
                raise ValidationError(_("This table is already booked for the selected time."))

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for incoming in vals_list:
            vals = {key: value for key, value in incoming.items() if key not in DERIVED_FIELDS}
            if vals.get("state", "pending") != "pending":
                raise ValidationError(_("New bookings must be awaiting deposit."))
            table = self.env["qclub.table"].browse(vals.get("table_id"))
            table._check_bookable()
            config = self.env["qclub.config"].sudo()._get_for_website(table.website_id)
            vals.update({field: config[field] for field in SNAPSHOT_FIELDS if field != "hourly_price"})
            vals.update({
                "hourly_price": table.hourly_price,
                "state": "pending",
                "lock_expire": fields.Datetime.now() + timedelta(minutes=config.lock_minutes),
                "name": self.env["ir.sequence"].next_by_code("qclub.booking"),
            })
            prepared.append(vals)
        bookings = super().create(prepared)
        bookings._check_slot()
        bookings._check_future()
        return bookings

    def write(self, vals):
        vals = dict(vals)
        if "state" in vals:
            labels = dict(self._fields["state"]._description_selection(self.env))
            for booking in self:
                target = vals["state"]
                if target != booking.state and target not in ALLOWED_TRANSITIONS.get(booking.state, set()):
                    raise ValidationError(_(
                        "Cannot change a booking from %(old)s to %(new)s.",
                        old=labels[booking.state], new=labels.get(target, target),
                    ))
        # Readonly fields must also be protected from direct RPC writes.
        if "lock_expire" in vals or "name" in vals:
            raise ValidationError(_("Booking numbers and lock expiry times cannot be edited directly."))
        if any(field in vals for field in SNAPSHOT_FIELDS):
            raise ValidationError(_("Price and policy snapshots cannot be edited directly."))
        if any(field in vals for field in DERIVED_FIELDS):
            raise ValidationError(_("Booking end, business date and amounts are calculated automatically."))
        if "table_id" in vals:
            table = self.env["qclub.table"].browse(vals["table_id"])
            table._check_bookable()
            for booking in self:
                record_vals = dict(vals)
                if booking.table_id != table:
                    record_vals["hourly_price"] = table.hourly_price
                super(QclubBooking, booking).write(record_vals)
            result = True
        else:
            result = super().write(vals)
        if {"start", "duration_hours", "table_id"}.intersection(vals):
            self._check_slot()
        elif vals.get("state") in ACTIVE_STATES:
            self._check_conflicts()
        if "start" in vals:
            self._check_future()
        return result

    def action_confirm(self):
        return self.write({"state": "confirmed"})

    def action_arrive(self):
        return self.write({"state": "arrived"})

    def action_complete(self):
        return self.write({"state": "done"})

    def action_cancel(self):
        return self.write({"state": "cancelled"})

    def action_no_show(self):
        return self.write({"state": "no_show"})

    def _action_expire(self):
        return self.write({"state": "expired"})

    def unlink(self):
        if not self.env.su:
            raise UserError(_("Bookings cannot be deleted. Cancel them instead."))
        return super().unlink()
