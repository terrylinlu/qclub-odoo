import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from freezegun import freeze_time
from lxml import etree

from odoo.exceptions import AccessError
from odoo.tests.common import new_test_user, tagged

from .common import BilliardCase


@tagged("post_install", "-at_install")
@freeze_time("2026-06-01 00:00:00")
class TestOccupancy(BilliardCase):
    def setUp(self):
        super().setUp()
        self.Booking = self.env["qclub.booking"]
        self.Hours = self.env["qclub.opening.hours"]
        self.Hours.search([("website_id", "in", [self.qclub.id, self.aushare.id])]).unlink()
        self.Hours._load_default_hours(self.qclub)
        self.config = self.env["qclub.config"]._get_for_website(self.qclub)
        self.config.write({"online_booking": True, "max_advance_days": 14, "lock_minutes": 10})
        self.qclub.company_id.currency_id = self.env.ref("base.AUD")
        kind = self._make_type("Occupancy type")
        self.table, self.second = self.env["qclub.table"].create([
            {"name": name, "type_id": kind.id, "website_id": self.qclub.id,
             "hourly_price": 25, "sequence": sequence}
            for name, sequence in (("Occupancy first", 1), ("Occupancy second", 2))
        ])
        other_kind = self._make_type("Other occupancy type", self.aushare)
        self.foreign = self.env["qclub.table"].create({
            "name": "Foreign table", "website_id": self.aushare.id,
            "type_id": other_kind.id, "hourly_price": 30,
        })
        self.partner = self.env["res.partner"].create({
            "name": "Private Occupancy Customer", "email": "private-occupancy@example.invalid",
            "phone": "+61000000999",
        })
        self.public = self.qclub.user_id

    def _book(self, start="2026-06-01 04:30:00", duration=1, table=None):
        return self.Booking.create({
            "table_id": (table or self.table).id, "partner_id": self.partner.id,
            "start": start, "duration_hours": duration,
        })

    def _result(self, day=date(2026, 6, 1)):
        return self.Booking.with_user(self.public)._get_occupancy(self.qclub, day)

    def _states(self, result, table=None):
        return next(row["slots"] for row in result["tables"] if row["id"] == (table or self.table).id)

    def test_web_002_public_whitelist_privacy_and_website(self):
        booking = self._book()
        result = self._result()
        self.assertEqual(set(result), {"business_date", "available_dates", "currency", "slots", "tables"})
        self.assertEqual(set(result["available_dates"]), {"min", "max"})
        self.assertEqual(result["available_dates"], {"min": "2026-06-01", "max": "2026-06-15"})
        self.assertEqual(result["business_date"], "2026-06-01")
        self.assertEqual(result["currency"], "AUD")
        self.assertTrue(result["slots"])
        for slot in result["slots"]:
            self.assertEqual(set(slot), {"start", "label", "next_day"})
        self.assertTrue(result["tables"])
        for table in result["tables"]:
            self.assertEqual(set(table), {"id", "name", "type", "hourly_price", "slots"})
            self.assertEqual(len(table["slots"]), len(result["slots"]))
            self.assertLessEqual(set(table["slots"]), {"past", "occupied", "free"})
        text = json.dumps(result)
        for secret in (self.partner.name, self.partner.email, self.partner.phone, booking.name):
            self.assertNotIn(secret, text)
        self.assertNotIn(self.foreign.id, [row["id"] for row in result["tables"]])
        rows = [row for row in result["tables"] if row["id"] in (self.table.id, self.second.id)]
        self.assertEqual([row["id"] for row in rows], [self.table.id, self.second.id])
        self.assertEqual(rows[0]["type"], "Occupancy type")
        self.assertEqual(Decimal(str(rows[0]["hourly_price"])), Decimal("25.00"))

    def test_web_003_states_and_inactive_tables(self):
        transitions = {
            "pending": (), "confirmed": ("action_confirm",), "arrived": ("action_confirm", "action_arrive"),
            "cancelled": ("action_cancel",), "expired": ("_action_expire",),
            "no_show": ("action_confirm", "action_no_show"),
            "done": ("action_confirm", "action_arrive", "action_complete"),
        }
        for index, (state, actions) in enumerate(transitions.items()):
            booking = self._book(start=datetime(2026, 6, 1, 4, 30) + timedelta(hours=index))
            for action in actions:
                getattr(booking, action)()
            self.assertEqual(booking.state, state)
        self.second.active = False
        result = self._result()
        self.assertEqual(self._states(result)[:7], ["occupied"] * 3 + ["free"] * 4)
        self.assertNotIn(self.second.id, [row["id"] for row in result["tables"]])

    def test_web_003_stale_pending_read_only_and_past_boundary(self):
        booking = self._book()
        before = booking.read(["state", "lock_expire", "write_date"])
        with freeze_time("2026-06-01 00:10:00"):
            self.assertEqual(self._states(self._result())[0], "free")
        self.assertEqual(booking.read(["state", "lock_expire", "write_date"]), before)
        with freeze_time("2026-06-01 04:30:00"):
            self.assertEqual(self._states(self._result())[:2], ["past", "free"])

    def test_web_003_bk_008_one_minute_hold_frees_then_cron_expires(self):
        self.config.lock_minutes = 1
        booking = self._book()
        self.assertEqual(self._states(self._result())[0], "occupied")
        with freeze_time("2026-06-01 00:01:00"):
            self.assertEqual(self._states(self._result())[0], "free")
            self.assertEqual(booking.state, "pending")
            self.Booking._cron_expire_pending()
            self.assertEqual(booking.state, "expired")
            self.assertEqual(self._states(self._result())[0], "free")

    def test_web_007_ordinary_day_split_intervals_and_closed_day(self):
        result = self._result()
        self.assertEqual(len(result["slots"]), 10)
        self.assertEqual(result["slots"][0], {
            "start": "2026-06-01T04:30:00Z", "label": "2:00 PM", "next_day": False,
        })
        self.assertEqual(result["slots"][-1]["label"], "11:00 PM")
        self.Hours.search([("website_id", "=", self.qclub.id), ("weekday", "=", "0")]).unlink()
        self.assertEqual(self._result()["slots"], [])
        self.Hours.create([
            {"website_id": self.qclub.id, "weekday": "0", "open_hour": opening, "close_hour": closing}
            for opening, closing in ((14, 16), (18, 20))
        ])
        self.assertEqual([slot["label"] for slot in self._result()["slots"]],
                         ["2:00 PM", "3:00 PM", "6:00 PM", "7:00 PM"])

    def test_web_007_dst_saturday_nights_and_overlap(self):
        cases = (
            (date(2026, 4, 4), "2026-04-04 00:00:00", "2026-04-04T02:30:00Z", "2026-04-04 12:30:00"),
            (date(2026, 10, 3), "2026-10-03 00:00:00", "2026-10-03T03:30:00Z", "2026-10-03 13:30:00"),
        )
        for day, now, first, late_start in cases:
            with self.subTest(day=day), freeze_time(now):
                booking = self._book(start=late_start, duration=3)
                booking.action_confirm()
                result = self._result(day)
                self.assertEqual(len(result["slots"]), 13)
                self.assertEqual(result["slots"][0]["start"], first)
                self.assertEqual([slot["label"] for slot in result["slots"]], [
                    "1:00 PM", "2:00 PM", "3:00 PM", "4:00 PM", "5:00 PM", "6:00 PM", "7:00 PM",
                    "8:00 PM", "9:00 PM", "10:00 PM", "11:00 PM", "12:00 AM", "1:00 AM",
                ])
                self.assertEqual([slot["next_day"] for slot in result["slots"]], [False] * 11 + [True] * 2)
                starts = [datetime.fromisoformat(slot["start"].removesuffix("Z")) for slot in result["slots"]]
                self.assertTrue(all(b - a == timedelta(hours=1) for a, b in zip(starts, starts[1:])))
                self.assertEqual(self._states(result), ["free"] * 10 + ["occupied"] * 3)
                self.assertEqual(self._states(self._result(day + timedelta(days=1))), ["free"] * 11)

    def test_tbl_006_friday_owns_next_day_columns(self):
        result = self._result(date(2026, 6, 5))
        self.assertEqual(len(result["slots"]), 12)
        self.assertEqual(result["slots"][-2:], [
            {"start": "2026-06-05T14:30:00Z", "label": "12:00 AM", "next_day": True},
            {"start": "2026-06-05T15:30:00Z", "label": "1:00 AM", "next_day": True},
        ])
        saturday = self._result(date(2026, 6, 6))
        self.assertTrue(set(slot["start"] for slot in result["slots"])
                        .isdisjoint(slot["start"] for slot in saturday["slots"]))
        self.assertEqual(saturday["slots"][0]["label"], "1:00 PM")

    def test_cfg_005_defaults_permissions_and_form(self):
        self.assertFalse(self.config.occupancy_requires_login)
        other = self.env["qclub.config"]._get_for_website(self.aushare)
        self.assertFalse(other.online_booking)
        self.assertFalse(other.occupancy_requires_login)
        portal = new_test_user(self.env, login="occupancy-permissions-portal", groups="base.group_portal")
        for field in ("online_booking", "occupancy_requires_login"):
            for user in (self.staff, self.internal, self.public, portal):
                with self.subTest(field=field, user=user.login), self.assertRaises(AccessError):
                    self.config.with_user(user).write({field: True})
            self.config.with_user(self.manager).write({field: True})
            self.assertTrue(self.config[field])
        root = etree.fromstring(self.env.ref("qclub_billiard.qclub_config_view_form").arch_db)
        for field in ("online_booking", "occupancy_requires_login"):
            self.assertTrue(root.xpath(f".//field[@name='{field}']"))

    def test_bk_004_init_idempotent_extension_exists(self):
        self.Booking.init()
        self.Booking.init()
        self.env.cr.execute("SELECT count(*) FROM pg_extension WHERE extname = 'btree_gist'")
        self.assertEqual(self.env.cr.fetchone()[0], 1)
