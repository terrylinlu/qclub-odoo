import json
from unittest.mock import patch

from freezegun import freeze_time
from lxml import html
from psycopg2.errors import UniqueViolation

from odoo.addons.website.models import ir_http
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import HttpCase, tagged
from odoo.tests.common import new_test_user
from odoo.tools import mute_logger

from .common import site_companies


@tagged("post_install", "-at_install")
@freeze_time("2026-11-01 00:00:00")
class TestBoardPosts(HttpCase):
    def setUp(self):
        super().setUp()
        self.website = self.env["website"].search([("name", "=", "Q Club")], limit=1)
        self.other_site = self.env["website"].search([("name", "=", "AUSHARE")], limit=1)
        self.env["website"].search([("domain", "=", self.base_url())]).write({"domain": False})
        self.env.flush_all()  # Clear first: website domains are unique row by row.
        self.website.domain = self.base_url()
        self.env.registry.clear_cache()
        self.config = self.env["qclub.config"]._get_for_website(self.website)
        self.config.write({"online_booking": True, "online_board": True, "board_requires_login": False})
        self.env["qclub.opening.hours"]._load_default_hours(self.website)
        kind = self.env["qclub.table.type"].create({"name": "Board type", "website_id": self.website.id})
        self.table = self.env["qclub.table"].create({
            "name": "Board table", "website_id": self.website.id, "type_id": kind.id, "hourly_price": 20,
        })
        self.customer = new_test_user(self.env, login="board-test-customer", password="board-test",
                                      groups="base.group_portal", name="Board Customer")
        self.customer.partner_id.write({"email": "board-contact@example.invalid", "phone": "0412345678"})
        self.other = new_test_user(self.env, login="board-test-other", password="board-test",
                                   groups="base.group_portal")
        self.booking = self.env["qclub.booking"].create({
            "table_id": self.table.id, "partner_id": self.customer.partner_id.id,
            "start": "2026-11-06 12:30:00", "duration_hours": 2,
        })
        self.booking.action_confirm()
        self.Post = self.env["qclub.board.post"]
        self.values = {"booking_id": self.booking.id, "message": "<script>alert(1)</script> https://example.invalid",
                       "level": "intermediate", "players_needed": 2}
        self.env.flush_all()

    def rpc(self, route, **params):
        self.env.flush_all()
        return self.url_open("/billiard/booking/" + route, data=json.dumps({
            "jsonrpc": "2.0", "method": "call", "id": 1, "params": params,
        }), headers={"Content-Type": "application/json"})

    def login(self, other=False):
        self.authenticate("board-test-other" if other else "board-test-customer", "board-test")
        page = html.fromstring(self.url_open("/billiard/booking").content)
        return page.xpath("//div[@data-csrf-token]/@data-csrf-token")[0]

    def test_brd_004_brd_026_brd_029_create_identity_csrf_terms_duplicate(self):
        self.assertEqual(self.rpc("post/create", **self.values).json()["result"]["error"], "login_required")
        token = self.login(other=True)
        self.assertEqual(self.rpc("post/create", **self.values).json()["result"]["error"], "csrf")
        self.assertEqual(self.rpc("post/create", **self.values, csrf_token=token,
                                  accept_terms=True).json()["result"]["error"], "validation")
        token = self.login()
        self.assertEqual(self.rpc("post/create", **self.values, csrf_token=token).json()["result"]["error"],
                         "validation")
        result = self.rpc("post/create", **self.values, csrf_token=token, accept_terms=True,
                          state="closed", table_id=0, start="2000-01-01").json()["result"]
        self.assertIn("id", result)
        self.assertEqual(self.Post.browse(result["id"]).state, "open")
        duplicate = self.rpc("post/create", **self.values, csrf_token=token).json()["result"]
        self.assertEqual(duplicate["error"], "duplicate")
        second = self.env["qclub.booking"].create({
            "table_id": self.table.id, "partner_id": self.customer.partner_id.id,
            "start": "2026-11-07 12:30:00", "duration_hours": 2,
        })
        second.action_confirm()
        self.assertIn("id", self.rpc("post/create", **dict(self.values, booking_id=second.id),
                                     csrf_token=token).json()["result"])
        self.assertEqual(self.env["qclub.board.terms"].search_count([
            ("partner_id", "=", self.customer.partner_id.id), ("website_id", "=", self.website.id),
        ]), 1)
        for model in ("qclub.board.post", "qclub.board.terms"):
            for operation in ("read", "create", "write", "unlink"):
                with self.assertRaises(AccessError):
                    self.env[model].with_user(self.customer).check_access(operation)

    def test_brd_004_database_unique_and_invalid_booking_states(self):
        for state, transitions in (
            ("pending", []), ("arrived", ["confirmed", "arrived"]),
            ("done", ["confirmed", "arrived", "done"]), ("cancelled", ["cancelled"]),
            ("expired", ["expired"]), ("no_show", ["confirmed", "no_show"]),
        ):
            with self.subTest(state=state), self.env.cr.savepoint() as savepoint:
                self.booking.action_cancel()
                booking = self.env["qclub.booking"].create({
                    "table_id": self.table.id, "partner_id": self.customer.partner_id.id,
                    "start": "2026-11-06 12:30:00", "duration_hours": 2,
                })
                for target in transitions:
                    booking.write({"state": target})
                with self.assertRaises(ValidationError), self.env.cr.savepoint():
                    self.Post.create(dict(self.values, booking_id=booking.id))
                savepoint.rollback()
        self.Post.create(self.values)
        with mute_logger("odoo.sql_db"), self.assertRaises(UniqueViolation), self.env.cr.savepoint():
            self.Post.create(self.values)

    def test_brd_005_message_level_players_boundaries(self):
        for values, exception in (({"message": " "}, ValidationError), ({"message": "a" * 501}, ValidationError),
                                  ({"level": "expert"}, ValueError), ({"players_needed": 0}, ValidationError),
                                  ({"players_needed": self.config.board_max_players + 1}, ValidationError)):
            with self.subTest(values=values), self.assertRaises(exception), self.env.cr.savepoint():
                self.Post.create(dict(self.values, **values))
        for message in ("x", "x" * 500):
            with self.env.cr.savepoint() as savepoint:
                self.assertEqual(self.Post.create(dict(self.values, message=message)).message, message)
                savepoint.rollback()

    def test_brd_001_brd_002_brd_003_brd_007_brd_008_brd_025_privacy_and_detail(self):
        post = self.Post.create(self.values)
        summary = self.rpc("board", date="2026-11-06").json()["result"]
        item = next(item for item in summary["posts"] if item["id"] == post.id)
        self.assertEqual(item["display_name"], "Q Club Player")
        self.assertEqual(item["hours"], 2)
        self.assertIn("Sat 7 Nov", item["time_label"])
        detail = self.rpc("post", post=post.id).json()["result"]
        self.assertEqual(detail["message"], self.values["message"])
        for private in (self.customer.name, "board-test-customer", "board-contact@example.invalid", "0412345678", self.booking.name):
            self.assertNotIn(private, json.dumps([summary, detail]))
        self.assertEqual(set(item), {"id", "table_id", "start", "hours", "time_label", "table_name",
                                     "display_name", "level", "remaining"})
        self.assertNotIn("booking_id", item)
        self.assertEqual(summary["own_bookings"], [])
        self.login()
        self.assertEqual(self.rpc("post", post=post.id).json()["result"]["display_name"], self.customer.name)
        self.customer.partner_id.name = "person@example.invalid"
        self.assertEqual(self.rpc("post", post=post.id).json()["result"]["display_name"], "Q Club Player")

    def test_brd_009_brd_027_gates_and_record_rules(self):
        post = self.Post.create(self.values)
        self.config.board_requires_login = True
        for route, params in (("board", {"date": "2026-11-06"}), ("post", {"post": post.id})):
            self.assertEqual(self.rpc(route, **params).json()["result"]["error"], "login_required")
        self.config.online_board = False
        for route in ("board", "post", "post/create"):
            self.assertEqual(self.rpc(route).status_code, 404)
        self.website.domain = False
        self.env.flush_all()  # Clear first: website domains are unique row by row.
        self.other_site.domain = self.base_url()
        self.env.registry.clear_cache()
        for route in ("board", "post", "post/create"):
            self.assertEqual(self.rpc(route).status_code, 404)
        for model in ("qclub.board.post", "qclub.board.terms"):
            rules = self.env["ir.rule"].search([("model_id.model", "=", model)])
            self.assertTrue(rules)
            self.assertTrue(all("website_id" in rule.domain_force for rule in rules))

    def test_brd_006_confirmation_entry_conditions(self):
        self.login()
        path = "/billiard/booking/confirmation/" + self.booking.name
        self.assertIn("Find players", self.url_open(path).text)
        with freeze_time("2026-11-06 12:30:00"):
            self.assertNotIn("Find players", self.url_open(path).text)
        self.config.online_board = False
        self.env.flush_all()
        self.assertNotIn("Find players", self.url_open(path).text)
        self.config.online_board = True
        self.env.flush_all()
        pending = self.env["qclub.booking"].create({
            "table_id": self.table.id, "partner_id": self.customer.partner_id.id,
            "start": "2026-11-07 12:30:00", "duration_hours": 2,
        })
        self.env.flush_all()
        self.assertNotIn("Find players", self.url_open("/billiard/booking/confirmation/" + pending.name).text)
        self.Post.create(self.values)
        self.assertNotIn("Find players", self.url_open(path).text)

    def test_brd_016_read_time_closure_without_cron(self):
        post = self.Post.create(self.values)
        with freeze_time("2026-11-06 12:30:00"):
            self.assertFalse(post._is_open())
            self.assertEqual(self.rpc("post", post=post.id).json()["result"]["state"], "closed")
            with self.assertRaises(ValidationError), self.env.cr.savepoint():
                self.Post.create(self.values)
        self.booking.action_cancel()
        self.assertFalse(post._is_open())
        self.assertNotIn(post.id, [p["id"] for p in self.rpc("board", date="2026-11-06").json()["result"]["posts"]])

    def test_brd_026_brd_027_staff_manager_permissions_and_actual_isolation(self):
        post = self.Post.create(self.values)
        terms = self.env["qclub.board.terms"].create({
            "website_id": self.website.id, "partner_id": self.customer.partner_id.id,
        })
        staff = new_test_user(self.env, login="board-staff", groups="qclub_billiard.group_billiard_staff",
                                    company_ids=[(6, 0, site_companies(self.env))], company_id=self.other_site.company_id.id)
        manager = new_test_user(self.env, login="board-manager", groups="qclub_billiard.group_billiard_manager",
                                    company_ids=[(6, 0, site_companies(self.env))], company_id=self.other_site.company_id.id)
        for record in (post, terms):
            for site in (self.website, self.other_site, self.website):
                with patch.object(ir_http, "get_request_website", return_value=site):
                    model = self.env[record._name].with_user(staff).with_context(website_id=site.id)
                    self.assertIn(record.id, model.search([]).ids)
            with patch.object(ir_http, "get_request_website", return_value=self.website):
                staff_record = record.with_user(staff).with_context(website_id=self.website.id)
                manager_record = record.with_user(manager).with_context(website_id=self.website.id)
                with self.assertRaises(AccessError):
                    staff_record.write({"website_id": self.website.id})
                for user_record in (staff_record, manager_record):
                    with self.assertRaises(AccessError):
                        user_record.unlink()
                field = "message" if record == post else "accepted_at"
                manager_record.write({field: record[field]})

    def test_brd_006_brd_008_brd_009_validated_restore_parameters(self):
        page = html.fromstring(self.url_open(
            "/billiard/booking?date=2026-11-06&post=javascript:alert(1)&booking=-1"
        ).content)
        self.assertEqual(page.xpath("//div[@data-board-post]/@data-board-post"), [""])
        self.assertEqual(page.xpath("//div[@data-board-booking]/@data-board-booking"), [""])
        self.login(other=True)
        summary = self.rpc("board", date="2026-11-06").json()["result"]
        self.assertEqual(summary["own_bookings"], [])
        for value in (None, True, -1, "1 OR 1=1"):
            self.assertEqual(self.rpc("post", post=value).json()["result"]["error"], "not_found")
        for value in (None, "2026-02-30", "2030-01-01", True):
            self.assertEqual(self.rpc("board", date=value).json()["result"]["error"], "invalid_date")
