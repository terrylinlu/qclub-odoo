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


## CFG-006：网格台费显示开关

本次未运行演示环境（任务要求不访问数据库），以下步骤待人工验收。

1. 管理员打开 Q Club 的 Billiard Settings，确认 Show Prices in Grid 默认开启，空闲格和桌名提示显示台费。
2. 关闭 Show Prices in Grid 并保存，刷新预约页：空闲格显示 Available，桌名提示保留名称和类型，不含单价。
3. 选择同桌连续两格，确认摘要仍显示 Table fee 和 Deposit 金额；继续确认预约，核对确认页、付款流程和邮件金额。
4. 确认 Booked、Join · N、Yours 标记不变；员工可查看开关但不能修改。
5. 管理员重新开启开关，刷新后确认网格价格恢复。

本次未修改 docker/ 演示数据脚本；新增字段默认开启。

## 任务 4.2：在线押金（PAY-001–014）

押金 E2E 使用独立演示账号（密码均为 `demo`）：桌面 `demo-customer-pay`，移动端
`demo-customer-pay-mobile`。两者沿用其他顾客的 portal / 公司隔离规则；更新后运行
`make demo` 创建账号，避免与其他规格共用未付款预约额度。

先运行 `make demo`，演示脚本会在 `qclub_demo` 安装并发布仅限 Q Club / TAB
公司的 Demo 支付方式；若该公司已启用 Stripe，则保留 Stripe，停用 Demo。
本任务没有执行这些命令，也没有连接数据库。

1. 在 Q Club 以 `demo-customer-a` 登录，从营业日期范围内挑选空闲桌台和时段，提交预约。
2. 确认页应显示 Awaiting Deposit、AUD 押金、TAB 公司身份和 Pay deposit 表单。
   开始时间在免费取消窗口内时，应显示不能免费取消的提示。
3. 选 Demo，Payment Details 填任意演示文字，Payment Status 选 Successful，点击 Pay deposit。
   返回确认页后状态应为 Confirmed，付款表单消失。Mailpit 应收到 Q Club 发件人的
   “Deposit received – booking confirmed”邮件，含金额、时段、免费取消截止时间，不含支付详情。
4. 另选空闲时段创建预约，Demo 选 Error。预约应保持 Awaiting Deposit，锁定期内可重试。
5. 后台用员工查看 Deposit 区域：状态、实付金额、时间、交易号及交易列表只读；手动确认
   新建电话预约后，状态应为 No online deposit。
6. AUSHARE 网站不能显示 Q Club 支付方式或访问 Q Club 预约付款；匿名用户、其他顾客同样不能访问。
7. 本地真实 Stripe 测试演示：在仓库外准备 mode 600 的
   `~/.config/qclub/stripe-test.env`（`STRIPE_PUBLISHABLE_KEY`、`STRIPE_SECRET_KEY`）和
   `stripe-webhook.env`（`STRIPE_WEBHOOK_SECRET`）。只能使用测试模式值。
   执行 `tools/stripe_demo.sh start`，用已在穿刺 3 验证的测试卡完成成功、拒绝、3DS 演示。
   CLI listener 的签名 secret 必须与私有 webhook 文件一致；不要把 CLI 启动输出贴入仓库或报告。
   `tools/stripe_demo.sh status` 仅显示容器状态；`stop` 停止转发。
8. 人工验证并发付款：两个窗口在到账前分别开始支付；第二笔成功到账后应标记
   Payment needs attention，发邮件到 Q Club 联系邮箱，不自动退款。
   管理员打开 Refund extra payment，选择多付的交易并填写原因；员工看不到按钮。
   原始押金不受影响，退款请求和原因、操作人、UTC 时间进入 chatter。
   支付方确认退款后，若没有其他异常，提示消失；退款失败则保持提示。
9. 验证过期竞态：到账时锁定已过期，空闲时段应恢复确认；已被占用或已取消则发起全额退款。
   退款完成时邮件写明已退款；尚未完成或失败时邮件明确写退款已请求，并保留后台提示。
10. PAY-012 仅人工验收：12 张桌（美式 4 × AUD20、中式 7 × AUD25、斯诺克 1 × AUD30），50% 押金。
    PAY-013 银行账单商户名须在 Q Club 自己的 Stripe 账号人工核对；自动测试只验证网页和邮件的公司身份。

