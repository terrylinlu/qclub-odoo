from psycopg2.errors import CheckViolation

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import tagged
from odoo.tools import mute_logger

from .common import BilliardCase


@tagged("post_install", "-at_install")
class TestBoardConfig(BilliardCase):
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
