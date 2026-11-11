# 阶段 4 演示脚本：押金支付与资金流

状态：**已定稿**（2026-11-11 评审通过）
对应规格：`docs/spec/phase4.md`（PAY、RF、NS、ST）

## 启动与账号

- `make demo` 启动演示环境（任务 4.0 起为 12 张桌子：美式 $20、中式 $25、斯诺克 $30）。用 **Chrome 或 Edge** 打开。
- Stripe 测试密钥由脚本从 `~/.config/qclub/stripe-test.env` 写入演示库；付款通知由我在本机启动的转发程序送到演示环境，开始演示前我会确认它在运行。
- Stripe 控制台（测试模式）：https://dashboard.stripe.com/test/payments ，可核对付款和退款。

| 入口 | 地址 |
|---|---|
| Q Club 预约页 | http://qclub.localhost:8069/billiard/booking |
| AUSHARE 商城 | http://aushare.localhost:8069/shop |
| 后台 | http://localhost:8069/web/login |
| 邮件（Mailpit） | http://localhost:8025 |

演示账号（密码均为 `demo`）：`demo-customer-a`、`demo-customer-b`、`demo-customer-c`、`demo-staff`；`admin` / `admin`。

**Stripe 测试卡**（任意未来有效期、任意 CVC、任意邮编）：

| 卡号 | 结果 |
|---|---|
| 4242 4242 4242 4242 | 付款成功 |
| 4000 0000 0000 0002 | 被拒绝 |
| 4000 0025 0000 3155 | 需要 3D Secure 验证，验证后成功 |

## Task 4.0: two companies

- CO-002：用 `demo-aushare-staff` / `demo` 登录后台（只允许 AUSHARE 公司）。Billiards 菜单仍由用户组控制，但桌台、预约、帖子和配置列表没有 Q Club 记录；直接打开 Q Club 记录应拒绝访问。用 `demo-staff` / `demo` 登录（仅 TAB 公司），确认能查看 Q Club 记录并处理预约。
- CO-003：用 AUSHARE 公司的 `demo-customer-a` 登录 Q Club，查看占用网格并提交预约；用 TAB 公司的 `demo-customer-c` 登录 AUSHARE `/shop`，查看不绑定公司的商品并加入购物车。两个域名分别登录，使用同一账号，不需重新注册。
- CO-004：为 Customer A 准备一条 AUSHARE 已确认订单。分别登录两个网站的 `/my` 和 `/my/orders`：Q Club 的订单列表及计数不含该订单，AUSHARE 仍显示；AUSHARE 没有 Q Club 卡片，`/my/billiard` 为 404。报价和发票同样只在启用在线预约的网站按其公司过滤。
- CO-005：在 Q Club 注册一个新演示账号，在后台确认其默认公司为 TAB。
- CO-006：运行 `make iso-check` 核对 AUSHARE 指纹。Task 4.0 尚未实现下文的 Stripe 和结算流程；桌台数量和价格仍以当前演示数据为准。

## 阶段 4 后续演示步骤

| 步骤 | 操作 | 应该看到 | 规格 |
|---|---|---|---|
| 1 | Customer A 预约后天的中式桌 2 小时，提交 | 确认页显示押金 $25.00 和 **Pay deposit** | PAY-003 |
| 2 | 点 Pay deposit，用 4000 0000 0000 0002 付款 | 提示付款失败；预约仍为 Awaiting Deposit，可重试 | PAY-007 |
| 3 | 改用 4242 4242 4242 4242 付款 | 回到确认页，预约为 **Confirmed**；Mailpit 收到 "Deposit received – booking confirmed"，没有卡号；Stripe 控制台有 $25.00 付款 | PAY-004、PAY-008 |
| 4 | 后台打开该预约 | 付款金额、时间、Stripe 交易号只读显示，不能修改 | PAY-009 |
| 5 | 打开 AUSHARE 商城，加一件商品走到结账页 | 看不到 Stripe，结账页和以前一样 | PAY-001 |
| 6 | Customer B 预约 3 天后的美式桌 2 小时，付 $20.00；在 My Account 点 Cancel | 先显示 "You will receive a full refund of $20.00."；确认后变为 Cancelled，Stripe 控制台出现 $20.00 退款，B 收到邮件 | RF-001、RF-003、RF-006、RF-007 |
| 7 | Customer B 预约今天稍后的斯诺克桌 1 小时，付 $15.00，然后取消 | 先显示 "Your $15.00 deposit is non-refundable."；确认后取消，不退款 | RF-002、RF-004 |
| 8 | `admin` 对另一条窗口内的已付预约取消，选择例外全额退款并填原因；`demo-staff` 试同样操作 | admin 成功退款并留下原因和操作员；staff 没有这个选项 | RF-005、ST-002 |
| 9 | `admin` 把未到场等待时长改为 1 分钟；Customer C 预约下一个整点的中式桌 1 小时并付 $12.50；到点 1 分钟后刷新后台 | 预约变为 **No-show**，没收 $12.50，C 收到邮件 | NS-001、NS-003 |
| 10 | `admin` 把这条 No-show 改回 Arrived 并填写原因 | 没收撤销，押金可用于结算 | NS-002、NS-004 |
| 11 | `demo-staff` 对一条已确认、即将开始的预约点 Arrived，再点 **Settle**，实际台费保持不变，余额选 EFTPOS | 余额 = 台费 − 押金；预约变为 **Completed**，结算记录不可修改 | ST-001、ST-005、ST-006、ST-007 |
| 12 | 再结算一条：实际台费改为加时后的金额并填原因，余额选现金 | 现金金额正确，原因有记录 | ST-005、ST-006 |
| 13 | 打开 Billiards → **Daily Reconciliation**，查看今天 | 各项数字与你今天的操作一致；两个自检等式都成立；点数字能看到对应预约；可导出 Excel | ST-003、ST-008–011 |
| 14 | 员工在后台手动确认一条电话预约 | 标记 "No online deposit"，结算时全额收取 | PAY-010 |

步骤 13 的核对方法：演示前我会把你当天要做的操作和对应的预期数字列成一张表，你对照报表逐项核对。第 G 节的 5 个固定场景由自动测试核对（ST-012）。

## 不在演示中手动操作的项目

由自动测试覆盖：重复的付款通知只处理一次（PAY-004）、金额不一致（PAY-005）、付款到达时预约已过期（PAY-006）、为别人的预约付款（PAY-011）、Stripe 退款失败后重试（RF-006）、跨夏令时和跨午夜的取消窗口计算（RF-004）。

## 验收标准

1. 阶段 4 的规格在 `make report` 中全部有测试且通过；前三个阶段的 77 条保持通过
2. `make lint`、`make test`、`make iso-check`、`make e2e` 通过；AUSHARE 结账页不受影响
3. 上述步骤 1–14 由你亲手走通，金额与 Stripe 控制台一致
4. **人工项**：在手机浏览器上（或 Chrome 手机模拟）完成一次付押金和一次自助取消
5. 全程只使用测试密钥和测试卡；仓库和日志中没有任何密钥
