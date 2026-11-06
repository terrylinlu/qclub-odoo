from datetime import date, datetime
from decimal import Decimal
from xml.etree import ElementTree

from freezegun import freeze_time
from psycopg2.errors import UniqueViolation

from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form
from odoo.tests.common import tagged
from odoo.tools import mute_logger

from .common import BilliardCase


@tagged("post_install", "-at_install")
@freeze_time("2026-06-01 00:00:00")
class TestBooking(BilliardCase):
    def setUp(self):
        super().setUp()
        self.Booking = self.env["qclub.booking"]
        self.Hours = self.env["qclub.opening.hours"]
        self.Hours.search([("website_id", "=", self.qclub.id)]).unlink()
        self.Hours._load_default_hours(self.qclub)
        self.config = self.env["qclub.config"]._get_for_website(self.qclub)
        self.config.write({
            "deposit_ratio": 50, "free_cancel_hours": 24, "no_show_wait_minutes": 30,
            "lock_minutes": 10, "max_consecutive_hours": 4, "max_advance_days": 14,
        })
        self.kind = self._make_type("Booking test type")
        self.table, self.other_table = self.env["qclub.table"].create([
            {"name": name, "type_id": self.kind.id, "website_id": self.qclub.id, "hourly_price": 25}
            for name in ("Booking table A", "Booking table B")
        ])
        self.partner = self.env["res.partner"].create({"name": "Booking customer"})
        self.qclub.company_id.currency_id = self.env.ref("base.AUD")

    def _book(self, **values):
        return self.Booking.create(dict({
            "table_id": self.table.id, "partner_id": self.partner.id,
            "start": "2026-06-01 04:30:00", "duration_hours": 1,
        }, **values))

    def _reject(self, **values):
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._book(**values)

    def test_bk_003_form_defaults_to_next_business_hour(self):
        cases = (
            ("2026-06-01 01:30:00", date(2026, 6, 1), "14", datetime(2026, 6, 1, 4, 30)),
            ("2026-06-01 05:50:00", date(2026, 6, 1), "16", datetime(2026, 6, 1, 6, 30)),
            ("2026-06-01 14:00:00", date(2026, 6, 2), "14", datetime(2026, 6, 2, 4, 30)),
        )
        for now, day, hour, expected in cases:
            with self.subTest(now=now), freeze_time(now):
                form = Form(self.Booking.with_user(self.staff), view="qclub_billiard.qclub_booking_view_form")
                form.table_id = self.table
                form.partner_id = self.partner
                self.assertEqual((form.start_date, form.start_hour), (day, hour))
                booking = form.save()
                self.assertEqual(booking.start, expected)
                booking.action_cancel()

    def test_bk_002_form_date_defaults_and_overnight_business_date(self):
        form = Form(self.Booking.with_user(self.staff), view="qclub_billiard.qclub_booking_view_form")
        form.table_id = self.table
        form.partner_id = self.partner
        form.start_date = date(2026, 6, 5)
        self.assertEqual(form.start_hour, "14")
        form.start_hour = "1"
        booking = form.save()
        self.assertEqual(booking.start, datetime(2026, 6, 5, 15, 30))
        self.assertEqual(booking.end, datetime(2026, 6, 5, 16, 30))
        self.assertEqual(booking.business_date, date(2026, 6, 5))

    def test_bk_001_hour_selection_has_24_whole_hours(self):
        selection = self.Booking._fields["start_hour"]._description_selection(self.env)
        self.assertEqual(selection, [
            ("6", "6:00 AM"), ("7", "7:00 AM"),
            ("8", "8:00 AM"), ("9", "9:00 AM"), ("10", "10:00 AM"), ("11", "11:00 AM"),
            ("12", "12:00 PM"), ("13", "1:00 PM"), ("14", "2:00 PM"), ("15", "3:00 PM"),
            ("16", "4:00 PM"), ("17", "5:00 PM"), ("18", "6:00 PM"), ("19", "7:00 PM"),
            ("20", "8:00 PM"), ("21", "9:00 PM"), ("22", "10:00 PM"), ("23", "11:00 PM"),
            ("0", "12:00 AM (next day)"), ("1", "1:00 AM (next day)"),
            ("2", "2:00 AM (next day)"), ("3", "3:00 AM (next day)"),
            ("4", "4:00 AM (next day)"), ("5", "5:00 AM (next day)"),
        ])

    def test_bk_002_outside_hours_warns_and_save_still_rejects(self):
        form = Form(self.Booking.with_user(self.staff), view="qclub_billiard.qclub_booking_view_form")
        form.table_id = self.table
        form.partner_id = self.partner
        form.start_hour = "13"
        self.assertEqual(form.start_date, date(2026, 6, 1))
        self.assertEqual(form.start_hour, "13")
        preview = self.Booking.with_user(self.staff).new({
            "state": "pending", "table_id": self.table.id, "start": datetime(2026, 6, 1, 3, 30), "duration_hours": 1,
        })
        self.assertIn("warning", preview._onchange_start_slot())
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            form.save()

    def test_bk_003_past_hour_and_duration_overrun_warn(self):
        preview = self.Booking.with_user(self.staff).new({
            "state": "pending", "table_id": self.table.id, "start": datetime(2026, 6, 1, 13, 30), "duration_hours": 2,
        })
        self.assertIn("warning", preview._onchange_start_slot())
        preview.duration_hours = 1
        with freeze_time("2026-06-01 13:30:00"):
            self.assertIn("warning", preview._onchange_start_slot())

    def test_bk_002_closed_date_keeps_date_and_warns(self):
        self.Hours.search([("website_id", "=", self.qclub.id), ("weekday", "=", "2")]).unlink()
        form = Form(self.Booking.with_user(self.staff), view="qclub_billiard.qclub_booking_view_form")
        form.table_id = self.table
        form.partner_id = self.partner
        form.start_date = date(2026, 6, 3)
        self.assertEqual((form.start_date, form.start_hour), (date(2026, 6, 3), "14"))
        preview = self.Booking.with_user(self.staff).new({
            "state": "pending", "table_id": self.table.id, "start": datetime(2026, 6, 1, 4, 30), "duration_hours": 1,
        })
        preview.start_date = date(2026, 6, 3)
        self.assertIn("warning", preview._onchange_start_slot())
        self.assertEqual(preview.start_date, date(2026, 6, 3))
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            form.save()

    def test_bk_003_first_start_includes_previous_business_day_and_limit(self):
        with freeze_time("2026-06-05 15:00:00"):
            self.assertEqual(self.Booking._first_available_start(self.qclub), datetime(2026, 6, 5, 15, 30))
        self.Hours.search([("website_id", "=", self.qclub.id)]).unlink()
        self.assertFalse(self.Booking._first_available_start(self.qclub))
        self.Hours.create({"website_id": self.qclub.id, "weekday": "1", "open_hour": 14, "close_hour": 24})
        self.config.max_advance_days = 0
        self.assertFalse(self.Booking._first_available_start(self.qclub))
        self.assertFalse(self.Booking._first_available_start(self.qclub, date(2026, 6, 16)))

    def test_bk_003_saved_form_date_change_updates_start(self):
        for state in ("pending", "confirmed"):
            with self.subTest(state=state):
                booking = self._book()
                if state == "confirmed":
                    booking.action_confirm()
                form = Form(booking.with_user(self.staff), view="qclub_billiard.qclub_booking_view_form")
                form.start_date = date(2026, 6, 6)
                self.assertEqual(form.start_hour, "13")
                form.start_hour = "15"
                saved = form.save()
                self.assertEqual(saved.start, datetime(2026, 6, 6, 5, 30))
                saved.action_cancel()

    def test_bk_001_local_hours_and_duration_bounds(self):
        for start in ("2026-06-01 05:00:00", "2026-06-01 04:31:00", "2026-06-01 04:30:01"):
            self._reject(start=start)
        for duration in (0, -1, 5):
            self._reject(duration_hours=duration)
        booking = self._book(duration_hours=4)
        self.assertEqual(booking.end, datetime(2026, 6, 1, 8, 30))
        booking.action_cancel()
        self.assertEqual(self._book().duration_hours, 1)

    def test_bk_002_business_hours_and_midnight(self):
        self._reject(start="2026-06-01 03:30:00")
        self._reject(start="2026-06-01 13:30:00", duration_hours=2)
        booking = self._book(start="2026-06-05 13:30:00", duration_hours=2)
        self.assertEqual(booking.end, datetime(2026, 6, 5, 15, 30))
        self.assertEqual(booking.business_date, date(2026, 6, 5))
        self.Hours.search([("website_id", "=", self.qclub.id), ("weekday", "=", "0")]).unlink()
        self._reject()
        self.Hours.create([
            {"website_id": self.qclub.id, "weekday": "0", "open_hour": opening, "close_hour": closing}
            for opening, closing in ((14, 16), (17, 20))
        ])
        self._reject(start="2026-06-01 05:30:00", duration_hours=3)

    def test_bk_002_dst_transition_business_date(self):
        self.config.max_advance_days = 400
        for start, end, business_day in (
            ("2026-10-03 14:30:00", datetime(2026, 10, 3, 16, 30), date(2026, 10, 3)),
            ("2027-04-03 13:30:00", datetime(2027, 4, 3, 15, 30), date(2027, 4, 3)),
        ):
            booking = self._book(start=start, duration_hours=2)
            self.assertEqual(booking.end, end)
            self.assertEqual(booking.business_date, business_day)
            self._reject(start=start, duration_hours=2)

    def test_bk_003_future_and_advance_boundary(self):
        self._reject(start="2026-05-31 04:30:00")
        self._book(start="2026-06-15 04:30:00")
        self._reject(start="2026-06-16 04:30:00")
        # Advance limits use the owning business day, including after midnight.
        self.config.max_advance_days = 4
        late = self._book(start="2026-06-05 15:30:00")
        self.assertEqual(late.business_date, date(2026, 6, 5))
        self.config.max_advance_days = 14
        with freeze_time("2026-06-01 04:30:00"):
            self._reject()
        booking = self._book()
        with freeze_time("2026-06-01 06:30:00"):
            booking.action_confirm()
            booking.action_arrive()
            booking.duration_hours = 3
            with self.assertRaises(ValidationError), self.env.cr.savepoint():
                booking.write({"start": "2026-06-01 04:30:00"})

    def test_bk_006_overlap_adjacency_and_different_tables(self):
        booking = self._book(duration_hours=2)
        for method in (None, "action_confirm", "action_arrive"):
            if method:
                getattr(booking, method)()
            self._reject(start="2026-06-01 05:30:00")
        self._book(table_id=self.other_table.id)
        self._book(start="2026-06-01 06:30:00")
        with self.assertRaisesRegex(ValidationError, "already booked"), self.env.cr.savepoint():
            booking.write({"duration_hours": 3})

    def test_bk_006_all_inactive_states_release_slot(self):
        for path in (
            ("action_cancel",), ("_action_expire",),
            ("action_confirm", "action_no_show"),
            ("action_confirm", "action_arrive", "action_complete"),
        ):
            booking = self._book()
            for method in path:
                getattr(booking, method)()
            replacement = self._book()
            replacement.action_cancel()

    def test_bk_006_batch_and_table_change_conflicts(self):
        values = {"table_id": self.table.id, "partner_id": self.partner.id,
                  "start": "2026-06-01 04:30:00", "duration_hours": 1}
        with self.assertRaisesRegex(ValidationError, "already booked"), self.env.cr.savepoint():
            self.Booking.create([values, dict(values)])
        self._book()
        other = self._book(table_id=self.other_table.id)
        with self.assertRaisesRegex(ValidationError, "already booked"), self.env.cr.savepoint():
            other.write({"table_id": self.table.id})

    def test_bk_007_pending_and_lock(self):
        booking = self._book(lock_expire="2099-01-01", deposit_ratio=100)
        self.assertEqual(booking.state, "pending")
        self.assertEqual(booking.lock_expire, datetime(2026, 6, 1, 0, 10))
        self.assertEqual(booking.deposit_ratio, 50)
        self._reject(state="confirmed")

    def test_bk_007_lock_expire_cannot_be_written_directly(self):
        booking = self._book()
        original = booking.lock_expire
        for user in (self.staff, self.manager):
            with self.subTest(user=user.login):
                with self.assertRaises(ValidationError), self.env.cr.savepoint():
                    booking.with_user(user).write({"lock_expire": "2099-01-01 00:00:00"})
                booking.invalidate_recordset(["lock_expire"])
                self.assertEqual(booking.lock_expire, original)

    def test_bk_009_currency_rounding_and_duration(self):
        self.config.deposit_ratio = 30.5
        booking = self._book()
        self.assertEqual(booking.table_fee, 25)
        self.assertEqual(Decimal(str(booking.deposit_amount)), Decimal("7.63"))
        booking.duration_hours = 2
        self.assertEqual(booking.table_fee, 50)
        self.assertEqual(Decimal(str(booking.deposit_amount)), Decimal("15.25"))

    def test_bk_009_derived_amounts_cannot_be_supplied(self):
        booking = self._book(end="2026-06-01 10:30:00", table_fee=1, deposit_amount=1,
                             business_date="2026-06-02")
        self.assertEqual(booking.end, datetime(2026, 6, 1, 5, 30))
        self.assertEqual(booking.business_date, date(2026, 6, 1))
        self.assertEqual((booking.table_fee, booking.deposit_amount), (25, 12.5))
        for field, value in (("end", "2026-06-01 10:30:00"), ("table_fee", 1), ("deposit_amount", 1)):
            with self.assertRaises(ValidationError), self.env.cr.savepoint():
                booking.write({field: value})

    def test_bk_010_every_transition(self):
        paths = {"pending": (), "confirmed": ("confirmed",), "arrived": ("confirmed", "arrived"),
                 "done": ("confirmed", "arrived", "done"), "cancelled": ("cancelled",),
                 "expired": ("expired",), "no_show": ("confirmed", "no_show")}
        allowed = {"pending": {"confirmed", "expired", "cancelled"},
                   "confirmed": {"arrived", "cancelled", "no_show"}, "arrived": {"done"}}
        for source, path in paths.items():
            for target in paths:
                with self.subTest(source=source, target=target), self.env.cr.savepoint():
                    booking = self._book()
                    for state in path:
                        booking.write({"state": state})
                    if source == target or target in allowed.get(source, set()):
                        booking.write({"state": target})
                        self.assertEqual(booking.state, target)
                    else:
                        with self.assertRaises(ValidationError), self.env.cr.savepoint():
                            booking.write({"state": target})
                    booking.sudo().unlink()

    def test_bk_011_sequence_and_database_uniqueness(self):
        first = self._book()
        second = self._book(table_id=self.other_table.id)
        self.assertNotEqual(first.name, second.name)
        for booking in (first, second):
            self.assertRegex(booking.name, r"^QB2026-\d{5}$")
        with self.assertRaises(UniqueViolation), mute_logger("odoo.sql_db"), self.env.cr.savepoint():
            self.env.cr.execute("UPDATE qclub_booking SET name = %s WHERE id = %s", (first.name, second.id))

    def test_bk_011_sequence_restarts_each_year(self):
        self._book()
        with freeze_time("2035-06-01 00:00:00"):
            booking = self._book(start="2035-06-01 04:30:00")
        self.assertEqual(booking.name, "QB2035-00001")

    def test_bk_011_name_cannot_be_written_directly(self):
        booking = self._book()
        original = booking.name
        for user in (self.staff, self.manager):
            with self.subTest(user=user.login):
                with self.assertRaises(ValidationError), self.env.cr.savepoint():
                    booking.with_user(user).write({"name": "QB2099-99999"})
                booking.invalidate_recordset(["name"])
                self.assertEqual(booking.name, original)

    def test_bk_012_website_from_table(self):
        self.assertEqual(self._book().website_id, self.table.website_id)

    def test_cfg_003_snapshots_and_table_switch(self):
        first = self._book()
        self.config.write({"deposit_ratio": 40, "free_cancel_hours": 12, "no_show_wait_minutes": 15})
        second = self._book(table_id=self.other_table.id)
        self.assertEqual((first.deposit_ratio, first.free_cancel_hours, first.no_show_wait_minutes), (50, 24, 30))
        self.assertEqual((second.deposit_ratio, second.free_cancel_hours, second.no_show_wait_minutes), (40, 12, 15))
        second.action_cancel()
        self.other_table.hourly_price = 35
        first.table_id = self.other_table
        self.assertEqual(first.hourly_price, 35)
        self.assertEqual(first.deposit_ratio, 50)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            first.write({"deposit_ratio": 99})

    def test_cfg_003_new_form_previews_and_saves_server_snapshot(self):
        self.config.write({"deposit_ratio": 30.5, "free_cancel_hours": 12, "no_show_wait_minutes": 15})
        form = Form(self.Booking.with_user(self.staff), view="qclub_billiard.qclub_booking_view_form")
        form.table_id = self.table
        form.partner_id = self.partner
        form.start_date = date(2026, 6, 1)
        form.start_hour = "14"
        form.duration_hours = 2
        self.assertEqual(form.hourly_price, 25)
        self.assertEqual((form.deposit_ratio, form.free_cancel_hours, form.no_show_wait_minutes), (30.5, 12, 15))
        self.assertEqual(form.table_fee, 50)
        self.assertEqual(Decimal(str(form.deposit_amount)), Decimal("15.25"))
        booking = form.save()
        self.assertEqual(booking.hourly_price, 25)
        self.assertEqual((booking.deposit_ratio, booking.free_cancel_hours, booking.no_show_wait_minutes),
                         (30.5, 12, 15))
        self.assertEqual(booking.table_fee, 50)
        self.assertEqual(Decimal(str(booking.deposit_amount)), Decimal("15.25"))

    def test_cfg_003_new_form_clears_snapshot_without_table(self):
        form = Form(self.Booking.with_user(self.staff), view="qclub_billiard.qclub_booking_view_form")
        form.table_id = self.table
        form.duration_hours = 2
        self.assertEqual(form.table_fee, 50)
        form.table_id = self.env["qclub.table"]
        self.assertEqual((form.hourly_price, form.deposit_ratio, form.free_cancel_hours, form.no_show_wait_minutes),
                         (0, 0, 0, 0))
        self.assertEqual((form.table_fee, form.deposit_amount), (0, 0))

    def test_cfg_003_saved_form_preserves_snapshot(self):
        booking = self._book(duration_hours=2)
        self.table.hourly_price = 40
        self.other_table.hourly_price = 60
        self.config.write({"deposit_ratio": 20, "free_cancel_hours": 12, "no_show_wait_minutes": 15})
        form = Form(booking.with_user(self.staff), view="qclub_billiard.qclub_booking_view_form")
        self.assertEqual((form.hourly_price, form.deposit_ratio, form.free_cancel_hours, form.no_show_wait_minutes),
                         (25, 50, 24, 30))
        self.assertEqual((form.table_fee, form.deposit_amount), (50, 25))
        # An onchange on a saved booking must also leave its stored snapshot alone.
        form.table_id = self.other_table
        self.assertEqual((form.hourly_price, form.deposit_ratio, form.free_cancel_hours, form.no_show_wait_minutes),
                         (25, 50, 24, 30))
        self.assertEqual((booking.hourly_price, booking.deposit_ratio), (25, 50))

    def test_cfg_003_create_ignores_forged_client_snapshot(self):
        booking = self.Booking.with_user(self.staff).create({
            "table_id": self.table.id, "partner_id": self.partner.id,
            "start": "2026-06-01 04:30:00", "duration_hours": 2,
            "hourly_price": 1, "deposit_ratio": 1, "free_cancel_hours": 999, "no_show_wait_minutes": 999,
        })
        self.assertEqual((booking.hourly_price, booking.deposit_ratio, booking.free_cancel_hours,
                          booking.no_show_wait_minutes), (25, 50, 24, 30))
        self.assertEqual((booking.table_fee, booking.deposit_amount), (50, 25))

    def test_tbl_005_price_snapshot(self):
        first = self._book()
        self.table.hourly_price = 40
        first.write({"table_id": self.table.id})
        first.duration_hours = 2
        self.assertEqual((first.hourly_price, first.table_fee), (25, 50))
        second = self._book(start="2026-06-01 06:30:00")
        self.assertEqual((second.hourly_price, second.table_fee), (40, 40))

    def test_tbl_003_disabled_existing_booking(self):
        booking = self._book()
        self.table.active = False
        self._reject(start="2026-06-01 06:30:00")
        for method in ("action_confirm", "action_arrive", "action_complete"):
            getattr(booking, method)()
        self.assertEqual(booking.state, "done")
        other = self._book(table_id=self.other_table.id)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            other.table_id = self.table

    def test_adm_004_permissions_and_buttons(self):
        booking = self.Booking.with_user(self.staff).create({
            "table_id": self.table.id, "partner_id": self.partner.id,
            "start": "2026-06-01 04:30:00", "duration_hours": 1,
        })
        for method in ("action_confirm", "action_arrive", "action_complete"):
            getattr(booking, method)()
        booking = self._book().with_user(self.staff)
        booking.action_cancel()
        booking = self._book().with_user(self.staff)
        booking.action_confirm()
        booking.action_no_show()
        for user in (self.staff, self.manager, self.internal):
            with self.assertRaises(UserError), self.env.cr.savepoint():
                booking.with_user(user).unlink()
            self.assertTrue(booking.sudo().exists())
        booking.sudo().unlink()
        self.assertFalse(booking.sudo().exists())
        root = ElementTree.fromstring(self.env.ref("qclub_billiard.qclub_booking_view_form").arch_db)
        expected = {"action_confirm": "state != 'pending'", "action_arrive": "state != 'confirmed'",
                    "action_complete": "state != 'arrived'", "action_cancel": "state not in ('pending', 'confirmed')",
                    "action_no_show": "state != 'confirmed'"}
        self.assertEqual(len(root.findall("./header/button")), 5)
        for method, condition in expected.items():
            button = root.find(f"./header/button[@name='{method}']")
            self.assertEqual(button.get("invisible"), condition)
            self.assertEqual(button.get("groups"), "qclub_billiard.group_billiard_staff")

    def test_adm_002_views_search_and_menu(self):
        action = self.env.ref("qclub_billiard.qclub_booking_action")
        self.assertEqual(action.view_mode, "list,calendar,form")
        self.assertIn("search_default_active", action.context)
        root = ElementTree.fromstring(self.env.ref("qclub_billiard.qclub_booking_view_search").arch_db)
        filters = {node.get("name"): node for node in root.findall(".//filter")}
        self.assertEqual(filters["active"].get("domain"), "[('state', 'in', ('pending', 'confirmed', 'arrived'))]")
        for state in ("pending", "confirmed", "arrived", "done", "cancelled", "expired", "no_show"):
            self.assertEqual(filters[state].get("domain"), f"[('state', '=', '{state}')]")
        self.assertEqual(filters["business_date"].get("date"), "business_date")
        for field in ("state", "table_id", "business_date"):
            self.assertIn(f"'group_by': '{field}'", filters[f"group_{field}"].get("context"))
        calendar = ElementTree.fromstring(self.env.ref("qclub_billiard.qclub_booking_view_calendar").arch_db)
        self.assertEqual((calendar.get("date_start"), calendar.get("date_stop")), ("start", "end"))
        self.assertEqual(self.env.ref("qclub_billiard.menu_billiard_bookings").action, action)
