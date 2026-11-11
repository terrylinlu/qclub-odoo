from odoo.tests.common import TransactionCase, new_test_user


def site_companies(env):
    return env["website"].search([("name", "in", ["Q Club", "AUSHARE"])]).company_id.ids


class BilliardCase(TransactionCase):
    """Shared fixtures. Websites are looked up by name, never by hard-coded id (AGENTS.md section 7)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Website = cls.env["website"]
        cls.qclub = Website.search([("name", "=", "Q Club")], limit=1)
        cls.aushare = Website.search([("name", "=", "AUSHARE")], limit=1)
        assert cls.qclub and cls.aushare, "test database must contain the Q Club and AUSHARE websites"

        cls.staff = new_test_user(cls.env, login="test-billiard-staff", groups="qclub_billiard.group_billiard_staff",
                                  company_ids=[(6, 0, site_companies(cls.env))], company_id=cls.aushare.company_id.id)
        cls.manager = new_test_user(
            cls.env, login="test-billiard-manager", groups="qclub_billiard.group_billiard_manager",
            company_ids=[(6, 0, site_companies(cls.env))], company_id=cls.aushare.company_id.id,
        )
        cls.internal = new_test_user(cls.env, login="test-plain-internal", groups="base.group_user",
                                     company_ids=[(6, 0, site_companies(cls.env))], company_id=cls.aushare.company_id.id)

    @classmethod
    def _make_type(cls, name="Snooker", website=None):
        return cls.env["qclub.table.type"].create({"name": name, "website_id": (website or cls.qclub).id})
