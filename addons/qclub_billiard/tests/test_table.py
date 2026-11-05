from psycopg2.errors import CheckViolation, UniqueViolation

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import tagged
from odoo.tools import mute_logger

from .common import BilliardCase


@tagged("post_install", "-at_install")
class TestTable(BilliardCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.snooker = cls._make_type("Snooker")
        cls.Table = cls.env["qclub.table"]

    def _make_table(self, name="Table 1", price=30.0, website=None, table_type=None, **extra):
        vals = {
            "name": name,
            "type_id": (table_type or self.snooker).id,
            "hourly_price": price,
            "website_id": (website or self.qclub).id,
        }
        vals.update(extra)
        return self.Table.create(vals)

    # ---- TBL-001 ----
    def test_tbl_001_create_table_with_all_fields(self):
        table = self._make_table("Table 7", price=32.5, sequence=3, active=True)
        self.assertEqual(table.name, "Table 7")
        self.assertEqual(table.type_id, self.snooker)
        self.assertEqual(table.hourly_price, 32.5)
        self.assertEqual(table.sequence, 3)
        self.assertTrue(table.active)
        self.assertEqual(table.website_id, self.qclub)
        self.assertEqual(table.currency_id, self.qclub.company_id.currency_id)
        self.assertEqual(table.currency_id.name, "AUD")

    def test_tbl_001_name_unique_per_website(self):
        self._make_table("Table 1")
        with self.assertRaises(UniqueViolation), mute_logger("odoo.sql_db"), self.env.cr.savepoint():
            self._make_table("Table 1")
            self.env.flush_all()

    def test_tbl_001_same_name_allowed_on_other_website(self):
        self._make_table("Table 1")
        aushare_type = self._make_type("Snooker", website=self.aushare)
        other = self._make_table("Table 1", website=self.aushare, table_type=aushare_type)
        self.env.flush_all()
        self.assertEqual(other.website_id, self.aushare)

    def test_tbl_001_negative_price_rejected_on_create(self):
        # On create the INSERT runs first, so the database CHECK constraint is what rejects it.
        with self.assertRaises(CheckViolation), mute_logger("odoo.sql_db"), self.env.cr.savepoint():
            self._make_table("Cheap", price=-1)

    def test_tbl_001_negative_price_rejected_on_write(self):
        table = self._make_table("Table 8")
        with self.assertRaises(ValidationError):
            table.write({"hourly_price": -1})

    def test_tbl_001_negative_price_rejected_by_database(self):
        table = self._make_table("Table 2")
        with self.assertRaises(CheckViolation), mute_logger("odoo.sql_db"), self.env.cr.savepoint():
            self.env.cr.execute("UPDATE qclub_table SET hourly_price = -5 WHERE id = %s", [table.id])

    def test_tbl_001_type_must_belong_to_same_website(self):
        aushare_type = self._make_type("Pool", website=self.aushare)
        with self.assertRaises(ValidationError):
            self._make_table("Table 3", table_type=aushare_type)

    def test_tbl_001_type_website_change_blocked_when_used(self):
        for active in (True, False):
            with self.subTest(active=active):
                table_type = self._make_type("Used type %s" % active)
                table = self._make_table("Used table %s" % active, table_type=table_type, active=active)
                with self.assertRaises(ValidationError), self.env.cr.savepoint():
                    table_type.with_user(self.manager).write({"website_id": self.aushare.id})
                self.assertEqual(table_type.website_id, self.qclub)
                self.assertEqual(table.website_id, self.qclub)

    def test_tbl_001_unused_type_website_change_allowed(self):
        table_type = self._make_type("Unused type")
        table_type.with_user(self.manager).write({"website_id": self.aushare.id})
        self.assertEqual(table_type.website_id, self.aushare)

    def test_tbl_001_manager_manages_staff_reads(self):
        table = self._make_table("Table 4")
        self.assertEqual(table.with_user(self.staff).name, "Table 4")
        with self.assertRaises(AccessError):
            table.with_user(self.staff).write({"hourly_price": 1})
        table.with_user(self.manager).write({"hourly_price": 40})
        self.assertEqual(table.hourly_price, 40)

    # ---- TBL-002 ----
    def test_tbl_002_module_ships_no_hard_coded_types(self):
        Type = self.env["qclub.table.type"].with_context(active_test=False)
        self.assertEqual(Type.search_count([("id", "!=", self.snooker.id)]), 0)

    def test_tbl_002_manager_can_add_rename_archive_types(self):
        Type = self.env["qclub.table.type"].with_user(self.manager)
        nine_ball = Type.create({"name": "9-Ball", "website_id": self.qclub.id})
        nine_ball.name = "Nine Ball"
        nine_ball.active = False
        self.assertEqual(nine_ball.name, "Nine Ball")
        self.assertFalse(Type.search([("name", "=", "Nine Ball")]))

    def test_tbl_002_staff_cannot_change_types(self):
        with self.assertRaises(AccessError):
            self.env["qclub.table.type"].with_user(self.staff).create({"name": "X", "website_id": self.qclub.id})

    def test_tbl_002_type_name_unique_per_website(self):
        with self.assertRaises(UniqueViolation), mute_logger("odoo.sql_db"), self.env.cr.savepoint():
            self._make_type("Snooker")
            self.env.flush_all()

    # ---- TBL-003 ----
    def test_tbl_003_disabled_table_not_bookable(self):
        table = self._make_table("Table 5")
        self.assertTrue(table._check_bookable())
        table.active = False
        with self.assertRaises(ValidationError):
            table._check_bookable()

    def test_tbl_003_reenabled_table_bookable_again(self):
        table = self._make_table("Table 6", active=False)
        table.active = True
        self.assertTrue(table._check_bookable())
