import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from psycopg2.errors import ExclusionViolation

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import SQL

from .qclub_opening_hours import BUSINESS_DAY_CUTOFF, BUSINESS_TZ, business_date_of_utc, business_today

_logger = logging.getLogger(__name__)

# Stable signed int32 namespace ("QCLB"); never use Python's randomized hash().
TABLE_LOCK_NAMESPACE = 0x51434C42
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
        (str(hour % 24), f"{hour % 12 or 12}:00 {'AM' if hour % 24 < 12 else 'PM'}"
         + (" (next day)" if hour >= 24 else ""))
        for hour in range(BUSINESS_DAY_CUTOFF, 24 + BUSINESS_DAY_CUTOFF)
    ], string="Start Time", compute="_compute_start_parts", readonly=False)
    duration_hours = fields.Integer(string="Number of Hours", required=True, default=1)
    end = fields.Datetime(compute="_compute_end", store=True, readonly=True, precompute=True)
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

    def init(self):
        super().init()
        self.env.cr.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
        # Let PostgreSQL canonicalize the expected definition using the same column
        # types. Comparing deparsed definitions avoids fragile cast/whitespace checks.
        definition = SQL("""
            EXCLUDE USING gist (table_id WITH =, tsrange(start, "end", '[)') WITH &&)
            WHERE (state IN %s)
        """, ACTIVE_STATES)
        with self.env.cr.savepoint():
            self.env.cr.execute("""
                CREATE TEMP TABLE qclub_booking_overlap_definition
                (LIKE qclub_booking) ON COMMIT DROP
            """)
            self.env.cr.execute(SQL(
                "ALTER TABLE qclub_booking_overlap_definition "
                "ADD CONSTRAINT qclub_booking_no_overlap %s", definition,
            ))
            self.env.cr.execute("""
                SELECT pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE conname = 'qclub_booking_no_overlap'
                  AND conrelid = 'pg_temp.qclub_booking_overlap_definition'::regclass
            """)
            expected = self.env.cr.fetchone()[0]
            self.env.cr.execute("""
                SELECT pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE conname = 'qclub_booking_no_overlap'
                  AND conrelid = 'qclub_booking'::regclass
            """)
            existing = self.env.cr.fetchone()
            if existing and existing[0] != expected:
                self.env.cr.execute("ALTER TABLE qclub_booking DROP CONSTRAINT qclub_booking_no_overlap")
                existing = None
            if not existing:
                # btree_gist is provisioned by the database environment.
                self.env.cr.execute(SQL(
                    "ALTER TABLE qclub_booking ADD CONSTRAINT qclub_booking_no_overlap %s", definition,
                ))
            self.env.cr.execute("DROP TABLE pg_temp.qclub_booking_overlap_definition")

    @api.model
    def _get_occupancy(self, website, business_date):
        """Read-only public projection: no booking identifiers or customer fields."""
        website.ensure_one()
        now = fields.Datetime.now()
        tz = ZoneInfo(BUSINESS_TZ)
        today = business_today()
        config = self.env["qclub.config"].sudo().search([("website_id", "=", website.id)], limit=1)
        intervals = self.env["qclub.opening.hours"]._get_business_intervals(website, business_date)
        starts = []
        for start, end in intervals:
            while start + timedelta(hours=1) <= end:
                starts.append(start)
                start += timedelta(hours=1)
        slots = []
        for start in starts:
            local = start.replace(tzinfo=timezone.utc).astimezone(tz)
            slots.append({
                "start": start.isoformat(timespec="seconds") + "Z",
                "label": f"{local.hour % 12 or 12}:00 {'AM' if local.hour < 12 else 'PM'}",
                "next_day": local.date() > business_date,
            })
        tables = self.env["qclub.table"].sudo().search_read(
            [("website_id", "=", website.id), ("active", "=", True)],
            ["name", "type_id", "hourly_price"], order="sequence, name, id",
        )
        by_table = {table["id"]: [] for table in tables}
        if starts and tables:
            bookings = self.sudo().search_read([
                ("website_id", "=", website.id), ("table_id", "in", list(by_table)),
                ("state", "in", ACTIVE_STATES),
                ("start", "<", starts[-1] + timedelta(hours=1)), ("end", ">", starts[0]),
            ], ["table_id", "start", "end", "state", "lock_expire"], load=None)
            for booking in bookings:
                lock_expire = fields.Datetime.to_datetime(booking["lock_expire"])
                if booking["state"] == "pending" and lock_expire and lock_expire <= now:
                    continue
                by_table[booking["table_id"]].append((
                    fields.Datetime.to_datetime(booking["start"]), fields.Datetime.to_datetime(booking["end"]),
                ))
        rows = []
        for table in tables:
            states = []
            for start in starts:
                if start <= now:
                    state = "past"
                elif any(a < start + timedelta(hours=1) and b > start for a, b in by_table[table["id"]]):
                    state = "occupied"
                else:
                    state = "free"
                states.append(state)
            rows.append({
                "id": table["id"], "name": table["name"], "type": table["type_id"][1],
                "hourly_price": table["hourly_price"], "slots": states,
            })
        return {
            "business_date": business_date.isoformat(),
            "available_dates": {"min": today.isoformat(), "max": (today + timedelta(
                days=config.max_advance_days,
            )).isoformat()},
            "currency": website.sudo().company_id.currency_id.name,
            "slots": slots, "tables": rows,
        }

    @api.model
    def _cron_expire_pending(self):
        bookings = self.sudo().search([
            ("state", "=", "pending"), ("lock_expire", "<=", fields.Datetime.now()),
        ])
        expired = self.sudo().browse()
        for booking in bookings:
            try:
                with self.env.cr.savepoint():
                    booking._action_expire()
                expired |= booking
            except Exception:
                _logger.exception("Failed to expire unpaid booking %s", booking.id)
        return expired

    @api.model
    def _lock_tables(self, table_ids):
        """Serialize changes to each table until this transaction ends."""
        for table_id in sorted(set(table_ids)):
            self.env.cr.execute(
                "SELECT pg_advisory_xact_lock(%s, %s)", (TABLE_LOCK_NAMESPACE, table_id),
            )

    @api.model
    def _expire_stale_locks(self, table_ids):
        if table_ids:
            bookings = self.sudo().search([
                ("table_id", "in", list(table_ids)), ("state", "=", "pending"),
                ("lock_expire", "<=", fields.Datetime.now()),
            ])
            for booking in bookings:
                booking._action_expire()

    @api.depends("start")
    def _compute_start_parts(self):
        for booking in self:
            if booking.start:
                local = booking.start.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(BUSINESS_TZ))
                booking.start_date = business_date_of_utc(booking.start)
                booking.start_hour = str(local.hour)
            else:
                booking.start_date = False
                booking.start_hour = False

    @api.model
    def _first_start_on_date(self, website, day):
        """Find a future whole hour on a business date, using first-fold DST rules."""
        now = fields.Datetime.now()
        today = business_today()
        config = self.env["qclub.config"].sudo()._get_for_website(website)
        if not today <= day <= today + timedelta(days=config.max_advance_days):
            return False
        intervals = self.env["qclub.opening.hours"]._get_business_intervals(website, day)
        candidates = sorted({
            (datetime.combine(day, time()) + timedelta(hours=hour))
            .replace(tzinfo=ZoneInfo(BUSINESS_TZ), fold=0)
            .astimezone(timezone.utc).replace(tzinfo=None)
            for hour in range(BUSINESS_DAY_CUTOFF, 24 + BUSINESS_DAY_CUTOFF)
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
        today = business_today()
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
            previous_day = business_date_of_utc(self.start) if self.start else False
            if day != previous_day:
                current_start = False
                if hour is not False:
                    calendar_day = day + timedelta(days=int(hour) < BUSINESS_DAY_CUTOFF)
                    current_start = datetime.combine(calendar_day, time(int(hour))).replace(
                        tzinfo=ZoneInfo(BUSINESS_TZ), fold=0,
                    ).astimezone(timezone.utc).replace(tzinfo=None)
                intervals = self.env["qclub.opening.hours"]._get_business_intervals(
                    self.table_id.website_id, day,
                )
                if not (current_start and current_start > fields.Datetime.now()
                        and self.duration_hours > 0
                        and any(start <= current_start < current_start + timedelta(
                            hours=self.duration_hours,
                        ) <= stop for start, stop in intervals)):
                    candidate = self._first_start_on_date(self.table_id.website_id, day)
                    if candidate:
                        labels = dict(self._fields["start_hour"]._description_selection(self.env))
                        old_hour = hour
                        self.start = candidate
                        hour = self.start_hour
                        if old_hour is not False:
                            message = _(
                                "Start Time changed to %(new)s: %(old)s is not available on this date.",
                                new=labels[hour], old=labels[old_hour],
                            )
                    else:
                        message = _("There is no available opening hour on the selected date.")
            if hour is not False:
                calendar_day = day + timedelta(days=int(hour) < BUSINESS_DAY_CUTOFF)
                self.start = datetime.combine(calendar_day, time(int(hour))).replace(
                    tzinfo=ZoneInfo(BUSINESS_TZ), fold=0,
                ).astimezone(timezone.utc).replace(tzinfo=None)
        if self.start and not message:
            if self.start <= fields.Datetime.now():
                message = _("The booking start must be strictly after now.")
            elif self.duration_hours > 0:
                owner = business_date_of_utc(self.start)
                end = self.start + timedelta(hours=self.duration_hours)
                if not any(start <= self.start < end <= stop
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
        for booking in self:
            booking.business_date = business_date_of_utc(booking.start) if booking.start else False

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
            if not any(start <= booking.start < booking.end <= end
                       for start, end in self.env["qclub.opening.hours"]._get_business_intervals(
                           booking.website_id, business_date_of_utc(booking.start),
                       )):
                raise ValidationError(_("The booking must be fully within one business opening interval."))
        self._check_conflicts()

    def _check_future(self):
        now = fields.Datetime.now()
        today = business_today()
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
                raise ValidationError(_(
                    "This table is already booked for the selected time. Please choose another time or table."
                ))

    @api.model_create_multi
    def create(self, vals_list):
        self.check_access("create")
        try:
            with self.env.cr.savepoint():
                table_ids = {vals["table_id"] for vals in vals_list if vals.get("table_id")}
                self._lock_tables(table_ids)
                self._expire_stale_locks(table_ids)
                prepared = []
                for incoming in vals_list:
                    vals = {key: value for key, value in incoming.items() if key not in DERIVED_FIELDS}
                    if vals.get("state", "pending") != "pending":
                        raise ValidationError(_("New bookings must be awaiting deposit."))
                    table = self.env["qclub.table"].browse(vals.get("table_id"))
                    table._check_bookable()
                    config = self.env["qclub.config"].sudo()._get_for_website(table.website_id)
                    # Validate before precomputing end: a negative duration would
                    # otherwise reach PostgreSQL as an invalid (reversed) range.
                    duration = vals.get("duration_hours") if "duration_hours" in vals else self.default_get(
                        ["duration_hours"],
                    ).get("duration_hours", 0)
                    duration = self._fields["duration_hours"].convert_to_cache(duration, self)
                    if not 1 <= duration <= config.max_consecutive_hours:
                        raise ValidationError(_(
                            "The number of hours must be between 1 and %s.", config.max_consecutive_hours,
                        ))
                    vals["duration_hours"] = duration
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
                bookings.flush_recordset()
                return bookings
        except ExclusionViolation as error:
            raise ValidationError(_(
                "This table is already booked for the selected time. Please choose another time or table."
            )) from error

    def write(self, vals):
        self.check_access("write")
        vals = dict(vals)
        # Readonly fields must also be protected from direct RPC writes.
        if "lock_expire" in vals or "name" in vals:
            raise ValidationError(_("Booking numbers and lock expiry times cannot be edited directly."))
        if any(field in vals for field in SNAPSHOT_FIELDS):
            raise ValidationError(_("Price and policy snapshots cannot be edited directly."))
        if any(field in vals for field in DERIVED_FIELDS):
            raise ValidationError(_("Booking end, business date and amounts are calculated automatically."))
        try:
            with self.env.cr.savepoint():
                slot_changed = bool({"start", "duration_hours", "table_id"}.intersection(vals))
                if slot_changed or vals.get("state") in ACTIVE_STATES:
                    table_ids = set(self.table_id.ids)
                    if vals.get("table_id"):
                        table_ids.add(vals["table_id"])
                    self._lock_tables(table_ids)
                    if slot_changed:
                        self._expire_stale_locks(table_ids)
                if "state" in vals:
                    labels = dict(self._fields["state"]._description_selection(self.env))
                    for booking in self:
                        target = vals["state"]
                        if target != booking.state and target not in ALLOWED_TRANSITIONS.get(booking.state, set()):
                            raise ValidationError(_(
                                "Cannot change a booking from %(old)s to %(new)s.",
                                old=labels[booking.state], new=labels.get(target, target),
                            ))
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
                self.flush_recordset()
                return result
        except ExclusionViolation as error:
            raise ValidationError(_(
                "This table is already booked for the selected time. Please choose another time or table."
            )) from error

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
