from psycopg2.errors import CheckViolation, UniqueViolation

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import tagged
from odoo.tools import mute_logger

from .common import BilliardCase


@tagged("post_install", "-at_install")
class TestConfig(BilliardCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Config = cls.env["qclub.config"]
        cls.config = cls.Config._get_for_website(cls.qclub)

    # ---- CFG-001 ----
    def test_cfg_001_defaults(self):
        self.assertEqual(self.config.deposit_ratio, 50.0)
        self.assertEqual(self.config.free_cancel_hours, 24)
        self.assertEqual(self.config.no_show_wait_minutes, 30)
        self.assertEqual(self.config.lock_minutes, 10)
        self.assertEqual(self.config.max_consecutive_hours, 4)
        self.assertEqual(self.config.max_advance_days, 14)

    def test_cfg_001_get_for_website_does_not_duplicate(self):
        again = self.Config._get_for_website(self.qclub)
        self.assertEqual(again, self.config)
        self.assertEqual(self.Config.search_count([("website_id", "=", self.qclub.id)]), 1)

    def test_cfg_001_one_config_per_website(self):
        other = self.Config._get_for_website(self.aushare)
        self.assertNotEqual(other, self.config)
        with self.assertRaises(UniqueViolation), mute_logger("odoo.sql_db"), self.env.cr.savepoint():
            self.Config.create({"website_id": self.qclub.id})
            self.env.flush_all()

    def test_cfg_001_manager_can_change_all_settings(self):
        values = {
            "deposit_ratio": 30.0,
            "free_cancel_hours": 12,
            "no_show_wait_minutes": 15,
            "lock_minutes": 5,
            "max_consecutive_hours": 3,
            "max_advance_days": 7,
        }
        self.config.with_user(self.manager).write(values)
        for field_name, value in values.items():
            self.assertEqual(self.config[field_name], value, field_name)

    # ---- CFG-002 ----
    def test_cfg_002_deposit_ratio_out_of_range_rejected(self):
        for bad in (-1, 100.01, 150):
            with self.assertRaises(ValidationError, msg=bad):
                self.config.write({"deposit_ratio": bad})

    def test_cfg_002_negative_durations_rejected(self):
        for field_name in ("free_cancel_hours", "no_show_wait_minutes", "lock_minutes", "max_advance_days"):
            with self.assertRaises(ValidationError, msg=field_name):
                self.config.write({field_name: -1})

    def test_cfg_002_max_consecutive_at_least_one(self):
        with self.assertRaises(ValidationError):
            self.config.write({"max_consecutive_hours": 0})

    def test_cfg_002_boundary_values_accepted(self):
        self.config.write({
            "deposit_ratio": 0, "free_cancel_hours": 0, "no_show_wait_minutes": 0,
            "lock_minutes": 0, "max_consecutive_hours": 1, "max_advance_days": 0,
        })
        self.config.write({"deposit_ratio": 100})
        self.env.flush_all()
        self.assertEqual(self.config.deposit_ratio, 100)

    def test_cfg_002_database_rejects_invalid_values(self):
        statements = (
            "UPDATE qclub_config SET deposit_ratio = 101 WHERE id = %s",
            "UPDATE qclub_config SET lock_minutes = -1 WHERE id = %s",
            "UPDATE qclub_config SET max_consecutive_hours = 0 WHERE id = %s",
        )
        self.env.flush_all()
        for sql in statements:
            with self.assertRaises(CheckViolation, msg=sql), mute_logger("odoo.sql_db"), self.env.cr.savepoint():
                self.env.cr.execute(sql, [self.config.id])

    # ---- CFG-004 ----
    def test_cfg_004_staff_cannot_create_settings_via_helper(self):
        website = self.env["website"].create({"name": "Staff helper website"})
        domain = [("website_id", "=", website.id)]
        self.assertEqual(self.Config.search_count(domain), 0)
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            self.Config.with_user(self.staff)._get_for_website(website)
        self.assertEqual(self.Config.search_count(domain), 0)

    def test_cfg_004_manager_helper_creates_missing_settings(self):
        website = self.env["website"].create({"name": "Manager helper website"})
        domain = [("website_id", "=", website.id)]
        self.assertEqual(self.Config.search_count(domain), 0)
        config = self.Config.with_user(self.manager)._get_for_website(website)
        self.assertEqual(config.website_id, website)
        self.assertEqual(config.env.uid, self.manager.id)
        self.assertEqual(self.Config.search_count(domain), 1)

    def test_cfg_004_staff_read_only(self):
        as_staff = self.config.with_user(self.staff)
        self.assertEqual(as_staff.deposit_ratio, 50.0)
        with self.assertRaises(AccessError):
            as_staff.write({"deposit_ratio": 20})
        with self.assertRaises(AccessError):
            self.Config.with_user(self.staff).create({"website_id": self.aushare.id})

    def test_cfg_004_manager_can_write(self):
        self.config.with_user(self.manager).write({"deposit_ratio": 40})
        self.assertEqual(self.config.deposit_ratio, 40)

    def test_cfg_004_other_internal_users_have_no_access(self):
        with self.assertRaises(AccessError):
            self.config.with_user(self.internal).read(["deposit_ratio"])
