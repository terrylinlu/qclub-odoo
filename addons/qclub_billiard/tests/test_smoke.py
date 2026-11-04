from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSmoke(TransactionCase):
    """环境冒烟测试：确认测试环境本身是对的。不对应任何业务需求编号。"""

    def test_000_module_installed(self):
        mod = self.env["ir.module.module"].search([("name", "=", "qclub_billiard")])
        self.assertEqual(mod.state, "installed")

    def test_001_two_websites_exist(self):
        """基础模板库里应有 Q Club 与 AUSHARE 两个不同的网站（按名称查找，不硬编码 id）。"""
        qclub = self.env["website"].search([("name", "=", "Q Club")], limit=1)
        aushare = self.env["website"].search([("name", "=", "AUSHARE")], limit=1)
        self.assertTrue(qclub)
        self.assertTrue(aushare)
        self.assertNotEqual(qclub, aushare)

    def test_002_btree_gist_available(self):
        self.env.cr.execute("SELECT 1 FROM pg_extension WHERE extname = 'btree_gist'")
        self.assertTrue(self.env.cr.fetchone(), "btree_gist 扩展未启用，防重复预约的排他约束无法创建")
