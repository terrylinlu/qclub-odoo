from odoo.tests.common import tagged

from .common import BilliardCase


@tagged("post_install", "-at_install")
class TestGroups(BilliardCase):
    def test_sec_001_groups_exist_with_hierarchy(self):
        staff_group = self.env.ref("qclub_billiard.group_billiard_staff")
        manager_group = self.env.ref("qclub_billiard.group_billiard_manager")
        self.assertEqual(staff_group.name, "Billiard Staff")
        self.assertEqual(manager_group.name, "Billiard Manager")
        self.assertIn(self.env.ref("base.group_user"), staff_group.implied_ids, "staff must be internal users")
        self.assertIn(staff_group, manager_group.implied_ids, "manager must include all staff rights")

    def test_sec_001_effective_membership(self):
        self.assertTrue(self.manager.has_group("qclub_billiard.group_billiard_staff"))
        self.assertTrue(self.staff.has_group("qclub_billiard.group_billiard_staff"))
        self.assertFalse(self.staff.has_group("qclub_billiard.group_billiard_manager"))
        self.assertFalse(self.internal.has_group("qclub_billiard.group_billiard_staff"))

    def test_sec_001_admin_is_billiard_manager(self):
        self.assertTrue(self.env.ref("base.user_admin").has_group("qclub_billiard.group_billiard_manager"))
