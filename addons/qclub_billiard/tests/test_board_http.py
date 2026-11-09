import json
from urllib.parse import parse_qs, urlparse

from lxml import html
from odoo.tests import HttpCase, tagged
from odoo.tests.common import new_test_user


@tagged("post_install", "-at_install")
class TestBoardHttp(HttpCase):
    def setUp(self):
        super().setUp()
        self.qclub = self.env["website"].search([("name", "=", "Q Club")], limit=1)
        self.aushare = self.env["website"].search([("name", "=", "AUSHARE")], limit=1)
        self.config = self.env["qclub.config"]._get_for_website(self.qclub)
        self.config.online_board = True
        self.customer = new_test_user(self.env, login="board-http", password="board-test", groups="base.group_portal")
        self.other = new_test_user(self.env, login="board-http-other", password="board-test", groups="base.group_portal")
        self.other.partner_id.write({"name": "Private Board Customer", "email": "private-board@example.invalid",
                                    "phone": "+61412345678"})
        self._website(self.qclub)

    def _website(self, website):
        self.env["website"].search([("domain", "=", self.base_url())]).write({"domain": False})
        website.domain = self.base_url()
        self.env.flush_all()
        self.env.registry.clear_cache()
        self.opener.cookies.clear()

    def _login(self):
        self.authenticate(self.customer.login, "board-test")
        page = html.fromstring(self.url_open("/billiard/board/nickname").content)
        return page.xpath('//input[@name="csrf_token"]/@value')[0]

    def test_brd_001_brd_003_brd_026_own_record_and_privacy(self):
        token = self._login()
        foreign = self.env["qclub.board.profile"].create({"website_id": self.aushare.id,
                   "partner_id": self.customer.partner_id.id, "nickname": "Foreign Player"})
        other = self.env["qclub.board.profile"].create({"website_id": self.qclub.id,
                 "partner_id": self.other.partner_id.id, "nickname": "Other Player"})
        result = self.url_open("/billiard/board/nickname", data={"csrf_token": token, "nickname": "Cue Player",
                 "partner_id": self.other.partner_id.id, "website_id": self.aushare.id, "id": other.id})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(urlparse(result.url).path, "/billiard/board")
        self.assertIn("Cue Player", result.text)
        self.assertEqual(other.nickname, "Other Player")
        self.assertEqual(foreign.nickname, "Foreign Player")
        self.assertNotIn("Foreign Player", result.text)
        for path in ("/billiard/board", "/billiard/board/nickname"):
            response = self.url_open(path)
            # BRD-003 protects customers from each other; the site header may show the viewer's own name.
            for secret in (self.other.partner_id.name, self.other.partner_id.email, self.other.partner_id.phone):
                self.assertNotIn(secret, response.text)
        profile = self.env["qclub.board.profile"].search([("partner_id", "=", self.customer.partner_id.id),
                                                                    ("website_id", "=", self.qclub.id)])
        self.assertEqual(profile.website_id, self.qclub)

    def test_brd_002_conflict_and_validation_through_route(self):
        token = self._login()
        self.env["qclub.board.profile"].create({"website_id": self.qclub.id,
                 "partner_id": self.other.partner_id.id, "nickname": "Taken Name"})
        for nickname, message in (("", "Nickname must be 2 to 20 characters."),
                                  ("taken name", "This nickname is already taken."),
                                  ("a@b.com", "Nickname cannot be an email address or phone number."),
                                  ("<script>", "Nickname can only contain letters, numbers, spaces, underscores and hyphens.")):
            result = self.url_open("/billiard/board/nickname", data={"csrf_token": token, "nickname": nickname})
            self.assertEqual(result.status_code, 200)
            self.assertIn(message, result.text)
            document = html.fromstring(result.content)
            self.assertEqual(document.xpath('//input[@name="nickname"]/@value'), [nickname])
            self.assertFalse(document.xpath('//script[not(@src) and normalize-space(text())="<script>"]'))
            self.assertNotIn('value="<script>"', result.text)
        self.url_open("/billiard/board/nickname", data={"csrf_token": token, "nickname": "Original"})
        result = self.url_open("/billiard/board/nickname", data={"csrf_token": token, "nickname": "TAKEN NAME"})
        self.assertIn("This nickname is already taken.", result.text)
        profile = self.env["qclub.board.profile"].search([("partner_id", "=", self.customer.partner_id.id)])
        self.assertEqual(profile.nickname, "Original")

    def test_brd_026_csrf_and_rpc_denied(self):
        self._login()
        self.assertEqual(self.url_open("/billiard/board/nickname", data={"nickname": "No Token"}).status_code, 400)
        for method, args in (("search_read", [[]]), ("create", [{"nickname": "RPC Player",
                "website_id": self.qclub.id, "partner_id": self.customer.partner_id.id}])):
            result = self.url_open(f"/web/dataset/call_kw/qclub.board.profile/{method}", data=json.dumps({
                "jsonrpc": "2.0", "method": "call", "id": 1,
                "params": {"model": "qclub.board.profile", "method": method, "args": args, "kwargs": {}},
            }), headers={"Content-Type": "application/json"}).json()
            self.assertIn("error", result)
            self.assertEqual(result["error"]["data"]["name"], "odoo.exceptions.AccessError")

    def test_brd_026_safe_next_and_login_return(self):
        response = self.url_open("/billiard/board/nickname", allow_redirects=False)
        target = parse_qs(urlparse(response.headers["Location"]).query)["redirect"][0]
        self.assertEqual(target, "/billiard/board/nickname")
        token = self._login()
        for target in ("//evil.example", "https://evil.example", "javascript:alert(1)",
                       "/\\evil.example", "\\evil.example", "/%2f%2fevil.example", "/%5cevil.example"):
            response = self.url_open("/billiard/board/nickname", data={"csrf_token": token,
                                     "nickname": "Safe Player", "next": target}, allow_redirects=False)
            self.assertEqual(response.headers["Location"], "/billiard/board")
        response = self.url_open("/billiard/board/nickname", data={"csrf_token": token,
                                 "nickname": "Safe Player", "next": "/billiard/board?ok=1"}, allow_redirects=False)
        self.assertEqual(response.headers["Location"], "/billiard/board?ok=1")

    def test_brd_027_disabled_websites_all_routes_404(self):
        for website in (self.qclub, self.aushare):
            self.env["qclub.config"]._get_for_website(website).online_board = False
            self._website(website)
            for path in ("/billiard/board", "/billiard/board/nickname"):
                self.assertEqual(self.url_open(path).status_code, 404)
            # Supply a real session token so CSRF does not mask the website gate.
            token = html.fromstring(self.url_open("/web/login").content).xpath('//input[@name="csrf_token"]/@value')[0]
            self.assertEqual(self.url_open("/billiard/board/nickname", data={"csrf_token": token,
                             "nickname": "Blocked"}).status_code, 404)

    def test_brd_028_login_switch(self):
        self.assertEqual(self.url_open("/billiard/board").status_code, 200)
        self.config.board_requires_login = True
        self.env.flush_all()
        result = self.url_open("/billiard/board", allow_redirects=False)
        self.assertEqual(parse_qs(urlparse(result.headers["Location"]).query)["redirect"], ["/billiard/board"])
        self._login()
        self.assertEqual(self.url_open("/billiard/board").status_code, 200)
