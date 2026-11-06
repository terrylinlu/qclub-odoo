from datetime import date, datetime

from freezegun import freeze_time
from psycopg2.errors import CheckViolation

from odoo.exceptions import ValidationError
from odoo.tests import Form
from odoo.tests.common import tagged
from odoo.tools import mute_logger

from ..controllers.main import BilliardBooking
from ..models.qclub_opening_hours import business_date_of_utc, business_today
from .common import BilliardCase


@tagged("post_install", "-at_install")
@freeze_time("2026-06-01 00:00:00")
class TestBusinessDayForm(BilliardCase):
    def setUp(self):
        super().setUp()
        self.Booking = self.env["qclub.booking"]
        self.Hours = self.env["qclub.opening.hours"]
        self.Hours.search([("website_id", "=", self.qclub.id)]).unlink()
        self.Hours._load_default_hours(self.qclub)
        self.config = self.env["qclub.config"]._get_for_website(self.qclub)
        self.config.max_advance_days = 14
        kind = self._make_type("Business day form type")
        self.table = self.env["qclub.table"].create({
            "name": "Business day form table", "type_id": kind.id,
            "website_id": self.qclub.id, "hourly_price": 25,
        })
        self.partner = self.env["res.partner"].create({"name": "Business day form customer"})

    def _form(self):
        form = Form(self.Booking.with_user(self.staff), view="qclub_billiard.qclub_booking_view_form")
        form.table_id = self.table
        form.partner_id = self.partner
        return form

    def test_tbl_004_business_day_bounds_sql_and_python(self):
        segment = self.Hours.search([("website_id", "=", self.qclub.id), ("weekday", "=", "0")])
        for opening, closing in ((5, 24), (14, 31)):
            with self.subTest(opening=opening, closing=closing):
                with self.assertRaisesRegex(ValidationError, "Opening hours must be within one business day"), \
                        self.env.cr.savepoint():
                    segment.write({"open_hour": opening, "close_hour": closing})
                with self.assertRaises(CheckViolation), mute_logger("odoo.sql_db"), self.env.cr.savepoint():
                    self.env.cr.execute(
                        "UPDATE qclub_opening_hours SET open_hour = %s, close_hour = %s WHERE id = %s",
                        (opening, closing, segment.id),
                    )
        for opening, closing in ((6, 30), (14, 26)):
            segment.write({"open_hour": opening, "close_hour": closing})
            segment.flush_recordset()
            self.assertEqual((segment.open_hour, segment.close_hour), (opening, closing))

    def test_tbl_004_business_date_cutoff_at_six(self):
        for instant, expected in (
            (datetime(2026, 6, 5, 20, 29, 59), date(2026, 6, 5)),
            (datetime(2026, 6, 5, 20, 30), date(2026, 6, 6)),
            (datetime(2026, 10, 3, 19, 29, 59), date(2026, 10, 3)),
            (datetime(2026, 10, 3, 19, 30), date(2026, 10, 4)),
        ):
            with self.subTest(instant=instant), freeze_time(instant):
                self.assertEqual(business_date_of_utc(instant), expected)
                self.assertEqual(business_today(), expected)

    def test_bk_002_next_day_overrun_warns_and_rejects(self):
        form = self._form()
        form.start_date = date(2026, 6, 5)
        form.start_hour = "1"
        saved = form.save()
        self.assertEqual(saved.start, datetime(2026, 6, 5, 15, 30))
        self.assertEqual(saved.business_date, date(2026, 6, 5))
        preview = self.Booking.new({
            "table_id": self.table.id, "start": saved.start, "duration_hours": 2, "state": "pending",
        })
        self.assertEqual(preview._onchange_start_slot()["warning"]["message"],
                         "The booking must be fully within one business opening interval.")
        edit = Form(saved.with_user(self.staff), view="qclub_billiard.qclub_booking_view_form")
        edit.duration_hours = 2
        with self.assertRaisesRegex(ValidationError, "fully within one business opening interval"), \
                self.env.cr.savepoint():
            edit.save()

    @freeze_time("2026-06-05 15:00:00")
    def test_bk_003_tbl_006_after_midnight_defaults_and_date_bounds(self):
        form = self._form()
        self.assertEqual((form.start_date, form.start_hour), (date(2026, 6, 5), "1"))
        saved = form.save()
        self.assertEqual(saved.start, datetime(2026, 6, 5, 15, 30))
        result = self.Booking._get_occupancy(self.qclub, date(2026, 6, 5))
        self.assertEqual(result["available_dates"], {"min": "2026-06-05", "max": "2026-06-19"})
        self.assertEqual(BilliardBooking()._date_bounds(self.config), (date(2026, 6, 5), date(2026, 6, 19)))
        self.config.max_advance_days = 0
        self.assertEqual(self.Booking._first_available_start(self.qclub), saved.start)
        with self.assertRaisesRegex(ValidationError, "maximum advance"), self.env.cr.savepoint():
            self.Booking.create({
                "table_id": self.table.id, "partner_id": self.partner.id,
                "start": datetime(2026, 6, 6, 3, 30), "duration_hours": 1,
            })

    def test_web_007_dst_form_next_day_conversion_first_fold(self):
        for day, now, expected in (
            (date(2026, 4, 4), "2026-04-04 00:00:00", datetime(2026, 4, 4, 14, 30)),
            (date(2026, 10, 3), "2026-10-03 00:00:00", datetime(2026, 10, 3, 15, 30)),
        ):
            with self.subTest(day=day), freeze_time(now):
                form = self._form()
                form.start_hour = "1"
                self.assertEqual(form.start_date, day)
                booking = form.save()
                self.assertEqual(booking.start, expected)
                self.assertEqual(booking.business_date, day)
                booking.action_cancel()
        segment = self.Hours.search([("website_id", "=", self.qclub.id), ("weekday", "=", "5")])
        segment.close_hour = 30
        with freeze_time("2026-04-04 00:00:00"):
            form = self._form()
            form.start_hour = "2"
            booking = form.save()
            self.assertEqual(booking.start, datetime(2026, 4, 4, 15, 30))
            self.assertEqual(booking.business_date, date(2026, 4, 4))

    def test_bk_003_date_change_keeps_valid_time(self):
        form = self._form()
        form.start_date = date(2026, 6, 5)
        form.start_hour = "18"
        saved = form.save()
        preview = self.Booking.new({
            "table_id": self.table.id, "start": saved.start, "duration_hours": 2,
        })
        preview.start_date = date(2026, 6, 6)
        self.assertFalse(preview._onchange_start_slot())
        self.assertEqual(preview.start_hour, "18")
        self.assertEqual(preview.start, datetime(2026, 6, 6, 8, 30))
        edit = Form(saved.with_user(self.staff), view="qclub_billiard.qclub_booking_view_form")
        edit.start_date = date(2026, 6, 6)
        self.assertEqual(edit.start_hour, "18")
        self.assertEqual(edit.save().start, datetime(2026, 6, 6, 8, 30))

    def test_bk_003_date_change_next_day_moves_with_exact_warning(self):
        preview = self.Booking.new({
            "table_id": self.table.id, "start": datetime(2026, 6, 5, 16, 30),
            "duration_hours": 1,
        })
        self.assertEqual(preview.start_hour, "2")
        preview.start_date = date(2026, 6, 6)
        self.assertEqual(preview._onchange_start_slot(), {"warning": {
            "title": "Booking time",
            "message": "Start Time changed to 1:00 PM: 2:00 AM (next day) is not available on this date.",
        }})
        self.assertEqual(preview.start_hour, "13")
        self.assertEqual(preview.start, datetime(2026, 6, 6, 3, 30))

    def test_bk_003_date_change_duration_overrun_moves_with_warning(self):
        preview = self.Booking.new({
            "table_id": self.table.id, "start": datetime(2026, 6, 5, 14, 30),
            "duration_hours": 2,
        })
        preview.start_date = date(2026, 6, 7)
        self.assertEqual(preview._onchange_start_slot(), {"warning": {
            "title": "Booking time",
            "message": "Start Time changed to 1:00 PM: 12:00 AM (next day) is not available on this date.",
        }})
        self.assertEqual(preview.start_hour, "13")
        self.assertEqual(preview.start, datetime(2026, 6, 7, 3, 30))

    def test_bk_003_date_change_closed_date_message(self):
        self.Hours.search([("website_id", "=", self.qclub.id), ("weekday", "=", "5")]).unlink()
        preview = self.Booking.new({
            "table_id": self.table.id, "start": datetime(2026, 6, 5, 8, 30),
            "duration_hours": 1,
        })
        preview.start_date = date(2026, 6, 6)
        self.assertEqual(preview._onchange_start_slot(), {"warning": {
            "title": "Booking time",
            "message": "There is no available opening hour on the selected date.",
        }})

    @freeze_time("2026-06-06 06:00:00")
    def test_bk_003_date_change_past_time_moves_with_warning(self):
        preview = self.Booking.new({
            "table_id": self.table.id, "start": datetime(2026, 6, 7, 3, 30),
            "duration_hours": 1,
        })
        preview.start_date = date(2026, 6, 6)
        self.assertEqual(preview._onchange_start_slot(), {"warning": {
            "title": "Booking time",
            "message": "Start Time changed to 4:00 PM: 1:00 PM is not available on this date.",
        }})
        self.assertEqual(preview.start, datetime(2026, 6, 6, 6, 30))
