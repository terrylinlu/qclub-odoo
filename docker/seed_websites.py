# 在 `odoo shell` 中运行（env 由 shell 提供）。
# 目的：让测试库的结构贴近生产：Q Club 与 AUSHARE 共用一个公司，各有一个网站。
Website = env["website"]

with env.cr.savepoint():
    aud = env.ref("base.AUD")
    aud.active = True
    env.company.currency_id = aud
env.company.partner_id.tz = "Australia/Adelaide"

for name, domain in (("AUSHARE", "https://aushare.test"), ("Q Club", "https://qclub.test")):
    if not Website.search([("name", "=", name)], limit=1):
        Website.create({"name": name, "domain": domain})

qclub = Website.search([("name", "=", "Q Club")], limit=1)
print("Q Club website id =", qclub.id, "(生产库中为 3；测试代码不得硬编码，应按名称查找)")
env.cr.commit()
