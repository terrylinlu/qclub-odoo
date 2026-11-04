# 演示数据（DEMO-002 / DEMO-003）。在 `odoo shell -d qclub_demo` 中运行（env 由 shell 提供），由 `make demo` 调用。
#
# 原则：
# - 只用于本机一次性演示库 qclub_demo；数据全部是假数据，与真实桌台、价格无关
# - 幂等：按登录名 / 名称查找后再创建或更新，可重复执行
# - 演示记录名称带"【演示】"前缀，演示账号登录名以 demo- 开头
# - 账号密码为本机演示库的占位值（AGENTS.md 规则 2 例外），不得与任何真实环境相同
# - 尚未实现的模型（桌台、营业时间等）在对应任务中往下面的分段里补数据

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
    summary.append(f"网站 {name}（id={site.id}）-> {domain}")

ICP = env["ir.config_parameter"].sudo()
ICP.set_param("web.base.url", BACKEND_URL)
ICP.set_param("web.base.url.freeze", "True")

# ---- 账号 ----
env.ref("base.user_admin").password = ADMIN_PASSWORD
summary.append("管理员 admin")

Users = env["res.users"].with_context(active_test=False, no_reset_password=True)


def ensure_user(login, name, group_xmlid):
    group = env.ref(group_xmlid)
    user = Users.search([("login", "=", login)], limit=1)
    if not user:
        user = Users.create({"login": login, "name": name, "group_ids": [(6, 0, [group.id])]})
    user.write({"name": name, "active": True, "password": DEMO_PASSWORD, "tz": "Australia/Adelaide"})
    summary.append(f"账号 {login}（{name}）")
    return user


ensure_user("demo-staff", "【演示】员工 小王", "base.group_user")
ensure_user("demo-customer-a", "【演示】顾客 A", "base.group_portal")
ensure_user("demo-customer-b", "【演示】顾客 B", "base.group_portal")

# ---- 任务 1.1：权限组、桌台、配置 ----
# 建立"球厅员工"组后：把 demo-staff 加入该组
# 建立桌台模型后：中式八球、斯诺克、九球各 1 张（名称带"【演示】"，单价为演示假数据）

# ---- 任务 1.2：营业时间 ----
# 按规格第 G 节写入初始营业时间（周五、周六至次日 02:00）

# ---- 任务 1.3 起：演示预约 ----

env.cr.commit()
print("[demo] 演示数据已写入 " + DEMO_DB + "：")
for line in summary:
    print("  - " + line)
