"""Joining stays on the board; booking and customer privacy remain unchanged."""
import json
from unittest.mock import patch

from freezegun import freeze_time
from lxml import html
from psycopg2.errors import UniqueViolation

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import HttpCase, tagged
from odoo.tests.common import new_test_user
from odoo.tools import mute_logger

from . import test_board_posts


@tagged("post_install", "-at_install")
@freeze_time("2026-11-01 00:00:00")
class TestBoardJoin(HttpCase):
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

    def apply(self, **values):
        return self.Application.create({"post_id": self.post_record.id,
                                        "partner_id": self.other.partner_id.id, **values})

    def test_brd_010_brd_029_reply_boundaries_closed_login_csrf_terms(self):
        for message in ("", " ", "x" * 501):
            with self.assertRaises(ValidationError), self.env.cr.savepoint():
                self.Reply.create({"post_id": self.post_record.id, "partner_id": self.other.partner_id.id,
                                   "message": message})
        for message in ("x", "x" * 500):
            self.Reply.create({"post_id": self.post_record.id, "partner_id": self.other.partner_id.id,
                               "message": message})
        params = {"post": self.post_record.id, "message": "hello"}
        self.assertEqual(self.rpc("post/reply", **params).json()["result"]["error"], "login_required")
        token = self.login(other=True)
        self.assertEqual(self.rpc("post/reply", **params).json()["result"]["error"], "csrf")
        self.assertEqual(self.rpc("post/reply", **params, csrf_token=token).json()["result"]["error"], "validation")
        self.assertIn("id", self.rpc("post/reply", **params, csrf_token=token,
                                     accept_terms=True).json()["result"])
        self.post_record.state = "closed"
        self.assertEqual(self.rpc("post/reply", **params, csrf_token=token).json()["result"]["error"], "validation")

    def test_brd_011_database_unique_withdraw_reapply_and_terminal_states(self):
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.apply(partner_id=self.customer.partner_id.id)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.apply(message="x" * 201)
        application = self.apply(message="x" * 200)
        with self.assertRaises(UniqueViolation), mute_logger("odoo.sql_db"), self.env.cr.savepoint():
            self.apply()
        application._transition("withdraw", self.other.partner_id)
        second = self.apply()
        second._transition("decline", self.customer.partner_id)
        with self.assertRaises(UniqueViolation), mute_logger("odoo.sql_db"), self.env.cr.savepoint():
            self.apply()
        with self.assertRaises(ValidationError):
            second._transition("accept", self.customer.partner_id)
        third = new_test_user(self.env, login="join-removed", groups="base.group_portal", name="Removed Player")
        removed = self.apply(partner_id=third.partner_id.id)
        removed._transition("accept", self.customer.partner_id)
        removed._transition("remove", self.customer.partner_id)
        with self.assertRaises(UniqueViolation), mute_logger("odoo.sql_db"), self.env.cr.savepoint():
            self.apply(partner_id=third.partner_id.id)
        with self.assertRaises(ValidationError):
            removed._transition("withdraw", third.partner_id)

    def test_brd_012_brd_013_brd_014_transitions_capacity_booking_unchanged(self):
        fields = ["start", "end", "duration_hours", "table_id", "state", "table_fee", "deposit_amount"]
        before = self.booking.read(fields)
        count = self.env["qclub.booking"].search_count([])
        self.post_record.players_needed = 1
        application = self.apply()
        with self.assertRaises(ValidationError):
            application._transition("accept", self.other.partner_id)
        application._transition("accept", self.customer.partner_id)
        self.assertEqual(self.post_record._summary(False)["remaining"], 0)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.apply(partner_id=self.env.user.partner_id.id)
        with self.assertRaises(ValidationError):
            application._transition("decline", self.customer.partner_id)
        with freeze_time("2026-11-06 12:30:00"):
            for action, partner in (("withdraw", self.other.partner_id), ("remove", self.customer.partner_id)):
                with self.assertRaises(ValidationError):
                    application._transition(action, partner)
        application._transition("remove", self.customer.partner_id)
        self.assertEqual(self.booking.read(fields), before)
        self.assertEqual(self.env["qclub.booking"].search_count([]), count)

    def test_brd_015_transactional_close(self):
        for target in ("cancelled", "no_show", "expired"):
            with self.env.cr.savepoint() as savepoint:
                if target == "expired":
                    # A pending booking cannot normally have a post; exercise historical data.
                    self.env.cr.execute("UPDATE qclub_booking SET state='pending' WHERE id=%s", [self.booking.id])
                    self.booking.invalidate_recordset()
                self.booking.write({"state": target})
                self.assertEqual(self.post_record.state, "closed")
                savepoint.rollback()
            self.assertEqual(self.post_record.state, "open")
            self.assertEqual(self.booking.state, "confirmed")

    def test_brd_003_brd_025_brd_026_brd_027_application_detail_privacy_and_routes(self):
        application = self.apply(message="PRIVATE <script>alert(1)</script>")
        self.Reply.create({"post_id": self.post_record.id, "partner_id": self.other.partner_id.id,
                           "message": "<script>alert(1)</script>"})
        public = self.rpc("post", post=self.post_record.id).json()["result"]
        self.assertNotIn("PRIVATE", json.dumps(public))
        self.assertEqual(public["replies"][0]["display_name"], "Q Club Player")
        token = self.login(other=True)
        own = self.rpc("post", post=self.post_record.id).json()["result"]
        self.assertEqual(own["application"]["id"], application.id)
        self.assertNotIn("applications", own)
        result = self.rpc("application/decide", application=application.id, action="accept",
                          csrf_token=token).json()["result"]
        self.assertEqual(result["error"], "validation")
        result = self.rpc("post/apply", post=self.post_record.id, csrf_token=token,
                          accept_terms=True).json()["result"]
        self.assertEqual(result["error"], "duplicate")
        self.login()
        owner = self.rpc("post", post=self.post_record.id).json()["result"]
        self.assertEqual(owner["applications"][0]["message"], application.message)
        for model in (self.Application, self.Reply):
            for operation in ("read", "create", "write", "unlink"):
                with self.assertRaises(AccessError):
                    model.with_user(self.other).check_access(operation)
        self.config.online_board = False
        for route in ("post/reply", "post/apply", "post/withdraw", "application/decide"):
            self.assertEqual(self.rpc(route).status_code, 404)

    def test_brd_017_brd_018_brd_019_notification_events_and_failure(self):
        self.config.booking_email_from = "Q Club <board@example.invalid>"
        self.other.partner_id.email = "applicant@example.invalid"
        Mail = self.env["mail.mail"]
        previous = Mail.search([])
        application = self.apply()
        application._transition("accept", self.customer.partner_id)
        self.booking.write({"start": "2026-11-07 12:30:00", "duration_hours": 1})
        self.assertEqual(self.post_record._summary(False)["hours"], 1)
        self.booking.action_cancel()
        mails = Mail.search([]) - previous
        self.assertEqual(len(mails), 4)
        self.assertEqual(mails.mapped("email_to").count(self.other.partner_id.email), 3)
        for mail in mails:
            self.assertIn("/billiard/booking?date=", mail.body_html)
            self.assertIn("post=", mail.body_html)
            self.assertNotIn(self.booking.name, mail.body_html)
            self.assertNotIn("AUSHARE", mail.body_html)
            self.assertNotIn(self.customer.partner_id.email, mail.body_html)
        self.config.booking_email_from = False
        self.post_record._queue_email("accepted", self.other.partner_id, self.customer.partner_id)
        self.assertEqual(Mail.search([]) - previous, mails)
        self.config.booking_email_from = "Q Club <board@example.invalid>"
        with patch.object(type(Mail), "create", side_effect=RuntimeError("queue failed")), mute_logger(
            "odoo.addons.qclub_billiard.models.qclub_board",
        ):
            self.post_record._queue_email("accepted", self.other.partner_id, self.customer.partner_id)

    def test_brd_011_brd_012_brd_026_brd_029_http_apply_decide_withdraw(self):
        params = {"post": self.post_record.id}
        self.assertEqual(self.rpc("post/apply", **params).json()["result"]["error"], "login_required")
        token = self.login(other=True)
        self.assertEqual(self.rpc("post/apply", **params, csrf_token=token).json()["result"]["error"], "validation")
        result = self.rpc("post/apply", **params, csrf_token=token, accept_terms=True,
                          partner_id=self.customer.partner_id.id, state="accepted").json()["result"]
        application = self.Application.browse(result["id"])
        self.assertEqual(application.partner_id, self.other.partner_id)
        self.assertEqual(application.state, "pending")
        owner_token = self.login()
        for route, arguments in (
            ("post/apply", params), ("post/withdraw", {"application": application.id}),
            ("application/decide", {"application": application.id, "action": "accept"}),
        ):
            self.assertEqual(self.rpc(route, **arguments).json()["result"]["error"], "csrf")
        self.assertEqual(self.rpc("post/withdraw", application=application.id,
                                  csrf_token=owner_token).json()["result"]["error"], "validation")
        self.assertEqual(self.rpc("application/decide", application=application.id, action="accept",
                                  csrf_token=owner_token).json()["result"], {"ok": True})
        application.invalidate_recordset()
        self.assertEqual(application.state, "accepted")
        token = self.login(other=True)
        self.assertEqual(self.rpc("post/withdraw", application=application.id,
                                  csrf_token=token).json()["result"], {"ok": True})
        application.invalidate_recordset()
        self.assertEqual(application.state, "withdrawn")
        # Terms accepted on apply also authorize replies, and withdrawal permits reapply.
        self.assertIn("id", self.rpc("post/reply", **params, message="hello", csrf_token=token).json()["result"])
        self.assertIn("id", self.rpc("post/apply", **params, csrf_token=token).json()["result"])
        self.assertEqual(self.env["qclub.board.terms"].search_count([
            ("partner_id", "=", self.other.partner_id.id), ("website_id", "=", self.website.id),
        ]), 1)

    def test_brd_003_brd_025_third_customer_cannot_see_application_content(self):
        third = new_test_user(self.env, login="board-test-third", password="board-test",
                              groups="base.group_portal", name="Third Player")
        application = self.apply(message="PRIVATE APPLICATION")
        application._transition("accept", self.customer.partner_id)
        self.authenticate(third.login, "board-test")
        detail = self.rpc("post", post=self.post_record.id).json()["result"]
        self.assertIsNone(detail["application"])
        self.assertNotIn("applications", detail)
        self.assertNotIn("PRIVATE APPLICATION", json.dumps(detail))
        self.assertEqual(detail["accepted"], [{"display_name": self.other.partner_id.name}])
        self.assertEqual(set(detail["accepted"][0]), {"display_name"})
        for private in (self.customer.partner_id.email, self.customer.partner_id.phone,
                        self.customer.login, self.other.login, self.booking.name):
            self.assertNotIn(private, json.dumps(detail))

    def test_brd_026_brd_027_new_models_staff_rules_and_aushare_routes(self):
        from odoo.addons.website.models import ir_http

        application = self.apply()
        reply = self.Reply.create({"post_id": self.post_record.id, "partner_id": self.other.partner_id.id,
                                   "message": "hello"})
        staff = new_test_user(self.env, login="join-staff", groups="qclub_billiard.group_billiard_staff")
        manager = new_test_user(self.env, login="join-manager", groups="qclub_billiard.group_billiard_manager")
        for record in (application, reply):
            # Back-office users work across websites (see test_sec_003_staff_has_no_website_filter);
            # the website rule applies to portal users only.
            for site in (self.website, self.other_site, self.website):
                with patch.object(ir_http, "get_request_website", return_value=site):
                    model = self.env[record._name].with_user(staff).with_context(website_id=site.id)
                    self.assertIn(record.id, model.search([]).ids)
            with patch.object(ir_http, "get_request_website", return_value=self.website):
                with self.assertRaises(AccessError):
                    record.with_user(staff).write({"message": "not allowed"})
                for user in (staff, manager):
                    with self.assertRaises(AccessError):
                        record.with_user(user).unlink()
                record.with_user(manager).write({"message": "manager update"})
        self.website.domain = False
        self.env.flush_all()  # Clear first: website domains are unique row by row.
        self.other_site.domain = self.base_url()
        self.env.registry.clear_cache()
        for route in ("post/reply", "post/apply", "post/withdraw", "application/decide"):
            self.assertEqual(self.rpc(route).status_code, 404)

    def test_brd_019_email_is_sent_after_commit_not_queued_for_cron(self):
        self.config.booking_email_from = "Q Club <board@example.invalid>"
        self.other.partner_id.email = "applicant@example.invalid"
        self.post_record.partner_id.email = "owner@example.invalid"
        with patch.object(type(self.env["mail.mail"]), "send_after_commit") as send:
            self.apply()
        send.assert_called_once()

    def test_brd_019_no_sender_sends_nothing(self):
        self.config.booking_email_from = False
        with patch.object(type(self.env["mail.mail"]), "send_after_commit") as send:
            self.apply()
        send.assert_not_called()

    def test_brd_017_brd_018_brd_019_all_events_recipients_text_and_no_reply_mail(self):
        self.config.booking_email_from = "Q Club <board@example.invalid>"
        self.other.partner_id.write({"email": "applicant@example.invalid", "name": "<script>Player</script>"})
        Mail = self.env["mail.mail"]
        previous = Mail.search([])

        def one_mail(recipient, event):
            nonlocal previous
            current = Mail.search([])
            added = current - previous
            self.assertEqual(len(added), 1)
            self.assertEqual(added.email_to, recipient.email)
            self.assertEqual(added.email_from, self.config.booking_email_from)
            self.assertIn(event, added.subject)
            self.assertIn(self.website.domain, added.body_html)
            self.assertIn(self.booking.table_id.name, added.body_html)
            self.assertIn(self.booking._time_label(), html.fromstring(added.body_html).text_content())
            for private in (self.customer.partner_id.email, self.other.partner_id.email,
                            self.customer.partner_id.phone, self.booking.name, "AUSHARE", self.env.company.name):
                self.assertNotIn(private, added.body_html)
            self.assertNotIn("<script>", added.body_html)
            previous = current
            return added

        application = self.apply()
        one_mail(self.customer.partner_id, "New application")
        # Pending applicants do not receive booking changes.
        self.booking.write({"duration_hours": 1})
        self.assertEqual(Mail.search([]), previous)
        application._transition("decline", self.customer.partner_id)
        one_mail(self.other.partner_id, "Application declined")
        another = new_test_user(self.env, login="join-mail-third", groups="base.group_portal", name="Third Player")
        another.partner_id.email = "third@example.invalid"
        accepted = self.apply(partner_id=another.partner_id.id)
        one_mail(self.customer.partner_id, "New application")
        accepted._transition("accept", self.customer.partner_id)
        one_mail(another.partner_id, "Application accepted")
        other_table = self.table.copy({"name": "Changed board table"})
        self.booking.write({"table_id": other_table.id})
        one_mail(another.partner_id, "Booking time or table changed")
        self.assertEqual(self.post_record._summary(False)["table_name"], other_table.name)
        self.booking.write({"table_id": other_table.id})
        self.assertEqual(Mail.search([]), previous)
        accepted._transition("remove", self.customer.partner_id)
        one_mail(another.partner_id, "Removed from the post")
        self.Reply.create({"post_id": self.post_record.id, "partner_id": self.customer.partner_id.id,
                           "message": "no notification"})
        self.assertEqual(Mail.search([]), previous)
        with freeze_time("2026-11-06 12:30:00"):
            self.assertEqual(self.rpc("post", post=self.post_record.id).json()["result"]["state"], "closed")
        self.assertEqual(Mail.search([]), previous)

    def test_brd_018_brd_019_queue_failure_does_not_break_application_action(self):
        self.config.booking_email_from = "Q Club <board@example.invalid>"
        self.other.partner_id.email = "applicant@example.invalid"
        Mail = self.env["mail.mail"]
        with patch.object(type(Mail), "create", side_effect=RuntimeError("queue failed")), mute_logger(
            "odoo.addons.qclub_billiard.models.qclub_board",
        ):
            application = self.apply()
            application._transition("accept", self.customer.partner_id)
            self.assertEqual(application.state, "accepted")
            self.booking.action_cancel()
            self.assertEqual(self.post_record.state, "closed")

    def test_brd_015_brd_017_booking_without_post_does_not_call_board_actions(self):
        # Use another table to leave the posted booking untouched.
        table = self.table.copy({"name": "No board table"})
        booking = self.env["qclub.booking"].create({
            "table_id": table.id, "partner_id": self.customer.partner_id.id,
            "start": "2026-11-06 12:30:00", "duration_hours": 2,
        })
        with patch.object(type(self.Post), "_notify_accepted", side_effect=AssertionError("no post hook")):
            booking.action_confirm()
            booking.write({"duration_hours": 1})
            booking.action_cancel()
        self.assertEqual(booking.state, "cancelled")
        self.assertEqual(self.post_record.state, "open")