结束 Stripe 演示后，在演示库后台停用 Q Club Stripe，再运行 `make demo` 即恢复 Demo。
不要在生产环境运行此脚本。

## 任务 4.3：取消与退款（待人工运行）

本任务未连接任何数据库，未执行 make demo、make test 或 make e2e。
复用已有 `demo-customer-pay`（桌面）和 `demo-customer-pay-mobile`（手机），无需新增演示数据或修改 docker。

1. 登录 Q Club，在至少三天后的空闲时段预约并使用 Demo 成功支付押金。
2. 确认页应显示 Cancel booking。进入 My Account → My bookings，找到本次预约并点击 Cancel booking。
   弹窗应显示服务端计算的 “You will receive a full refund of $….”；Keep booking 不改变状态。
3. 点击 Confirm cancellation。页面重载，顶部显示可关闭的绿色 “Booking cancelled.” 提示，状态变为 Cancelled，取消按钮消失。
   关闭提示并再次刷新，提示不应重复出现；确认页取消最后一条可取消预约时也应显示提示。
   后台 Deposit 应显示 Refunded、退款金额、UTC 存储的退款时间、提供方交易号、Free cancellation 和操作人。
   Mailpit 应收到 Q Club 发件人的取消邮件；关联找球友帖子应关闭。
   确认页 Cancelled 状态下方应显示与邮件相同的 “Your deposit of $… has been refunded in full.”；退款尚未完成时显示 “A full refund of $… has been requested. Our team will follow up if it fails.”。
4. 再预约不足 24 小时后的时段并完成 Demo 支付。取消弹窗应显示押金 non-refundable。
   确认后应为 Cancelled / Forfeited，没有退款交易；确认页状态下方应显示 “Your $… deposit is non-refundable.”。
5. 创建尚未付款的预约；取消弹窗应显示 “This booking has no deposit to refund.”。
   确认后押金保持 Awaiting payment。后台手动确认且 No online deposit 的预约同样没有可退押金。
6. 员工在后台点 Cancel：先打开结果向导；不足 24 小时的已付预约按不退处理。
   该向导复用 `qclub.deposit.refund` 的 `cancel` 模式；原 Refund extra payment 使用 `extra_refund` 模式，仍仅限管理员。
   两个入口各自打开独立表单，页头仍为 5 个按钮；不新增模型，也无需调整 ISO-001 白名单。
   管理员在该情形可选 Exception full refund，原因必填；其他情形不显示该选项。
7. 用离线 mock 测试验证请求失败和后续退款失败通知：预约保留 Cancelled，押金 Refund failed，
   出现 Payment needs attention，联系邮箱收到提醒；只有管理员能 Retry refund。
   成功、进行中的退款都必须阻止再次发出全额退款。
8. 真实 Stripe 测试模式退款、后续失败通知、邮件及无会计凭证需在获准的测试环境另行验收。
   AUSHARE 的两个取消接口均应 404；其他顾客、匿名顾客和已开始的预约应被拒绝。

## BRD-031 / ADM-002：分页与默认排序验收

1. 在 `/my/billiard` 使用已有预约较多的演示顾客，确认四个标签各自每页最多 20 条；
   数量徽章显示该标签的总数。My bookings 先显示尚未开始的有效预约，从近到远；
   然后显示其余预约，按下单时间（create_date）从新到旧，同时间按 ID 倒序；每行时段下方显示 “Booked on <时间>”。
   My posts / My join requests 的有效未来记录仍按预约时间从近到远，其余记录按发帖 / 申请创建时间倒序。
   使用预约时间与创建时间顺序不同的记录验证历史排序；Messages 按留言创建时间从新到旧。
2. 在不同标签分别翻页，确认链接保留四个分页参数及当前标签片段（如 `#posts`）；
   刷新、切换标签、浏览器返回后，标签与各自页码保持。非法页码回到第 1 页。
   有 45 条记录的标签，第 1 页应为 20 行，第 3 页应为 5 行，总数徽章为 45。
3. 后台 Bookings 默认启用可移除的 Upcoming 筛选（当前 UTC 时刻之后的 pending/confirmed/arrived），
   列表按 Start 升序。移除 Upcoming 可查看历史预约；Odoo 自带分页及日历入口保持可用。

无需新增 docker 演示账号或数据。本轮仅做静态与离线分页检查，未连接数据库或执行演示环境。
