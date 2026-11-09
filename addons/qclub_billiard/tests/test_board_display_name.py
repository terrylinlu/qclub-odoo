from odoo.tests.common import new_test_user, tagged

from ..models.qclub_board import board_display_name
from .common import BilliardCase


@tagged("post_install", "-at_install")
class TestBoardDisplayName(BilliardCase):
    def test_brd_001_display_name_and_partner_unchanged(self):
        partner = self.env["res.partner"].create({"name": "  Cue Player  "})
        before = partner.read()
        self.assertEqual(board_display_name(partner, True), "Q Club Player")
        self.assertEqual(board_display_name(partner, False), "Cue Player")
        self.assertEqual(partner.read(), before)

    def test_brd_002_name_boundaries(self):
        for name, expected in (
            (False, "Q Club Player"),
            ("", "Q Club Player"),
            ("   ", "Q Club Player"),
            ("Cue@Player", "Q Club Player"),
            ("  Player 12 34 56  ", "Player 12 34 56"),
            ("Player 12 34 567", "Q Club Player"),
            ("Player １２３４５６７", "Q Club Player"),
        ):
            with self.subTest(name=name):
                partner = self.env["res.partner"].new({"name": name})
                self.assertEqual(board_display_name(partner, False), expected)
                self.assertEqual(board_display_name(partner, True), "Q Club Player")

    def test_brd_003_contact_details_never_used(self):
        customer = new_test_user(
            self.env, login="board-login@example.invalid", groups="base.group_portal",
        )
        partner = customer.partner_id
        partner.write({"name": "Private Player", "email": "board-email@example.invalid",
                       "phone": "0412345678"})
        for public in (False, True):
            result = board_display_name(partner, public)
            self.assertEqual(result, "Q Club Player" if public else "Private Player")
            for private in (customer.login, partner.email, partner.phone):
                self.assertNotIn(private, result)
            if public:
                self.assertNotIn(partner.name, result)

    def test_brd_003_anonymous_does_not_read_name(self):
        class UnreadablePartner:
            @property
            def name(self):
                raise AssertionError("Anonymous viewers must not read partner.name")

        self.assertEqual(board_display_name(UnreadablePartner(), True), "Q Club Player")
