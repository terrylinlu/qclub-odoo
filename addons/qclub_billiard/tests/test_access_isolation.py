from datetime import timedelta
from unittest.mock import patch

from freezegun import freeze_time

from odoo.addons.website.models import ir_http
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import new_test_user, tagged

from .common import BilliardCase

OWN_MODELS = frozenset({
    "qclub.booking", "qclub.table", "qclub.table.type", "qclub.opening.hours", "qclub.config",
    "qclub.board.post", "qclub.board.terms", "qclub.board.reply", "qclub.board.application",
})
PORTAL_MODELS = OWN_MODELS - {
    "qclub.config", "qclub.board.post", "qclub.board.terms", "qclub.board.reply", "qclub.board.application",
}
DATA_MODELS = OWN_MODELS | {
    "ir.model", "ir.model.fields", "ir.model.constraint", "ir.model.access", "ir.rule",
    "res.groups", "res.groups.privilege", "ir.ui.view", "ir.ui.menu", "ir.actions.act_window",
    "ir.sequence", "ir.cron", "ir.actions.server", "ir.model.fields.selection",
}
# Any future core extension must be listed here with a reason and reviewed explicitly.
CORE_EXTENSION_ALLOWLIST = frozenset()


@tagged("post_install", "-at_install")
@freeze_time("2026-06-01 00:00:00")
class TestAccessIsolation(BilliardCase):
    def setUp(self):
        super().setUp()
        self.customer_a = new_test_user(self.env, login="isolation-customer-a", groups="base.group_portal")
        self.customer_b = new_test_user(self.env, login="isolation-customer-b", groups="base.group_portal")
        Hours = self.env["qclub.opening.hours"].sudo()
        Hours.search([("website_id", "in", (self.qclub.id, self.aushare.id))]).unlink()
        self.hours = Hours._load_default_hours(self.qclub)
        self.config = self.env["qclub.config"].sudo()._get_for_website(self.qclub)
        self.config.write({"max_advance_days": 14, "max_consecutive_hours": 4})
        self.kind = self._make_type("Isolation type")
        self.archived_kind = self._make_type("Archived isolation type")
        self.archived_kind.active = False
        self.table = self.env["qclub.table"].sudo().create({
            "name": "Isolation table", "website_id": self.qclub.id,
            "type_id": self.kind.id, "hourly_price": 25,
        })
        self.archived_table = self.table.copy({"name": "Archived isolation table", "active": False})
        self.values = {
            "table_id": self.table.id, "partner_id": self.customer_a.partner_id.id,
            "start": "2026-06-01 04:30:00", "duration_hours": 1,
        }
        self.booking_a = self.env["qclub.booking"].sudo().create(self.values)
        self.booking_b = self.env["qclub.booking"].sudo().create(dict(
            self.values, partner_id=self.customer_b.partner_id.id, start="2026-06-01 05:30:00",
        ))

    def _portal(self, model, website):
        # website.ir_rule checks frontend status before get_current_website() reads
        # context['website_id']; the same key also partitions the rule-domain cache.
        return self.env[model].with_user(self.customer_a).with_context(
            website_id=website.id if website else False, active_test=False,
        )

    def test_sec_002_own_bookings_and_read_only_models(self):
        with patch.object(ir_http, "get_request_website", return_value=self.qclub):
            Booking = self._portal("qclub.booking", self.qclub)
            self.assertEqual(Booking.search([]).ids, self.booking_a.ids)
            self.assertEqual(Booking.browse(self.booking_a.id).read(["name"])[0]["name"], self.booking_a.name)
            with self.assertRaises(AccessError):
                Booking.browse(self.booking_b.id).read(["name"])
            records = {
                "qclub.booking": (self.booking_a, dict(self.values, start="2026-06-01 06:30:00"),
                                  {"partner_id": self.customer_a.partner_id.id}),
                "qclub.table": (self.table, {"name": "Denied table", "website_id": self.qclub.id,
                                           "type_id": self.kind.id, "hourly_price": 25}, {"name": "Denied"}),
                "qclub.table.type": (self.kind, {"name": "Denied type", "website_id": self.qclub.id},
                                     {"name": "Denied"}),
                "qclub.opening.hours": (self.hours[:1], {"website_id": self.qclub.id, "weekday": "0",
                                                       "open_hour": 7, "close_hour": 8}, {"open_hour": 15}),
            }
            for model, (record, create_values, write_values) in records.items():
                Model = self._portal(model, self.qclub)
                for operation, error, message in (
                    (lambda: Model.create(create_values), AccessError, ".*"),
                    (lambda: Model.browse(record.id).write(write_values), AccessError, ".*"),
                    (lambda: Model.browse(record.id).unlink(),
                     UserError if model == "qclub.booking" else AccessError,
                     "Bookings cannot be deleted. Cancel them instead." if model == "qclub.booking" else ".*"),
                ):
                    with self.subTest(model=model, operation=operation), self.assertRaisesRegex(error, message):
                        with self.env.cr.savepoint():
                            operation()
            self.assertEqual(self._portal("qclub.opening.hours", self.qclub).search([]).ids, self.hours.ids)
            for model, visible, hidden in (
                ("qclub.table", self.table, self.archived_table),
                ("qclub.table.type", self.kind, self.archived_kind),
            ):
                Model = self._portal(model, self.qclub)
                self.assertIn(visible.id, Model.search([]).ids)
                self.assertNotIn(hidden.id, Model.search([]).ids)
                self.assertTrue(Model.browse(visible.id).read(["name"]))
                with self.assertRaises(AccessError):
                    Model.browse(hidden.id).read(["name"])
            with self.assertRaises(AccessError):
                self._portal("qclub.config", self.qclub).search([])
            with self.assertRaises(AccessError):
                self.config.with_user(self.customer_a).read(["deposit_ratio"])

    def test_sec_002_denied_create_preserves_sequence_and_stale_pending(self):
        sequence = self.env.ref("qclub_billiard.qclub_booking_sequence")
        self.assertTrue(sequence.use_date_range)
        # Bookings in setUp have already initialized the real PostgreSQL-backed
        # date-range sequence. Inspect that counter, not just the parent counter.
        date_range = self.env["ir.sequence.date_range"].search([
            ("sequence_id", "=", sequence.id),
            ("date_from", "<=", "2026-06-01"), ("date_to", ">=", "2026-06-01"),
        ])
        self.assertEqual(len(date_range), 1)
        date_range.invalidate_recordset(["number_next_actual"])
        next_number = date_range.number_next_actual
        values = dict(self.values, start="2026-06-01 06:30:00")
        with freeze_time(self.booking_a.lock_expire + timedelta(seconds=1)):
            self.assertEqual(self.booking_a.state, "pending")
            with patch.object(ir_http, "get_request_website", return_value=self.qclub):
                with self.assertRaises(AccessError):
                    self._portal("qclub.booking", self.qclub).create(values)
            date_range.invalidate_recordset(["number_next_actual"])
            self.assertEqual(date_range.number_next_actual, next_number)
            self.booking_a.invalidate_recordset(["state"])
            self.assertEqual(self.booking_a.state, "pending")
            # Positive control: the same valid attempt as superuser really does
            # release this stale hold, so the fixture exercises the expiry path.
            self.env["qclub.booking"].sudo().create(values)
            self.booking_a.invalidate_recordset(["state"])
            self.assertEqual(self.booking_a.state, "expired")

    def test_sec_003_website_switch_and_no_request(self):
        # Repeat Q Club after AUSHARE to exercise cache separation in both directions.
        for website in (self.qclub, self.aushare, self.qclub, self.aushare):
            with patch.object(ir_http, "get_request_website", return_value=website):
                for model in PORTAL_MODELS:
                    records = self._portal(model, website).search([])
                    self.assertEqual(bool(records), website == self.qclub, model)
                if website == self.aushare:
                    with self.assertRaises(AccessError):
                        self._portal("qclub.booking", website).browse(self.booking_a.id).read(["name"])
        # Frontend status is request state, not a cache key. Start a fresh
        # cache before simulating a backend request with a forced website id.
        self.env.registry.clear_cache()
        # No frontend mock: even a website_id alone must not grant frontend access.
        for website in (False, self.qclub):
            for model in PORTAL_MODELS:
                self.assertFalse(self._portal(model, website).search([]), model)
            with self.assertRaises(AccessError):
                self._portal("qclub.booking", website).browse(self.booking_a.id).read(["name"])

    def test_sec_003_public_and_plain_internal_denied(self):
        for user in (self.env.ref("base.public_user"), self.internal):
            with patch.object(ir_http, "get_request_website", return_value=self.qclub):
                for model in OWN_MODELS:
                    with self.subTest(user=user.login, model=model), self.assertRaises(AccessError):
                        self.env[model].with_user(user).with_context(website_id=self.qclub.id).search([])

    def test_sec_003_staff_has_no_website_filter(self):
        kind = self._make_type("Other website type", website=self.aushare)
        table = self.table.copy({"name": "Other website table", "type_id": kind.id,
                                 "website_id": self.aushare.id})
        self.env["qclub.opening.hours"].sudo()._load_default_hours(self.aushare)
        other = self.env["qclub.booking"].sudo().create(dict(self.values, table_id=table.id))
        for website in (self.qclub, self.aushare):
            with patch.object(ir_http, "get_request_website", return_value=website):
                found = self.env["qclub.booking"].with_user(self.staff).with_context(website_id=website.id).search([])
                self.assertTrue(set((self.booking_a | self.booking_b | other).ids) <= set(found.ids))

    def test_iso_001_module_data_whitelist(self):
        offending = []
        for data in self.env["ir.model.data"].search([("module", "=", "qclub_billiard")]):
            xmlid = f"{data.module}.{data.name}"
            if data.model not in DATA_MODELS:
                offending.append(f"{xmlid}: {data.model}")
            elif data.model == "ir.model.fields.selection":
                # Odoo generates these rows for Selection fields; only our own
                # models' fields may contribute selection metadata.
                selection = self.env["ir.model.fields.selection"].browse(data.res_id).exists()
                if not selection or selection.field_id.model_id.model not in OWN_MODELS:
                    offending.append(f"{xmlid}: missing selection or foreign field model")
            elif data.model == "ir.ui.view":
                view = self.env["ir.ui.view"].browse(data.res_id).exists()
                if not view or view.model not in OWN_MODELS or view.inherit_id:
                    offending.append(f"{xmlid}: foreign model or inherited view")
        self.assertFalse(offending, "Forbidden module data:\n" + "\n".join(sorted(offending)))

    def test_iso_002_no_core_model_extensions(self):
        offending = []
        for name, model in self.env.registry.models.items():
            if model._original_module == "qclub_billiard" or name in CORE_EXTENSION_ALLOWLIST:
                continue
            for cls in model.__mro__:
                if (cls.__dict__.get("_module") == "qclub_billiard"
                        or cls.__module__.startswith("odoo.addons.qclub_billiard.")):
                    attributes = sorted(key for key in cls.__dict__ if not key.startswith("__"))
                    offending.append(f"{name}: {cls.__name__}: {', '.join(attributes)}")
        self.assertFalse(offending, "Core model extensions:\n" + "\n".join(sorted(offending)))
