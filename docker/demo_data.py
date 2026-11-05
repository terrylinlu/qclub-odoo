# 演示数据（DEMO-002 / DEMO-003）。在 `odoo shell -d qclub_demo` 中运行（env 由 shell 提供），由 `make demo` 调用。
#
# 原则：
# - 只用于本机一次性演示库 qclub_demo；数据全部是假数据，与真实桌台、价格无关
# - 幂等：按登录名 / 名称查找后再创建或更新，可重复执行
# - 界面语言为英语：演示记录名称带 "[Demo]" 前缀，演示账号登录名以 demo- 开头
# - 账号密码为本机演示库的占位值（AGENTS.md 规则 2 例外），不得与任何真实环境相同
# - 后续任务往下面对应的分段里补数据

DEMO_DB = "qclub_demo"
if env.cr.dbname != DEMO_DB:
    raise SystemExit(f"REFUSED: 演示数据只能写入 {DEMO_DB}（当前: {env.cr.dbname}）")

DEMO_PASSWORD = "demo"     # 演示账号占位密码，仅本机演示库
ADMIN_PASSWORD = "admin"   # 管理员占位密码，仅本机演示库
BACKEND_URL = "http://localhost:8069"
SITE_DOMAINS = {
    "Q Club": "http://qclub.localhost:8069",
    "AUSHARE": "http://aushare.localhost:8069",
}

summary = []

# ---- 网站域名（DEMO-003）：用主机名区分两个品牌 ----
Website = env["website"]
for name, domain in SITE_DOMAINS.items():
    site = Website.search([("name", "=", name)], limit=1)
    if not site:
        raise SystemExit(f"缺少网站 {name}：请先 make demo-reset（基础模板库应含两个网站）")
    site.domain = domain
    summary.append(f"website {name} (id={site.id}) -> {domain}")
qclub = Website.search([("name", "=", "Q Club")], limit=1)

ICP = env["ir.config_parameter"].sudo()
ICP.set_param("web.base.url", BACKEND_URL)
ICP.set_param("web.base.url.freeze", "True")

# ---- 账号 ----
env.ref("base.user_admin").password = ADMIN_PASSWORD
summary.append("user admin (Billiard Manager)")

Users = env["res.users"].with_context(active_test=False, no_reset_password=True)


def ensure_user(login, name, group_xmlids):
    groups = [env.ref(x) for x in group_xmlids]
    user = Users.search([("login", "=", login)], limit=1)
    if not user:
        user = Users.create({"login": login, "name": name, "group_ids": [(6, 0, [groups[0].id])]})
    user.write({
        "name": name, "active": True, "password": DEMO_PASSWORD, "tz": "Australia/Adelaide",
        "group_ids": [(4, g.id) for g in groups],
    })
    summary.append(f"user {login} ({name})")
    return user


# 任务 1.1：demo-staff 加入 Billiard Staff 组（只读桌台和配置）
ensure_user("demo-staff", "[Demo] Staff Wang", ["base.group_user", "qclub_billiard.group_billiard_staff"])
ensure_user("demo-customer-a", "[Demo] Customer A", ["base.group_portal"])
ensure_user("demo-customer-b", "[Demo] Customer B", ["base.group_portal"])

# ---- 任务 1.1：球厅配置、桌台类型、桌台 ----
config = env["qclub.config"]._get_for_website(qclub)
summary.append(f"billiard settings for Q Club (deposit {config.deposit_ratio:g}%)")

TableType = env["qclub.table.type"].with_context(active_test=False)
Table = env["qclub.table"].with_context(active_test=False)
DEMO_TABLES = [
    # (类型, 桌台, 演示单价 AUD/小时 —— 假数据)
    ("[Demo] Chinese 8-Ball", "[Demo] Table 1", 20.0),
    ("[Demo] Snooker", "[Demo] Table 2", 30.0),
    ("[Demo] 9-Ball", "[Demo] Table 3", 25.0),
]
for seq, (type_name, table_name, price) in enumerate(DEMO_TABLES, start=1):
    table_type = TableType.search([("name", "=", type_name), ("website_id", "=", qclub.id)], limit=1)
    if not table_type:
        table_type = TableType.create({"name": type_name, "website_id": qclub.id, "sequence": seq})
    table = Table.search([("name", "=", table_name), ("website_id", "=", qclub.id)], limit=1)
    vals = {"type_id": table_type.id, "hourly_price": price, "sequence": seq, "active": True}
    if table:
        table.write(vals)
    else:
        Table.create(dict(vals, name=table_name, website_id=qclub.id))
    summary.append(f"table {table_name} ({type_name}, {price:g} AUD/h)")

# ---- 任务 1.2：营业时间 ----
# 按规格第 G 节写入初始营业时间（周五、周六至次日 02:00）

# ---- 任务 1.3 起：演示预约 ----

env.cr.commit()
print("[demo] demo data written to " + DEMO_DB + ":")
for line in summary:
    print("  - " + line)
