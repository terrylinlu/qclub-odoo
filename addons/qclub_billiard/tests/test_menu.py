from odoo.tests.common import tagged

from .common import BilliardCase


@tagged("post_install", "-at_install")
class TestMenu(BilliardCase):
    def _visible(self, user):
        return set(self.env["ir.ui.menu"].with_user(user)._visible_menu_ids())

    def _menu(self, xmlid):
        return self.env.ref(f"qclub_billiard.{xmlid}").id

    def test_adm_001_staff_sees_billiards_menu(self):
        visible = self._visible(self.staff)
        for xmlid in ("menu_billiard_root", "menu_billiard_tables", "menu_billiard_configuration",
                      "menu_billiard_settings"):
            self.assertIn(self._menu(xmlid), visible, xmlid)
        self.assertNotIn(self._menu("menu_billiard_table_types"), visible, "table types are manager-only")

    def test_adm_001_manager_sees_all_billiards_menus(self):
        visible = self._visible(self.manager)
        for xmlid in ("menu_billiard_root", "menu_billiard_tables", "menu_billiard_settings",
                      "menu_billiard_table_types"):
            self.assertIn(self._menu(xmlid), visible, xmlid)

    def test_adm_001_other_internal_users_do_not_see_billiards(self):
        self.assertNotIn(self._menu("menu_billiard_root"), self._visible(self.internal))

    def test_adm_001_menu_names(self):
        root = self.env.ref("qclub_billiard.menu_billiard_root")
        self.assertEqual(root.name, "Billiards")
        child_names = root.child_id.mapped("name")
        # Later tasks add Opening Hours and Bookings, so only check what this task provides.
        self.assertIn("Tables", child_names)
        self.assertIn("Configuration", child_names)
        settings_children = self.env.ref("qclub_billiard.menu_billiard_configuration").child_id.mapped("name")
        self.assertIn("Settings", settings_children)
        self.assertIn("Table Types", settings_children)
