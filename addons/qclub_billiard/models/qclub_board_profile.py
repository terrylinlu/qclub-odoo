import re

from psycopg2.errors import UniqueViolation

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class QclubBoardProfile(models.Model):
    _name = "qclub.board.profile"
    _description = "Board Nickname"
    _rec_name = "nickname"

    website_id = fields.Many2one("website", required=True, ondelete="cascade")
    partner_id = fields.Many2one("res.partner", required=True, ondelete="restrict")
    nickname = fields.Char(required=True)
    active = fields.Boolean(default=True)

    _partner_uniq = models.Constraint("UNIQUE(website_id, partner_id)",
                                      "Each customer can only have one nickname per website.")
    _nickname_uniq = models.UniqueIndex("(website_id, lower(nickname))")

    @staticmethod
    def _normalize_nickname(value):
        # Only ASCII spaces are normalized; tabs and other whitespace remain invalid.
        return re.sub(" +", " ", value.strip(" ")) if isinstance(value, str) else value

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(vals, nickname=self._normalize_nickname(vals.get("nickname", ""))) for vals in vals_list]
        # Validate even empty/missing values before SQL's required-field check,
        # so every nickname error uses the constraint's English messages.
        for vals in vals_list:
            self.new({"nickname": vals["nickname"]})._check_nickname()
        try:
            with self.env.cr.savepoint():
                records = super().create(vals_list)
                records.flush_recordset()
                return records
        except UniqueViolation as error:
            if error.diag.constraint_name == "qclub_board_profile_nickname_uniq":
                raise ValidationError(_("This nickname is already taken.")) from error
            raise

    def write(self, vals):
        vals = dict(vals)
        if "nickname" in vals:
            vals["nickname"] = self._normalize_nickname(vals["nickname"])
            self.new({"nickname": vals["nickname"]})._check_nickname()
        try:
            with self.env.cr.savepoint():
                result = super().write(vals)
                self.flush_recordset()
                return result
        except UniqueViolation as error:
            if error.diag.constraint_name == "qclub_board_profile_nickname_uniq":
                raise ValidationError(_("This nickname is already taken.")) from error
            raise

    @api.constrains("nickname")
    def _check_nickname(self):
        for profile in self:
            nickname = profile.nickname or ""
            if not 2 <= len(nickname) <= 20:
                raise ValidationError(_("Nickname must be 2 to 20 characters."))
            if "@" in nickname or len(re.findall(r"[0-9]", nickname)) >= 7:
                raise ValidationError(_("Nickname cannot be an email address or phone number."))
            if not re.fullmatch(r"[A-Za-z0-9 _-]+", nickname):
                raise ValidationError(_("Nickname can only contain letters, numbers, spaces, underscores and hyphens."))
            if any(word in nickname.lower() for word in ("admin", "staff", "qclub")):
                raise ValidationError(_("This nickname is not allowed."))

    def _public_data(self):
        self.ensure_one()
        return {"nickname": self.nickname}
