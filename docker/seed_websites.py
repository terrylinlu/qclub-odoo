# 在 `odoo shell` 中运行（env 由 shell 提供）。
# 测试网站分别属于 AUSHARE 和 TAB Entertainment。
Website = env["website"]

with env.cr.savepoint():
    aud = env.ref("base.AUD")
    aud.active = True
    env.company.currency_id = aud
env.company.partner_id.tz = "Australia/Adelaide"

for name, domain in (("AUSHARE", "https://aushare.test"), ("Q Club", "https://qclub.test")):
    if not Website.search([("name", "=", name)], limit=1):
        Website.create({"name": name, "domain": domain})

aushare = Website.search([("name", "=", "AUSHARE")], limit=1)
aushare.company_id.name = "AUSHAREU PTY LTD (Test)"
qclub = Website.search([("name", "=", "Q Club")], limit=1)
company = env["res.company"].search([("name", "=", "TAB Entertainment Pty Ltd (Test)")], limit=1)
if not company:
    company = env["res.company"].with_context(no_vat_validation=True).create({
        "name": "TAB Entertainment Pty Ltd (Test)", "currency_id": aud.id,
        "country_id": env.ref("base.au").id, "vat": "00 000 000 000",
        "street": "1 Test Street", "city": "Adelaide", "zip": "5000",
    })
company.partner_id.tz = "Australia/Adelaide"
qclub.company_id = company
env.ref("base.user_admin").write({"company_ids": [(4, company.id)]})
print("Q Club website id =", qclub.id, "(生产库中为 3；测试代码不得硬编码，应按名称查找)")
env.cr.commit()
