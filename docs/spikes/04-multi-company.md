# 穿刺 4：两家公司（TAB Entertainment 与 AUSHAREU）

日期：2026-11-11　对应：任务 4.0（`docs/design/4.0-multi-company.md`），规格 `docs/spec/phase4.md` 第 J 节
结论：**可行**。网站结构不变，顾客一个账号通用两个网站；有两个缺口要在实现中补上（后台按公司隔离、Q Club 的 My Account 显示了 AUSHARE 订单），还有两个需要你决定的事项（第五节）。

## 一、环境

| 项目 | 内容 |
|---|---|
| 两家公司的演示副本 | `qclub_spike_co`：从演示库复制，新建 "TAB Entertainment Pty Ltd (Test)"（AUD、澳洲），Q Club 网站改到新公司，AUSHARE 留在原公司。AUSHARE 侧加一件测试商品并启用银行转账；另建一个只能访问 AUSHARE 公司的后台员工 |
| 两家公司的测试库 | `qclub_spike_base` / `qclub_spike_test`：测试基础库做同样的拆分后，安装模块并运行全部测试 |
| 生产库副本演练 | 从本机 `qclub_prodcopy` 复制出 `qclub_prodsplit`，用生产实际运行的 Odoo 版本（`203c9270`）操作；演练后已删除，`qclub_prodcopy` 未改动 |

全部在本机 Docker 中进行，没有接触生产服务器。输出只记录计数和配置，不含客户数据。

## 二、七个问题的结果

| # | 问题 | 结果 |
|---|---|---|
| 1 | 跨公司登录 | ✅ 两个方向都可以。AUSHARE 公司的老顾客能登录 Q Club，看网格、提交预约，打开 My Bookings & Players；在 Q Club 注册的顾客能登录 AUSHARE，加购物车、填地址，用银行转账下单成功 |
| 2 | 新注册顾客归属 | 在 Q Club 注册 → 账号属于 TAB Entertainment；在 AUSHARE 注册 → 属于 AUSHAREU。联系人不绑定公司。Odoo 的欢迎邮件按网站显示公司名（Q Club 注册时显示 TAB Entertainment） |
| 3 | Q Club 的 My Account 是否显示 AUSHARE 订单 | ❌ **会显示**：Q Club 上有 "Your Orders"、"Your Invoices" 卡片，`/my/orders` 列出了顾客在 AUSHARE 的订单。AUSHARE 侧不显示 Q Club 内容，`/my/billiard` 返回 404 ✅ |
| 4 | 只能访问 AUSHAREU 的后台用户 | ❌ **能看到** Q Club 的全部桌台（3）、预约（119）、帖子（79）和配置，和预期一致：模块现在只按用户组控制 |
| 5 | 邮件和页面上的公司信息 | 本模块的预约邮件用 Q Club 自己的版式，不显示公司名 ✅；Odoo 自带邮件按网站公司显示 ✅ |
| 6 | 现有测试 | ✅ 两家公司环境下 208 个测试全部通过，`iso-check` 无差异；演示副本上 e2e 44 项全部通过 |
| 7 | 生产库副本演练 | ✅ 用生产版本代码新建公司、装澳洲科目表（7 个日记账、21 个税）、改 Q Club 网站归属，全部成功；AUSHARE 公司的日记账和支付方式不变。指纹有 5 行差异，见第三节 |

## 三、需要注意的发现

1. **商品必须保持不绑定公司。** 穿刺一开始给测试商品绑了 AUSHARE 公司，结果在 Q Club 注册的顾客登录 AUSHARE 后看不到这件商品（没登录的访客反而看得到），这是 Odoo 的多公司规则。生产副本里 AUSHARE 的 61 个商品**全部没有绑定公司**，所以生产上没有这个问题。以后在 AUSHARE 新建商品也要保持不绑定公司，这条会写进迁移清单和运维说明。
2. **两个网站要分别登录。** 两个网站域名不同，登录状态不共享。从 Q Club 跳到 AUSHARE 要再登录一次，用同一个账号，不用重新注册。这和是否分公司无关。如果希望免登录跳转，需要单点登录，另作需求评估。
3. **新建公司时 Odoo 会自动给新公司复制一套停用的支付方式**（银行转账 3 个、PayPal、Stripe 各 1 个，全部停用）。AUSHARE 的支付方式前后完全一致。但现有的 AUSHARE 指纹不区分支付方式属于哪家公司，所以报出了 5 行差异。实现时要让指纹只比较 AUSHARE 公司的支付方式（需要你批准修改 `tools/iso_fingerprint.sql`）。
4. 在 `odoo shell` 里第一次新建公司时出现过一次 `KeyError: 'res.partner.image_1024'`，重跑后成功，原因未查明。生产上建公司走后台界面，迁移清单会注明出错时如何确认和重试。
5. 生产副本的现状：Q Club 网站（id 3）和 AUSHARE 都属于 AUSHAREU；库里共 3 家公司（另两家来自 Odoo 演示数据）；已装 `payment_stripe` 但未启用。

## 四、实现要做的（任务 4.0 的正式部分，由 Codex 编写）

- **后台按公司隔离（CO-002）**：本模块所有模型加多公司记录规则，按记录所属网站的公司限制；只能访问 AUSHAREU 的用户看不到 Q Club 的数据和菜单。门户顾客走现有路由，不受影响。
- **Q Club 的 My Account（CO-004）**：按第五节第 1 条处理。
- **测试环境**（已获批准）：`docker/seed_websites.py` 建出两家公司；`docker/demo_data.py` 让员工能访问 TAB Entertainment，演示账号覆盖跨网站登录。
- **指纹**：按第五节第 2 条修改。
- **测试**：CO-001 至 CO-006，把 CO 加入覆盖检查。
- **迁移清单** `docs/deploy/company-split.md`：新建公司（名称、ABN、地址、AUD、澳洲科目表）、改 Q Club 网站归属、员工公司权限、商品保持不绑定公司、迁移后的检查。

## 五、需要你决定

1. **Q Club 的 My Account 显示哪些订单和发票**：建议**只显示 Q Club 所属公司（TAB Entertainment）的单据**。这样 AUSHARE 的购物记录只在 AUSHARE 显示，以后 Q Club 开的收据或发票会自然出现在 Q Club。这个过滤只在 Q Club 网站生效，AUSHARE 的页面输出不变。
2. **修改 AUSHARE 指纹 `tools/iso_fingerprint.sql`**：支付方式只比较属于 AUSHARE 公司的那些。其他比较项不变。同意吗？
