from psycopg2.errors import CheckViolation, UniqueViolation

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import new_test_user, tagged
from odoo.tools import mute_logger

from .common import BilliardCase


@tagged("post_install", "-at_install")
class TestBoardProfile(BilliardCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Profile = cls.env["qclub.board.profile"]
        cls.customer = new_test_user(cls.env, login="board-customer", groups="base.group_portal")
        cls.other = new_test_user(cls.env, login="board-other", groups="base.group_portal")

    def _profile(self, nickname="Cue Player", website=None, partner=None):
        return self.Profile.create({"website_id": (website or self.qclub).id,
                                    "partner_id": (partner or self.customer.partner_id).id,
                                    "nickname": nickname})

    def test_brd_001_normalization_partner_unchanged_and_one_per_site(self):
        partner = self.customer.partner_id
        before = partner.read(["name", "email", "phone"])
        profile = self._profile("  Cue   Player  ")
        self.assertEqual(profile.nickname, "Cue Player")
        self.assertEqual(partner.read(["name", "email", "phone"]), before)
        with self.assertRaises(UniqueViolation), mute_logger("odoo.sql_db"), self.env.cr.savepoint():
            self._profile("Another")
            self.env.flush_all()
        self.assertTrue(self._profile(website=self.aushare))

    def test_brd_002_validation_boundaries_and_messages(self):
        cases = [
            ("", "Nickname must be 2 to 20 characters."),
            ("   ", "Nickname must be 2 to 20 characters."),
            ("ab\tcd", "Nickname can only contain letters, numbers, spaces, underscores and hyphens."),
            ("a", "Nickname must be 2 to 20 characters."),
            ("a" * 21, "Nickname must be 2 to 20 characters."),
            ("a@b.com", "Nickname cannot be an email address or phone number."),
            ("12 345 67", "Nickname cannot be an email address or phone number."),
            ("Cue.AdMin", "Nickname can only contain letters, numbers, spaces, underscores and hyphens."),
            ("玩家", "Nickname can only contain letters, numbers, spaces, underscores and hyphens."),
            ("Café", "Nickname can only contain letters, numbers, spaces, underscores and hyphens."),
            ("<img>", "Nickname can only contain letters, numbers, spaces, underscores and hyphens."),
        ] + [(word, "This nickname is not allowed.") for word in ("ADMIN", "myStaff", "QclubFan")]
        for nickname, message in cases:
            with self.subTest(nickname=nickname), self.assertRaisesRegex(ValidationError, message):
                with self.env.cr.savepoint():
                    self._profile(nickname)
        profile = self._profile("ab")
        profile.nickname = "a" * 20
        profile.nickname = "Player_2-OK"
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            profile.nickname = "bad!"

    def test_brd_002_database_case_insensitive_unique_and_write(self):
        self._profile("CueMaster")
        other = self._profile("Other", partner=self.other.partner_id)
        for operation in (lambda: self._profile("cuemaster", partner=self.env["res.partner"].create({"name": "Third Player"})),
                          lambda: other.write({"nickname": "CUEMASTER"})):
            with self.assertRaisesRegex(ValidationError, "This nickname is already taken."), \
                    mute_logger("odoo.sql_db"), self.env.cr.savepoint():
                operation()
        # Bypass ORM validation to prove the case-folded index exists in PostgreSQL.
        with self.assertRaises(UniqueViolation), mute_logger("odoo.sql_db"), self.env.cr.savepoint():
            self.env.cr.execute("UPDATE qclub_board_profile SET nickname = %s WHERE id = %s", ("cUeMaStEr", other.id))
        self.assertTrue(self._profile("cuemaster", website=self.aushare))

    def test_brd_003_public_data_only_nickname(self):
        self.assertEqual(self._profile()._public_data(), {"nickname": "Cue Player"})

    def test_brd_026_model_access(self):
        profile = self._profile()
        for user in (self.customer, self.env.ref("base.public_user"), self.internal):
            for operation in (lambda: profile.with_user(user).read(["nickname"]),
                              lambda: profile.with_user(user).write({"nickname": "New Name"}),
                              lambda: self.Profile.with_user(user).create({
                                  "website_id": self.qclub.id, "partner_id": self.other.partner_id.id,
                                  "nickname": "New Player"}),
                              lambda: profile.with_user(user).unlink()):
                with self.assertRaises(AccessError), self.env.cr.savepoint():
                    operation()
        self.assertEqual(profile.with_user(self.staff).nickname, "Cue Player")
        with self.assertRaises(AccessError):
            profile.with_user(self.staff).write({"nickname": "Other Name"})
        profile.with_user(self.manager).write({"nickname": "Other Name"})
        with self.assertRaises(AccessError):
            profile.with_user(self.manager).unlink()

    def test_brd_027_rules_and_own_model_views(self):
        rule = self.env.ref("qclub_billiard.rule_qclub_board_profile_portal")
        self.assertIn("website.id", rule.domain_force)
        self.assertIn("user.partner_id.id", rule.domain_force)
        for name in ("board_page", "board_nickname"):
            self.assertEqual(self.env.ref("qclub_billiard." + name).model, "qclub.booking")
        self.assertEqual(self.Profile._table, "qclub_board_profile")

    def test_brd_028_defaults_validation_sql_and_permissions(self):
        config = self.env["qclub.config"]._get_for_website(self.qclub)
        self.assertFalse(config.online_board)
        self.assertFalse(config.board_requires_login)
        self.assertEqual(config.board_max_players, 3)
        self.assertEqual(config.board_rate_limit, 5)
        for field in ("board_max_players", "board_rate_limit"):
            for value in (0, -1):
                with self.assertRaises(ValidationError), self.env.cr.savepoint():
                    config.write({field: value})
                with self.assertRaises(CheckViolation), mute_logger("odoo.sql_db"), self.env.cr.savepoint():
                    self.env.cr.execute(f'UPDATE qclub_config SET {field} = %s WHERE id = %s', (value, config.id))
        with self.assertRaises(AccessError):
            config.with_user(self.staff).write({"online_board": True})
        config.with_user(self.manager).write({"online_board": True, "board_requires_login": True})
