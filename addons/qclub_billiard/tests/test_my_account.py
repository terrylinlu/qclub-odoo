import json

from freezegun import freeze_time
from lxml import html

from odoo.tests import HttpCase, tagged
from odoo.tests.common import new_test_user


@tagged("post_install", "-at_install")
@freeze_time("2026-11-01 00:00:00")
class TestMyAccount(HttpCase):
    def setUp(self):
        super().setUp()
        self.site = self.env["website"].search([("name", "=", "Q Club")], limit=1)
        self.other_site = self.env["website"].search([("name", "=", "AUSHARE")], limit=1)
        self.config = self.env["qclub.config"]._get_for_website(self.site)
        self.config.write({"online_booking": True, "online_board": True})
        self.customer = new_test_user(self.env, login="account-customer", password="account-test",
                                      groups="base.group_portal", name="Account Customer")
        self.other = new_test_user(self.env, login="account-private-login", password="account-test",
                                   groups="base.group_portal", name="Other Player")
        self.other.partner_id.write({"email": "private-account@example.invalid", "phone": "0411222333"})
        self.env["qclub.opening.hours"]._load_default_hours(self.site)
        kind = self.env["qclub.table.type"].create({"name": "Account type", "website_id": self.site.id})
        self.table = self.env["qclub.table"].create({
            "name": "Account table", "website_id": self.site.id, "type_id": kind.id, "hourly_price": 20,
        })
        self.own = self.booking(self.customer, "2026-11-06 12:30:00")
        self.foreign = self.booking(self.other, "2026-11-07 12:30:00")
        self.post = self.env["qclub.board.post"].create({
            "booking_id": self.foreign.id, "message": "Other post", "players_needed": 2,
        })
        self.application = self.env["qclub.board.application"].create({
            "post_id": self.post.id, "partner_id": self.customer.partner_id.id,
        })
        self.reply = self.env["qclub.board.reply"].create({
            "post_id": self.post.id, "partner_id": self.other.partner_id.id,
            "message": "<script>window.accountXss=true</script>",
        })
        self.website(self.site)

    def booking(self, user, start):
        booking = self.env["qclub.booking"].create({
            "table_id": self.table.id, "partner_id": user.partner_id.id, "start": start, "duration_hours": 1,
        })
        booking.action_confirm()
        return booking

    def website(self, site):
        self.env["website"].search([("domain", "=", self.base_url())]).write({"domain": False})
        self.env.flush_all()
        site.domain = self.base_url()
        self.env.flush_all()
        self.env.registry.clear_cache()

    def reminders(self):
        self.env.flush_all()
        return self.url_open("/billiard/booking/reminders", data=json.dumps({
            "jsonrpc": "2.0", "method": "call", "id": 1, "params": {},
        }), headers={"Content-Type": "application/json"})

    def test_brd_030_card_login_return_and_website_gate(self):
        response = self.url_open("/my/billiard")
        self.assertIn("/web/login", response.url)
        self.assertIn("%2Fmy%2Fbilliard", response.url)
        self.authenticate("account-customer", "account-test")
        self.assertIn("My Bookings &amp; Players", self.url_open("/my").text)
        self.website(self.other_site)
        page = self.url_open("/my").text
        self.assertNotIn("/my/billiard", page)
        self.assertNotIn("My Bookings", page)
        self.assertEqual(self.url_open("/my/billiard").status_code, 404)
        self.assertEqual(self.reminders().status_code, 404)

    def test_brd_031_brd_032_brd_033_sections_privacy_escape_read_only_links(self):
        self.authenticate("account-customer", "account-test")
        models = ("qclub.booking", "qclub.board.post", "qclub.board.application", "qclub.board.reply")
        before = {model: self.env[model].search([]).read(["write_date"]) for model in models}
        response = self.url_open("/my/billiard")
        self.assertEqual(response.status_code, 200)
        doc = html.fromstring(response.content)
        for title in ("My bookings", "My posts", "My join requests", "Messages", "Waiting", "Other Player"):
            self.assertIn(title, doc.text_content())
        self.assertIn(self.own.name, doc.text_content())
        self.assertEqual(len(doc.xpath("//section[@id='qclub_my_bookings']/article")), 1)
        self.assertEqual(len(doc.xpath("//section[@id='qclub_my_applications']/article")), 1)
        for secret in (self.foreign.name, self.other.login, self.other.partner_id.email, self.other.partner_id.phone):
            self.assertNotIn(secret, response.text)
        self.assertIn(self.reply.message, doc.text_content())
        self.assertFalse(doc.xpath("//main//script[contains(text(), 'accountXss')]"))
        self.assertIn(f"/billiard/booking?date={self.foreign.business_date}&post={self.post.id}",
                      doc.xpath("//a/@href"))
        self.env.invalidate_all()
        self.assertEqual(before, {model: self.env[model].search([]).read(["write_date"]) for model in models})

    def test_brd_034_own_business_dates_only_no_accepted_application(self):
        self.assertEqual(self.reminders().json()["result"], {"dates": []})
        self.application._transition("accept", self.other.partner_id)
        self.authenticate("account-customer", "account-test")
        self.assertEqual(self.reminders().json()["result"], {"dates": [self.own.business_date.isoformat()]})
        self.own.action_cancel()
        self.assertEqual(self.reminders().json()["result"], {"dates": []})

    def test_brd_031_brd_032_latest_fifty_messages_and_own_post_counts(self):
        own_post = self.env["qclub.board.post"].create({
            "booking_id": self.own.id, "message": "My own post", "players_needed": 2,
        })
        self.env["qclub.board.application"].create({
            "post_id": own_post.id, "partner_id": self.other.partner_id.id,
        })
        for index in range(55):
            self.env["qclub.board.reply"].create({
                "post_id": own_post.id, "partner_id": self.other.partner_id.id,
                "message": f"Account message {index:02d}",
            })
        self.authenticate("account-customer", "account-test")
        self.env.flush_all()
        doc = html.fromstring(self.url_open("/my/billiard").content)
        messages = doc.xpath("//section[@id='qclub_my_messages']/article")
        self.assertEqual(len(messages), 50)
        self.assertIn("Account message 54", messages[0].text_content())
        self.assertIn("Account message 05", messages[-1].text_content())
        posts = doc.xpath("//section[@id='qclub_my_posts']/article")
        self.assertEqual(len(posts), 1)
        self.assertIn("Open", posts[0].text_content())
        self.assertIn("Waiting: 1", posts[0].text_content())
        self.assertIn("Accepted: 0 / 2", posts[0].text_content())
        with freeze_time("2026-11-06 12:30:00"):
            doc = html.fromstring(self.url_open("/my/billiard").content)
            self.assertIn("Closed", doc.xpath("//section[@id='qclub_my_posts']")[0].text_content())

    def test_brd_034_pending_lock_expiry_arrived_and_website_isolation(self):
        pending = self.env["qclub.booking"].create({
            "table_id": self.table.id, "partner_id": self.customer.partner_id.id,
            "start": "2026-11-08 12:30:00", "duration_hours": 1,
        })
        self.own.action_arrive()
        self.authenticate("account-customer", "account-test")
        expected = sorted([self.own.business_date.isoformat(), pending.business_date.isoformat()])
        self.assertEqual(self.reminders().json()["result"], {"dates": expected})
        with freeze_time("2026-11-01 00:11:00"):
            self.assertEqual(self.reminders().json()["result"], {"dates": [self.own.business_date.isoformat()]})
        self.website(self.other_site)
        other_config = self.env["qclub.config"]._get_for_website(self.other_site)
        other_config.online_booking = True
        self.assertEqual(self.reminders().json()["result"], {"dates": []})
        self.assertNotIn(self.own.name, self.url_open("/my/billiard").text)

    def test_brd_030_aushare_portal_output_identical_without_inherited_card(self):
        self.authenticate("account-customer", "account-test")
        self.website(self.other_site)
        # Compare only the card category: surrounding portal markup includes
        # per-request CSRF tokens, unrelated to this inherited view.
        def category():
            self.env.flush_all()
            doc = html.fromstring(self.url_open("/my").content)
            return html.tostring(doc.get_element_by_id("portal_common_category"))

        with_card_view = category()
        self.env.ref("qclub_billiard.portal_my_home_billiard").active = False
        self.assertEqual(with_card_view, category())

    def test_brd_034_cross_midnight_dst_business_date_and_window(self):
        with freeze_time("2026-10-03 00:00:00"):
            # Local Sunday 00:00 on the DST-change weekend belongs to Saturday's hours.
            booking = self.booking(self.customer, "2026-10-03 14:30:00")
            self.assertEqual(booking.business_date.isoformat(), "2026-10-03")
            self.authenticate("account-customer", "account-test")
            self.assertEqual(self.reminders().json()["result"], {"dates": ["2026-10-03"]})
        # Existing November reservations are outside October's booking window.
        with freeze_time("2026-10-04 22:00:00"):
            self.assertEqual(self.reminders().json()["result"], {"dates": []})

    def test_brd_031_upcoming_before_history_and_translated_state_labels(self):
        future = self.booking(self.customer, "2026-11-09 12:30:00")
        self.authenticate("account-customer", "account-test")
        self.env.flush_all()
        with freeze_time("2026-11-08 00:00:00"):
            doc = html.fromstring(self.url_open("/my/billiard").content)
            rows = doc.xpath("//section[@id='qclub_my_bookings']/article")
            self.assertEqual(len(rows), 2)
            self.assertIn(future.name, rows[0].text_content())
            self.assertIn(self.own.name, rows[1].text_content())
            self.assertIn("Confirmed", rows[0].text_content())
