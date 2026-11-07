from datetime import datetime, timedelta
from unittest.mock import patch

from freezegun import freeze_time
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import BilliardCase


@tagged("post_install", "-at_install")
@freeze_time("2026-11-01 00:00:00")
class TestOnlineBooking(BilliardCase):
    def setUp(self):
        super().setUp()
        self.Booking = self.env["qclub.booking"].sudo()
        self.config = self.env["qclub.config"]._get_for_website(self.qclub)
        self.config.write({"online_booking": True, "booking_email_from": "Q Club <booking@cueclub.example>",
                           "max_unpaid_online_bookings": 2})
        self.env["qclub.opening.hours"]._load_default_hours(self.qclub)
        self.qclub.domain = "https://cueclub.example"
        self.qclub.company_id.currency_id = self.env.ref("base.AUD")
        self.table = self.env["qclub.table"].create({
            "name": "Online table", "website_id": self.qclub.id,
            "type_id": self._make_type().id, "hourly_price": 20,
        })
        self.partner = self.env["res.partner"].create({"name": "Online guest", "email": "guest@example.invalid"})
        self.start = datetime(2026, 11, 6, 12, 30)  # Friday 11 PM Adelaide

    def _book(self, **extra):
        return self.Booking.create(dict(table_id=self.table.id, partner_id=self.partner.id,
                                        start=self.start, duration_hours=2, **extra))

    def test_web_008_shared_quote_and_backend_amounts(self):
        quote = self.Booking._quote_online(self.qclub, self.table.id, "2026-11-06T12:30:00Z", 2)
        booking = self._book()
        self.assertEqual((quote["table_fee"], quote["deposit_amount"]), (40, 20))
        self.assertEqual((booking.table_fee, booking.deposit_amount), (40, 20))

    def test_web_010_one_overnight_format_in_quote_confirmation_and_email(self):
        booking = self._book(booking_channel="online")
        expected = "Fri 6 Nov, 11:00 PM – Sat 7 Nov, 1:00 AM"
        self.assertEqual(booking._time_label(), expected)
        quote = self.Booking._quote_online(self.qclub, self.table.id, "2026-11-06T12:30:00Z", 2,
                                          check_conflicts=False)
        self.assertEqual(quote["time_label"], expected)
        booking._queue_booking_email()
        mail = self.env["mail.mail"].search([("subject", "ilike", booking.name)], limit=1)
        self.assertIn(expected, mail.body_html)
        self.assertEqual(mail.email_from, self.config.booking_email_from)
        self.assertIn("https://cueclub.example/billiard/booking/confirmation/", mail.body_html)
        for forbidden in ("AUSHARE", "Powered by Odoo", self.qclub.company_id.name):
            self.assertNotIn(forbidden, mail.body_html)

    def test_web_009_creation_boundary_and_immutable_fact(self):
        for delta, expected in ((-1, True), (0, False), (1, False)):
            with self.subTest(delta=delta), freeze_time(self.start - timedelta(hours=24, seconds=delta)):
                booking = self._book()
                self.assertEqual(booking.created_in_cancel_window, expected)
                booking.write({"start": self.start + timedelta(days=1)})
                self.assertEqual(booking.created_in_cancel_window, expected)
                booking.action_cancel()
                with self.assertRaises(ValidationError):
                    booking.write({"created_in_cancel_window": not expected})

    def test_web_004_invalid_inputs_do_not_create(self):
        count = self.Booking.search_count([])
        for start, hours in (("bad", 2), ("2026-11-06T12:31:00Z", 2),
                             ("2026-11-06T12:30:00Z", 5), ("2026-11-06T12:30:00Z", 1.5),
                             ("2026-10-01T12:30:00Z", 1), ("2026-11-06T01:30:00Z", 1)):
            with self.subTest(start=start, hours=hours), self.assertRaises(ValidationError):
                self.Booking._quote_online(self.qclub, self.table.id, start, hours)
        self.assertEqual(self.Booking.search_count([]), count)

    def test_web_005_dedicated_conflict_exception(self):
        from ..models.qclub_booking import BookingConflict
        self._book()
        count = self.Booking.search_count([])
        with self.assertRaises(BookingConflict):
            self._book()
        self.assertEqual(self.Booking.search_count([]), count)

    def test_cfg_004_online_limit_and_backoffice_exemption(self):
        self.start = datetime(2026, 11, 6, 3, 30)  # Friday 2 PM, all three intervals open.
        self._book(booking_channel="online")
        self.start += timedelta(hours=2)
        self._book(booking_channel="online")
        self.start += timedelta(hours=2)
        with self.assertRaisesRegex(ValidationError, "already have unpaid"):
            self._book(booking_channel="online")
        self._book()
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.config.max_unpaid_online_bookings = 0

    def test_web_008_email_opt_out_and_queue_failure(self):
        booking = self._book()
        before = self.env["mail.mail"].search_count([])
        booking._queue_booking_email()
        self.assertEqual(self.env["mail.mail"].search_count([]), before)
        booking.action_cancel()
        booking = self._book(booking_channel="online")
        self.config.booking_email_from = False
        booking._queue_booking_email()
        self.assertEqual(self.env["mail.mail"].search_count([]), before)
        self.config.booking_email_from = "Q Club <booking@cueclub.example>"
        with (patch.object(type(self.env["mail.mail"]), "create", side_effect=RuntimeError("queue unavailable")),
              mute_logger("odoo.addons.qclub_billiard.models.qclub_booking")):
            booking._queue_booking_email()
        self.assertTrue(booking.exists())

    def test_web_010_dst_overnight_labels(self):
        for now, start, expected in (
            ("2026-04-01", "2026-04-04T12:30:00Z", "Sat 4 Apr, 11:00 PM – Sun 5 Apr, 1:00 AM"),
            ("2026-10-01", "2026-10-03T13:30:00Z", "Sat 3 Oct, 11:00 PM – Sun 4 Oct, 1:00 AM"),
        ):
            with freeze_time(now):
                quote = self.Booking._quote_online(self.qclub, self.table.id, start, 2)
                self.assertEqual(quote["time_label"], expected)
                self.assertEqual(quote["deposit_amount"], 20)
