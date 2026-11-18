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

✅ 已在 demo 里人工走通（2026-11-18）：默认开启显示价格；关闭后空闲格显示 Available、桌名提示不含单价，选中两格摘要仍正确显示 Table fee $40 / Deposit $20；重新开启后网格价格恢复。

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

✅ 已在 demo 里用真实 Stripe 测试模式人工走通（2026-11-18）：成功卡、拒绝卡（主表步骤 1-3）、3D Secure 挑战卡 4000 0025 0000 3155（完整认证流程，Stripe 商户名正确显示为 TAB Entertainment Pty Ltd，认证通过后预约变 Confirmed）、AUSHARE 不显示 Stripe（主表步骤 5）。并发重复付款（步骤 8）的真实两窗口竞态未强行复现，改为确认其业务逻辑——`Refund extra payment` 向导仅限管理员、需要原因、员工无权限——已由自动化测试（`test_cancel_refund.py` 的 `extra_refund` 相关用例）覆盖。过期竞态（步骤 9）同样由自动化测试覆盖（PAY-006）。PAY-012（12 张桌、50% 押金）已在网格上目测确认。PAY-013（银行账单商户名）需你自己在 Stripe 账号后台核对，这部分不是应用能控制的。

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

✅ 已在 demo 里人工走通（2026-11-18）：窗口内全额退款（主表步骤 6）、窗口外不退款（主表步骤 7）、"Keep booking" 不改变状态、确认后绿色 "Booking cancelled." 提示出现且刷新/关闭后不重复出现、确认页同步显示退款文案。员工在后台点 Cancel 时弹窗只显示不退款结果，没有 "Exception full refund" 选项（该选项仅管理员可见，已由自动化测试覆盖）。离线 mock 退款失败通知（步骤 7）和真实 Stripe 测试模式退款失败重试（步骤 8）由自动化测试覆盖（RF-005/RF-006）。

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

✅ 已在 demo 里人工走通（2026-11-18）：`/my/billiard` 的标签徽章数字正确（My bookings 3 等），"Booked on <时间>" 子文案显示，历史记录按创建时间倒序排列；后台 Bookings 默认启用可移除的 Upcoming 筛选，列表按 Start 升序，移除筛选后可看历史预约。45 条记录的精确分页数学（3 页，20/20/5）由自动化测试覆盖，未在 demo 里人工复现大量数据。

## NS-006 / CFG-007：到店邮件与通知开关

沿用现有演示桌台、顾客与未到场场景，无需新增演示数据；本任务不修改 `docker/`。

1. `make demo` 升级演示模块。管理员进入 Billiards → Settings → Q Club，确认 Notifications 下五个开关默认开启，并确认 Booking Email From 和顾客邮箱已填写。开关控制之后发生的邮件事件，也适用于已有预约。
2. 在可到店窗口内，用员工账号对已确认预约点击 Mark Arrived。在 Mailpit 确认只收到一封 “Booking arrived” 邮件，含预约编号、台桌、阿德莱德时段与 TAB 公司名，不含金额或结算信息。
3. 对已被标为未到场的预约，由管理员填写原因并执行 Revert to Arrived。确认押金恢复 paid、原因/操作员/时间保留，且只收到一封到店邮件。电话预约也执行两种到店路径；无邮箱时正常到店、不发邮件。
4. 管理员逐一关闭五个开关，分别触发提交预约、付款确认、取消、未到场和到店事件。确认对应邮件不出现，预约保留、付款确认、退款/没收、到店与撤销审计照常完成。押金开关同时控制重复付款和时段不可用退款事件的通知；取消退款结果由 Cancellation 开关控制。
5. 重新开启后再触发新事件，确认恢复发信；不会补发关闭期间的邮件。员工可读开关，不能保存修改。
6. 网站隔离使用另建的测试网站检查，勿修改 AUSHARE 配置：一个网站关闭开关，另一个网站仍按自己的开关发信。

✅ 已在 demo 里人工走通（2026-11-18）：五个开关默认开启，Booking Email From / Contact Email 已填写；员工只能查看不能修改开关（点击无效）。Mark Arrived 发出且仅发出一封 "Booking arrived" 邮件，不含金额/结算信息。关闭 Notify: Arrival 后再次 Mark Arrived，没有发送到站内信邮箱（Mailpit 总数未增加），但预约状态正常变为 Arrived。重新开启开关后，没有补发刚才那次未发的邮件（验证了"不会补发关闭期间的邮件"）。

## ST-001 / ST-005–007：现场结算与管理员更正

