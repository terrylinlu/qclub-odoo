"""Moderation routes, database invariants, and back-office permissions."""
import json
from datetime import timedelta

from freezegun import freeze_time
from psycopg2.errors import CheckViolation, UniqueViolation

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import HttpCase, tagged
from odoo.tests.common import new_test_user
from odoo.tools import mute_logger

from . import test_board_posts


@tagged("post_install", "-at_install")
@freeze_time("2026-11-01 00:00:00")
class TestBoardModeration(HttpCase):
    rpc = test_board_posts.TestBoardPosts.rpc
    login = test_board_posts.TestBoardPosts.login

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
                                   groups="base.group_portal", name="Other Player")
        self.booking = self.env["qclub.booking"].create({
            "table_id": self.table.id, "partner_id": self.customer.partner_id.id,
            "start": "2026-11-06 12:30:00", "duration_hours": 2,
        })
        self.booking.action_confirm()
        self.Post = self.env["qclub.board.post"]
        self.values = {"booking_id": self.booking.id, "message": "<script>alert(1)</script> https://example.invalid",
                       "level": "intermediate", "players_needed": 2}
        self.env.flush_all()
        self.post_record = self.Post.create(self.values)
        self.Application = self.env["qclub.board.application"]
        self.Reply = self.env["qclub.board.reply"]
        self.Report = self.env["qclub.board.report"]
        self.Ban = self.env["qclub.board.ban"]
        self.staff = new_test_user(self.env, login="moderation-staff", groups="qclub_billiard.group_billiard_staff")
        self.manager = new_test_user(self.env, login="moderation-manager", groups="qclub_billiard.group_billiard_manager")

    def report(self, **values):
        return self.Report.create({"website_id": self.website.id, "reporter_id": self.other.partner_id.id,
                                   "post_id": self.post_record.id, "reason": "spam", **values})

    def ban(self, **values):
        return self.Ban.with_user(self.manager).create({
            "website_id": self.website.id, "partner_id": self.other.partner_id.id, "reason": "Private reason", **values,
        })

    def test_brd_021_dismiss_closes_report_without_hiding(self):
        reply = self.env["qclub.board.reply"].create({
            "post_id": self.post_record.id, "partner_id": self.other.partner_id.id, "message": "Fine reply",
        })
        report = self.env["qclub.board.report"].create({
            "website_id": self.website.id, "reporter_id": self.customer.partner_id.id,
            "reply_id": reply.id, "reason": "other",
        })
        result = report.with_user(self.staff).action_dismiss()
        self.assertEqual(result["params"]["message"], "Report dismissed. The content is still visible.")
        self.assertEqual(report.state, "resolved")
        self.assertEqual(report.resolved_by, self.staff)
        self.assertFalse(reply.hidden)
        self.assertTrue(report.create_date)

    def test_brd_020_database_xor_unique_reasons_and_note(self):
        for reason in ("spam", "abuse", "personal_information", "other"):
            with self.env.cr.savepoint() as sp:
                self.assertEqual(self.report(reason=reason).reason, reason)
                sp.rollback()
        reply = self.Reply.create({"post_id": self.post_record.id, "partner_id": self.customer.partner_id.id,
                                   "message": "Original reply"})
        for values in ({"post_id": False}, {"reply_id": reply.id}):
            with self.assertRaises(CheckViolation), mute_logger("odoo.sql_db"), self.env.cr.savepoint():
                self.report(**values)
        for target in ({}, {"post_id": False, "reply_id": reply.id}):
            self.report(**target)
            with self.assertRaises(UniqueViolation), mute_logger("odoo.sql_db"), self.env.cr.savepoint():
                self.report(**target)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.report(reporter_id=self.customer.partner_id.id, note="x" * 501)

    def test_brd_020_brd_025_brd_026_brd_027_report_http(self):
        params = {"post": self.post_record.id, "reason": "abuse", "note": "<script>plain</script>"}
        self.assertEqual(self.rpc("post/report", **params).json()["result"]["error"], "login_required")
        token = self.login(other=True)
        self.assertEqual(self.rpc("post/report", **params).json()["result"]["error"], "csrf")
        self.assertEqual(self.rpc("post/report", **dict(params, note="x" * 501), csrf_token=token).json()["result"]["error"], "validation")
        self.assertIn("id", self.rpc("post/report", **params, csrf_token=token).json()["result"])
        duplicate = self.rpc("post/report", **params, csrf_token=token).json()["result"]
        self.assertEqual(duplicate["error"], "duplicate")
        self.assertTrue(duplicate["message"])
        self.assertEqual(self.Report.search([("reporter_id", "=", self.other.partner_id.id)]).note, params["note"])
        self.assertNotIn(params["note"], json.dumps(self.rpc("post", post=self.post_record.id).json()))
        self.post_record.action_hide()
        self.assertEqual(self.rpc("post/report", **params, csrf_token=token).json()["result"]["error"], "validation")
        for model in (self.Report, self.Ban):
            for operation in ("read", "write", "create", "unlink"):
                for user in (self.other, self.website.user_id):
                    with self.assertRaises(AccessError):
                        model.with_user(user).check_access(operation)
        self.website.domain = False
        self.env.flush_all()
        self.other_site.domain = self.base_url()
        self.env.registry.clear_cache()
        self.assertEqual(self.rpc("post/report", **params, csrf_token=token).status_code, 404)

    def test_brd_021_moderation_permissions_audit_and_queue(self):
        report = self.report()
        reply = self.Reply.create({"post_id": self.post_record.id, "partner_id": self.other.partner_id.id,
                                   "message": "Preserve original"})
        for record in (self.post_record, reply):
            with self.assertRaises(AccessError):
                record.with_user(self.staff).write({"message": "Tampered"})
            with self.assertRaises(AccessError):
                record.with_user(self.staff).write({"hidden": True})
            with self.assertRaises(AccessError):
                record.with_user(self.other).action_hide()
            record.with_user(self.staff).action_hide()
            self.assertTrue(record.hidden)
            self.assertEqual(record.hidden_by, self.staff)
            self.assertTrue(record.hidden_at)
            record.with_user(self.staff).action_restore()
            self.assertFalse(record.hidden)
            self.assertEqual(record.hidden_by, self.staff)
        with self.assertRaises(AccessError):
            report.with_user(self.other).action_hide_and_resolve()
        with self.assertRaises(AccessError):
            report.with_user(self.other).action_dismiss()
        self.assertFalse(report.content_hidden)
        result = report.with_user(self.staff).action_hide_and_resolve()
        self.assertEqual(result["params"]["message"], "Content hidden and report resolved.")
        report.invalidate_recordset()
        self.assertTrue(report.content_hidden)
        self.assertTrue((report.post_id or report.reply_id).hidden)
        self.assertEqual(report.state, "resolved")
        self.assertEqual(report.resolved_by, self.staff)
        self.assertTrue(report.resolved_at)
        for record in (report, reply, self.post_record, self.ban()):
            for user in (self.staff, self.manager):
                with self.assertRaises(AccessError):
                    record.with_user(user).unlink()
        with self.assertRaises(AccessError):
            report.with_user(self.staff).write({"note": "Tampered"})
        with self.assertRaises(AccessError):
            self.Ban.with_user(self.staff).check_access("read")
        self.assertIn("search_default_new", self.env.ref("qclub_billiard.qclub_board_report_action").context)

    def test_brd_022_hidden_post_reply_all_customer_surfaces(self):
        reply = self.Reply.create({"post_id": self.post_record.id, "partner_id": self.other.partner_id.id,
                                   "message": "SECRET REPLY"})
        self.login()
        reply.with_user(self.staff).action_hide()
        detail = self.rpc("post", post=self.post_record.id).json()["result"]
        self.assertEqual(detail["replies"][0]["message"], "This reply was removed.")
        self.assertNotIn("SECRET REPLY", json.dumps(detail))
        self.assertNotIn(self.other.name, json.dumps(detail))
        self.assertNotIn("SECRET REPLY", self.url_open("/my/billiard").text)
        self.assertEqual(reply.message, "SECRET REPLY")
        self.post_record.with_user(self.staff).action_hide()
        board = self.rpc("board", date="2026-11-06").json()["result"]
        self.assertEqual(board["posts"], [])
        self.assertEqual(board["own_bookings"], [])
        self.assertEqual(self.rpc("post", post=self.post_record.id).json()["result"],
                         {"error": "not_found", "message": "This post is unavailable."})
        self.assertNotIn("Find players", self.url_open("/billiard/booking/confirmation/" + self.booking.name).text)
        self.assertNotIn("post=" + str(self.post_record.id), self.url_open("/my/billiard").text)
        self.post_record.with_user(self.staff).action_restore()
        self.assertEqual(self.rpc("post", post=self.post_record.id).json()["result"]["message"], self.values["message"])

    def test_brd_023_ban_expiry_site_scope_and_four_actions_only(self):
        with self.assertRaises(AccessError):
            self.Ban.with_user(self.staff).create({"website_id": self.website.id,
                                                  "partner_id": self.other.partner_id.id, "reason": "Denied"})
        ban = self.ban()
        with self.assertRaises(UniqueViolation), mute_logger("odoo.sql_db"), self.env.cr.savepoint():
            self.ban()
        token = self.login(other=True)
        for route in ("post/create", "post/reply", "post/apply", "post/report"):
            result = self.rpc(route, csrf_token=token).json()["result"]
            self.assertEqual(result["error"], "banned")
            self.assertEqual(result["message"], "Your account can't post on the board. Please contact Q Club.")
        self.assertIn("message", self.rpc("post", post=self.post_record.id).json()["result"])
        self.assertEqual(self.rpc("post/withdraw", csrf_token=token).json()["result"]["error"], "validation")
        ban.until = fields.Datetime.now() - timedelta(seconds=1)
        self.assertFalse(self.Ban._is_banned(self.website, self.other.partner_id))
        ban.until = False
        ban.website_id = self.other_site
        self.assertFalse(self.Ban._is_banned(self.website, self.other.partner_id))
        self.assertTrue(self.Ban._is_banned(self.other_site, self.other.partner_id))
        self.assertEqual(self.booking.state, "confirmed")

    def test_brd_024_four_models_combined_window_config_and_customer_scope(self):
        self.config.board_rate_limit = 3
        token = self.login(other=True)
        for route, values in (("post/reply", {"message": "One", "accept_terms": True}),
                              ("post/apply", {}), ("post/report", {"reason": "spam"})):
            self.assertIn("id", self.rpc(route, post=self.post_record.id, csrf_token=token, **values).json()["result"])
        count = self.Reply.search_count([])
        result = self.rpc("post/reply", post=self.post_record.id, message="Four", csrf_token=token).json()["result"]
        self.assertEqual(result["message"], "You're doing that too often. Please try again shortly.")
        self.assertEqual(self.Reply.search_count([]), count)
        self.config.board_rate_limit = 4
        self.assertIn("id", self.rpc("post/reply", post=self.post_record.id, message="Four", csrf_token=token).json()["result"])
        # create_date uses the DB clock even under freeze_time; age it explicitly.
        self.env.cr.execute("UPDATE qclub_board_reply SET create_date = %s WHERE partner_id = %s",
                            [fields.Datetime.now() - timedelta(seconds=61), self.other.partner_id.id])
        self.Reply.invalidate_model(["create_date"])
        self.assertIn("id", self.rpc("post/reply", post=self.post_record.id, message="After window", csrf_token=token).json()["result"])
        owner_token = self.login()
        self.assertIn("id", self.rpc("post/reply", post=self.post_record.id, message="Other customer",
                                    csrf_token=owner_token, accept_terms=True).json()["result"])

    def test_brd_020_brd_027_foreign_and_hidden_reply_targets(self):
        kind = self.env["qclub.table.type"].create({"name": "Other board type", "website_id": self.other_site.id})
        table = self.table.copy({"website_id": self.other_site.id, "type_id": kind.id})
        self.env["qclub.opening.hours"]._load_default_hours(self.other_site)
        booking = self.env["qclub.booking"].create({
            "table_id": table.id, "partner_id": self.customer.partner_id.id,
            "start": "2026-11-06 12:30:00", "duration_hours": 2,
        })
        booking.action_confirm()
        foreign = self.Post.create(dict(self.values, booking_id=booking.id))
        reply = self.Reply.create({"post_id": foreign.id, "partner_id": self.customer.partner_id.id,
                                   "message": "Other website"})
        token = self.login(other=True)
        for target in ({"post": foreign.id}, {"reply": reply.id}):
            self.assertEqual(self.rpc("post/report", **target, reason="other", csrf_token=token).json()["result"]["error"], "validation")
        local = self.Reply.create({"post_id": self.post_record.id, "partner_id": self.customer.partner_id.id,
                                   "message": "Local reply"})
        local.action_hide()
        self.assertEqual(self.rpc("post/report", reply=local.id, reason="other", csrf_token=token).json()["result"]["error"], "validation")
        local.action_restore()
        self.assertIn("id", self.rpc("post/report", reply=local.id, reason="other", csrf_token=token).json()["result"])
        self.assertEqual(self.rpc("post/report", reply=local.id, reason="other", csrf_token=token).json()["result"]["error"], "duplicate")

    def test_brd_023_banned_customers_can_manage_existing_applications_and_bookings(self):
        application = self.Application.create({"post_id": self.post_record.id, "partner_id": self.other.partner_id.id})
        self.ban(partner_id=self.customer.partner_id.id)
        self.ban()
        owner_token = self.login()
        self.assertEqual(self.rpc("application/decide", application=application.id, action="accept",
                                  csrf_token=owner_token).json()["result"], {"ok": True})
        self.assertEqual(self.url_open("/billiard/booking/confirmation/" + self.booking.name).status_code, 200)
        token = self.login(other=True)
        self.assertEqual(self.rpc("post/withdraw", application=application.id, csrf_token=token).json()["result"], {"ok": True})
        self.assertEqual(self.rpc("post/reply", csrf_token="bad").json()["result"]["error"], "csrf")
        self.assertEqual(self.booking.state, "confirmed")

    def test_brd_024_post_counts_default_limit_and_ban_precedes_limit(self):
        self.assertEqual(self.config.board_rate_limit, 5)
        self.config.board_rate_limit = 1
        token = self.login()
        result = self.rpc("post/create", csrf_token=token).json()["result"]
        self.assertEqual(result["error"], "rate_limit")  # fixture's post counts too
        self.ban(partner_id=self.customer.partner_id.id)
        self.assertEqual(self.rpc("post/create", csrf_token=token).json()["result"]["error"], "banned")

    def test_brd_021_brd_027_backoffice_visibility_and_portal_scoped_rules(self):
        from unittest.mock import patch
        from odoo.addons.website.models import ir_http

        report = self.report()
        ban = self.ban()
        for record, user in ((report, self.staff), (ban, self.manager)):
            for site in (self.website, self.other_site):
                with patch.object(ir_http, "get_request_website", return_value=site):
                    self.assertIn(record.id, self.env[record._name].with_user(user).with_context(website_id=site.id).search([]).ids)
        for model in ("post", "terms", "report", "ban"):
            rule = self.env.ref("qclub_billiard.rule_qclub_board_%s_website" % model)
            self.assertEqual(rule.groups, self.env.ref("base.group_portal"))
        menu = self.env.ref("qclub_billiard.menu_billiard_board_ban")
        self.assertNotIn(menu.id, self.env["ir.ui.menu"].with_user(self.staff)._visible_menu_ids())
        self.assertIn(menu.id, self.env["ir.ui.menu"].with_user(self.manager)._visible_menu_ids())
