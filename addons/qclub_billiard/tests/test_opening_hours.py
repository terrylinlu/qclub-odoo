from datetime import date, datetime
from xml.etree import ElementTree

from psycopg2.errors import CheckViolation

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import tagged
from odoo.tools import mute_logger

from .common import BilliardCase


@tagged("post_install", "-at_install")
class TestOpeningHours(BilliardCase):
    def setUp(self):
        super().setUp()
        self.Hours = self.env["qclub.opening.hours"]
        self.Hours.search([("website_id", "in", (self.qclub.id, self.aushare.id))]).unlink()

    def _segment(self, weekday="0", opening=14, closing=24, website=None):
        return self.Hours.create({
            "website_id": (website or self.qclub).id,
            "weekday": weekday, "open_hour": opening, "close_hour": closing,
        })

    def test_tbl_004_invalid_bounds_on_create(self):
        # On create the INSERT runs before the Python constraint.
        for opening, closing in ((24, 26), (-1, 10), (14, 14), (14, 13), (14, 39)):
            with self.assertRaises(CheckViolation), mute_logger("odoo.sql_db"), self.env.cr.savepoint():
                self._segment(opening=opening, closing=closing)

    def test_tbl_004_invalid_bounds_on_write(self):
        segment = self._segment()
        for opening, closing in ((24, 26), (-1, 10), (14, 14), (14, 13), (14, 39)):
            with self.assertRaises(ValidationError), self.env.cr.savepoint():
                segment.write({"open_hour": opening, "close_hour": closing})

    def test_tbl_004_overlaps(self):
        for first, second in (
            (("0", 14, 20), ("0", 18, 22)),
            (("4", 14, 30), ("5", 5, 10)),
            (("6", 13, 30), ("0", 5, 10)),
        ):
            with self.subTest(first=first), self.env.cr.savepoint():
                segment = self._segment(*first)
                with self.assertRaises(ValidationError), self.env.cr.savepoint():
                    self._segment(*second)
                segment.unlink()

    def test_tbl_004_adjacent_sorted_and_website_scope(self):
        later = self._segment("0", 18, 22)
        earlier = self._segment("0", 14, 18)
        self._segment("0", 14, 22, self.aushare)
        self.assertEqual(self.Hours._get_business_intervals(self.qclub, date(2026, 6, 1)), [
            (datetime(2026, 6, 1, 4, 30), datetime(2026, 6, 1, 8, 30)),
            (datetime(2026, 6, 1, 8, 30), datetime(2026, 6, 1, 12, 30)),
        ])
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            later.write({"open_hour": 17})
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.Hours.create([
                {"website_id": self.qclub.id, "weekday": "2", "open_hour": 14, "close_hour": 20},
                {"website_id": self.qclub.id, "weekday": "2", "open_hour": 18, "close_hour": 22},
            ])
        self.assertEqual(earlier.open_display, "2:00 PM")

    def test_tbl_004_database_checks(self):
        segment = self._segment()
        self.env.flush_all()
        for opening, closing in ((24, 26), (-1, 10), (14, 14), (14, 13), (14, 39)):
            with self.assertRaises(CheckViolation), mute_logger("odoo.sql_db"), self.env.cr.savepoint():
                self.env.cr.execute(
                    "UPDATE qclub_opening_hours SET open_hour = %s, close_hour = %s WHERE id = %s",
                    (opening, closing, segment.id),
                )

    def test_tbl_004_permissions(self):
        segment = self._segment()
        self.assertEqual(segment.with_user(self.staff).open_hour, 14)
        with self.assertRaises(AccessError):
            segment.with_user(self.staff).write({"open_hour": 15})
        with self.assertRaises(AccessError):
            segment.with_user(self.staff).unlink()
        segment.with_user(self.manager).write({"open_hour": 15})
        self.assertEqual(segment.open_hour, 15)
        segment.with_user(self.manager).unlink()
        created = self.Hours.with_user(self.manager).create({
            "website_id": self.qclub.id, "weekday": "0", "open_hour": 0, "close_hour": 24,
        })
        self.assertEqual(created.open_hour, 0)

    def test_tbl_004_business_day_ownership_and_display(self):
        segment = self._segment("4", 14, 26)
        self.assertEqual(segment.display_name, "Friday 14:00 – Saturday 02:00")
        self.assertEqual(segment.close_display, "2:00 AM (+1 day)")
        self.assertEqual(len(self.Hours._get_business_intervals(self.qclub, date(2026, 6, 5))), 1)
        self.assertEqual(self.Hours._get_business_intervals(self.qclub, date(2026, 6, 6)), [])
        self.assertEqual(self.Hours._get_business_intervals(self.qclub, date(2026, 6, 1)), [])
        segment.write({"close_hour": 24})
        self.assertEqual(segment.close_display, "12:00 AM (midnight)")

    def test_tbl_004_timezone_and_dst(self):
        cases = (
            (date(2026, 6, 1), 14, 24, datetime(2026, 6, 1, 4, 30), datetime(2026, 6, 1, 14, 30)),
            (date(2026, 12, 7), 14, 24, datetime(2026, 12, 7, 3, 30), datetime(2026, 12, 7, 13, 30)),
            (date(2026, 4, 4), 13, 26, datetime(2026, 4, 4, 2, 30), datetime(2026, 4, 4, 15, 30)),
            (date(2026, 10, 3), 13, 26, datetime(2026, 10, 3, 3, 30), datetime(2026, 10, 3, 16, 30)),
            (date(2026, 4, 4), 23, 26, datetime(2026, 4, 4, 12, 30), datetime(2026, 4, 4, 15, 30)),
            (date(2026, 10, 3), 23, 28, datetime(2026, 10, 3, 13, 30), datetime(2026, 10, 3, 17, 30)),
        )
        for day, opening, closing, start, end in cases:
            with self.subTest(day=day, opening=opening):
                segment = self._segment(str(day.weekday()), opening, closing)
                self.assertEqual(self.Hours._get_business_intervals(self.qclub, day), [(start, end)])
                segment.unlink()

    def test_tbl_007_defaults_idempotent_and_isolated(self):
        hours = self.Hours.with_user(self.manager)._load_default_hours(self.qclub)
        self.assertEqual(len(hours), 7)
        self.assertEqual([(h.weekday, h.open_hour, h.close_hour) for h in hours], [
            ("0", 14, 24), ("1", 14, 24), ("2", 14, 24), ("3", 14, 24),
            ("4", 14, 26), ("5", 13, 26), ("6", 13, 24),
        ])
        before = hours.read(["weekday", "open_hour", "close_hour", "write_date"])
        again = self.Hours._load_default_hours(self.qclub)
        self.assertEqual(again.ids, hours.ids)
        self.assertEqual(again.read(["weekday", "open_hour", "close_hour", "write_date"]), before)
        self.assertFalse(self.Hours.search([("website_id", "=", self.aushare.id)]))

    def test_tbl_007_custom_hours_unchanged(self):
        segment = self._segment("2", 10, 12)
        self.assertEqual(self.Hours._load_default_hours(self.qclub), segment)
        self.assertEqual((segment.weekday, segment.open_hour, segment.close_hour), ("2", 10, 12))

    def test_tbl_007_staff_cannot_load_defaults(self):
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            self.Hours.with_user(self.staff)._load_default_hours(self.qclub)
        self._segment()
        with self.assertRaises(AccessError):
            self.Hours.with_user(self.staff)._load_default_hours(self.qclub)

    def test_tbl_007_settings_button(self):
        config = self.env["qclub.config"]._get_for_website(self.qclub).with_user(self.manager)
        self.assertFalse(config.has_opening_hours)
        view = self.env.ref("qclub_billiard.qclub_config_view_form")
        root = ElementTree.fromstring(view.arch_db)
        button = root.find(".//header/button[@name='action_load_default_opening_hours']")
        self.assertIsNotNone(button)
        self.assertEqual(button.get("groups"), "qclub_billiard.group_billiard_manager")
        self.assertEqual(button.get("invisible"), "has_opening_hours")
        self.assertEqual(config.action_load_default_opening_hours(), {"type": "ir.actions.client", "tag": "reload"})
        self.assertTrue(config.has_opening_hours)
        self.assertEqual(self.Hours.search_count([("website_id", "=", self.qclub.id)]), 7)
        with self.assertRaises(AccessError):
            config.with_user(self.staff).action_load_default_opening_hours()

    def test_tbl_004_twelve_hour_display_and_no_aggregation(self):
        for opening, expected in ((0, "12:00 AM"), (12, "12:00 PM"), (13, "1:00 PM")):
            with self.subTest(opening=opening):
                segment = self._segment(opening=opening, closing=opening + 1)
                self.assertEqual(segment.open_display, expected)
                segment.unlink()
        for opening, closing, expected in (
            (14, 22, "10:00 PM"),
            (14, 24, "12:00 AM (midnight)"),
            (14, 26, "2:00 AM (+1 day)"),
            (23, 47, "11:00 PM (+1 day)"),
        ):
            with self.subTest(closing=closing):
                segment = self._segment(opening=opening, closing=closing)
                self.assertEqual(segment.close_display, expected)
                segment.unlink()
        for field_name in ("open_hour", "close_hour"):
            with self.subTest(field_name=field_name):
                self.assertFalse(self.Hours._fields[field_name].aggregator)