沿用已有演示桌台与顾客，在后台按下面步骤创建场景；本任务按范围限制不修改 `docker/`。

1. 运行 `make demo` 升级模块。使用员工账号创建处于当前到店窗口内的电话预约，Confirm 后 Mark Arrived。
2. 点击 Settle，确认实际台费默认等于预约台费、押金为零、余额为全部台费。有余额时必须选择 Cash 或 EFTPOS；不改台费可不填原因。确认后状态为 Completed，押金仍为 No online deposit，Settlement 分组显示金额、方式、员工和结算时间。
3. 对另一个已到店预约修改实际台费，不填写或只填空格原因应被拒绝；填写加时或优惠原因后可完成。
4. 对使用 Stripe 测试模式付过押金的已到店预约结算：余额扣除实付押金，押金变为 Applied to settlement。实际台费等于押金时无需支付方式；低于押金时显示不退款提示、余额为零，不生成退款。
5. 员工完成后看不到 Correct Settlement；管理员可打开该向导，同时更正金额和方式，原因必填。确认首次结算时间和操作员保留，更正原因、管理员和时间另行显示，chatter 留有记录。
6. 非 Arrived 预约不显示 Settle；非 Completed 预约不显示 Correct Settlement。

✅ 已在 demo 里人工走通（2026-11-18）：Settle 弹窗默认 Actual Table Fee = 预约台费、Balance to collect 正确计算，未改金额时无需填 Reason；选择 EFTPOS 确认后状态变 Completed，Settlement 区域正确记录金额/方式/操作员/时间，chatter 留痕。Correct Settlement 弹窗强制要求 Reason（"A reason is required for every settlement correction."）；更正金额和方式后，首次 Settle 的记录保留不变，新增独立的 Settle Correction Reason/Operator/At 字段，chatter 同时保留两条记录。


## ST-003 / ST-004 / ST-008–012：日对账与 Excel

沿用现有演示账号、桌台和押金支付/取消/未到场/结算流程；按本任务明确范围不修改 `docker/`。
本次 `make demo` 因 Docker socket 权限被拒绝未能启动，以下步骤尚未走通，需人工验收。

1. 在获准的本地测试环境执行 `make demo` 升级模块。员工进入 Billiards → Daily Reconciliation，
   选择 Q Club 与营业日。日期默认阿德莱德营业今天，06:00 为边界；每次重新进入菜单可选择另一网站/日期。
2. 按 `docs/spec/phase4.md` 第 G 节建立五个场景（Stripe 只用测试模式），确保付款、退款、取消、未到场和结算
   都在同一营业日。八行金额应依次为 92.50、20、45、15、12.50、25、40、0 AUD。
   自检①两边为 0，自检②两边为 110；均平衡，无人工核对红色提示。
3. 分别点八个 View，核对列表仅含所选网站与对应发生时间范围内的预约。
   同一预约可出现在多类，例如场景 1 同时出现在押金收取、押金抵扣、EFTPOS 和结算差额留存列表（差额为零）。
4. 新建实际台费低于押金的结算，确认差额留存为押金减实际台费，现场余额为零，自检②仍平衡。
   管理员更正结算后重新打开报表，确认金额实时更新且仍归首次结算日。
5. 将未到场预约 Revert to Arrived 后结算，重新打开报表；未到场没收不再包含它，押金计入抵扣，自检平衡。
6. 核对 06:00 前一秒与恰好 06:00 的付款/取消，后者归新营业日；检查自检①不误报。
   夏令时切换营业日分别覆盖 23/25 小时，存储时间为 UTC，显示为 Adelaide。
7. 点击 Export Excel，人工检查 Summary 与 Detail 两个 sheet：八类金额、自检左右值/平衡状态；
   明细按类目分行，预约号、球桌、顾客、金额和 Adelaide 事件时间正确，和界面/跳转列表一致。
8. 门户/匿名用户直接访问下载地址应 403；仅属另一公司的员工应 403；员工/管理员可查看自己可访问公司的网站。
   AUSHARE 与 Q Club 报表互不混入预约；本功能不生成会计/税务凭证，也不写死 GST。
9. 回到对账表单，点击工具栏 **New**。确认能打开新向导，英文界面的面包屑显示 **Daily Reconciliation**，
   并可选择另一营业日进行对账。

Excel 内容本身未自动核对：本次无法访问测试镜像确认 openpyxl；自动 HTTP 测试在镜像有 openpyxl 时核对内容，
没有时只核对响应 Content-Type 与非空字节，并记录“Excel 内容未自动核对，人工抽查”。
