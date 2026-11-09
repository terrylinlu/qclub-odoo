from urllib.parse import unquote, urlencode, urlsplit

from werkzeug.exceptions import NotFound

from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import request


class BilliardBoard(http.Controller):
    def _website_config(self):
        config = request.env["qclub.config"].sudo().search([
            ("website_id", "=", request.website.id), ("online_board", "=", True),
        ], limit=1)
        if not config:
            raise NotFound()
        return config

    def _login(self, target):
        return request.redirect("/web/login?" + urlencode({"redirect": target}))

    def _own_profile(self):
        # Only called after authenticating the customer. Ignore all submitted IDs.
        return request.env["qclub.board.profile"].sudo().with_context(active_test=False).search([
            ("website_id", "=", request.website.id),
            ("partner_id", "=", request.env.user.partner_id.id),
        ], limit=1)

    @staticmethod
    def _safe_next(value):
        if not isinstance(value, str):
            return "/billiard/board"
        decoded = value
        # Check encoded forms too, including nested encoding interpreted by intermediaries.
        while True:
            if (not decoded.startswith("/") or decoded.startswith("//") or "\\" in decoded
                    or any(ord(char) < 32 or ord(char) == 127 for char in decoded)):
                return "/billiard/board"
            try:
                parsed = urlsplit(decoded)
            except ValueError:
                return "/billiard/board"
            if parsed.scheme or parsed.netloc:
                return "/billiard/board"
            new = unquote(decoded)
            if new == decoded:
                return value
            decoded = new

    @http.route("/billiard/board", type="http", auth="public", website=True, sitemap=False, methods=["GET"])
    def board_page(self, **kwargs):
        config = self._website_config()
        public = request.env.user._is_public()
        if public and config.board_requires_login:
            return self._login("/billiard/board")
        profile = self._own_profile() if not public else None
        return request.render("qclub_billiard.board_page", {
            "profile_data": profile._public_data() if profile else {},
        })

    @http.route("/billiard/board/nickname", type="http", auth="public", website=True,
                sitemap=False, methods=["GET", "POST"])
    def nickname(self, nickname="", next=None, **kwargs):
        self._website_config()
        if request.env.user._is_public():
            return self._login("/billiard/board/nickname")
        profile = self._own_profile()
        target = self._safe_next(next)
        error = None
        if request.httprequest.method == "POST":
            try:
                with request.env.cr.savepoint():
                    if profile:
                        profile.write({"nickname": nickname})
                    else:
                        request.env["qclub.board.profile"].sudo().create({
                            "website_id": request.website.id,
                            "partner_id": request.env.user.partner_id.id, "nickname": nickname,
                        })
                return request.redirect(target)
            except ValidationError as exception:
                error = str(exception)
        else:
            nickname = profile._public_data()["nickname"] if profile else ""
        return request.render("qclub_billiard.board_nickname", {
            "nickname": nickname, "error": error, "next_path": target,
        })
