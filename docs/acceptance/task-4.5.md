# 任务 4.5 验收记录：现场结算（ST-001、ST-005–007）

状态：**验收中**（功能步骤已通过；发现 3 个客户侧展示/样式问题，已确认登记，统一修复后出回归版本）
版本：`task-4.5-v1`（main @ c357b38，PR #52）
演示环境：`make demo-reset`（演示库 `qclub_demo`，从 main @ task-4.5-v1 重建）；测试用预约 QB2026-00004~00007 是我通过后台直接创建的、已处于 Arrived 状态的场景数据，留在库里供你复查

## 一、验收步骤

| 步骤 | 内容 | 结果 | 依据 |
|---|---|---|---|
| 1 | ST-005：已到店预约点 Settle，实际台费默认等于预约台费，不改金额不用填原因，直接完成 | ✅ | QB2026-00004（台费 $40，已付押金 $20）：向导默认 Actual Table Fee $40、Balance $20，选 EFTPOS 后直接 Settle 成功，状态变 Completed |
| 2 | ST-005：改实际台费不填原因被拒绝；填原因后能完成 | ✅ | QB2026-00007：改成 $45 不填原因点 Settle 被拒绝（Reason 标红）；填"Extra time played"后成功，Settle Reason 正确记录 |
| 3 | ST-006：在线已付押金的预约结算，余额 = 实际台费 − 已付押金，选 EFTPOS/现金收余额；押金状态变为 Applied to settlement | ✅ | QB2026-00004 结算后 Deposit State 显示 "Applied to settlement"，Balance Amount/Method 正确 |
| 4 | ST-006/H.4 边界：实际台费 ≤ 已付押金时，余额为 0，不用选支付方式，差额不退（没有退款记录） | ✅ | QB2026-00005（台费=押金=$25）：Balance to collect 显示 $0，Method 字段不出现，直接 Settle 成功；结算前后 Refund 系列字段均为空/$0，没有产生任何退款 |
| 5 | ST-006：backoffice/电话预约（无押金）结算，余额 = 全部实际台费，必须选支付方式 | ✅ | QB2026-00006（backoffice，无押金，台费$20）：Deposit paid $0，Balance to collect $20，选 Cash 后完成；结算后 Deposit State 仍是 "No online deposit" |
| 6 | ST-007：结算完成后，员工看不到 Correct Settlement 按钮 | ✅ | 用 demo-staff 账号打开已完成的 QB2026-00004，表单 header 没有任何按钮（Correct Settlement 对员工隐藏） |
| 7 | ST-007：管理员能打开 Correct Settlement，不填原因被拒绝；填原因后能更正金额/方式，原结算的操作员/时间保留，更正记录单独显示，chatter 有记录 | ✅ | 管理员（admin）打开 QB2026-00004 的 Correct Settlement：不填原因点确认提示 "Missing required fields"；填原因、改台费 $35 后成功。校验：Settle Operator/Settle At（原结算的操作员和时间）始终未变；Settle Correction Reason/Operator/At 正确记录更正；chatter 里原结算和两次更正各有一条独立日志，金额、方式、原因都对得上 |
| 8 | 非 Arrived 状态看不到 Settle 按钮；非 Completed 状态看不到 Correct Settlement 按钮 | ✅ | QB2026-00002（Expired 状态）表单 header 没有任何按钮；整个测试过程中 Arrived 状态只看到 Settle、Completed 状态只看到 Correct Settlement，没有同时出现或状态不对时出现的情况 |

## 二、发现的问题

逐条确认但先不修复；等你验收全部测完，再统一修复、出回归版本。

| 单号 | 问题 | 规格/依据 | 状态 |
|---|---|---|---|
| task-4.5-v1-01 | 客户门户（确认页 `/billiard/booking/confirmation/<name>`，以及邮件模板）的 "Table fee" 始终显示 `booking.table_fee`（预约时的原价），结算（尤其是 Correct Settlement 改价）后不会更新。实测 QB2026-00009：后台 `actual_table_fee=10`（原价 `table_fee=20`），客户确认页仍显示 Table fee: $20.00 | 已确认。设计文档 4.5-settlement.md 只规划了员工/管理员后台的结算字段和操作，没有规划客户门户的展示联动——这是设计遗漏，不是实现偏离设计 | 已确认，待批量修复 |
| task-4.5-v1-02 | 客户门户/邮件完全没有展示结算后的实际金额（`actual_table_fee`/`balance_amount`/`balance_method`），客户无法知道自己实际被收了多少钱、怎么付的尾款——不管后台怎么改实际付款金额，客户看到的页面都不变 | 已确认，根因与 v1-01 相同：客户门户模板（`views/booking_templates.xml`）、邮件模板都未引用任何结算字段，全代码库搜索 `actual_table_fee`/`balance_amount`/`balance_method` 只出现在后台视图、向导和模型里 | 已确认，待批量修复（建议和 v1-01 一起修：确认页/邮件改成"实际台费 + 已付金额"的展示，done 状态下不再显示原始预约台费作为最终结果） |
| task-4.5-v1-03 | "My Bookings" 列表（`/my/billiard`）里，"Booked on ..." 一行和右侧 "View booking date / Cancel booking / Find players" 操作区，在不同订单行之间没有对齐，视觉上参差不齐（见你截图的红圈） | 已确认。根因：`my_account_templates.xml` 里 `.o_qclub_booking_details` 用 `display:flex; justify-content:space-between` 把"时间·球桌"段落、"Booked on ..."段落、操作区三个宽度不固定的元素放在同一行分散对齐，再加 `flex-wrap:wrap`；当第一段文字长度随订单内容（球桌名、时间文案长度）变化、或某些行没有 Cancel/Find players 链接导致操作区宽度不同时，三个元素的换行/分布位置就会跟着变，造成逐行视觉不对齐。这是纯 CSS 布局问题，不是数据问题 | 已确认，待批量修复（建议改成固定两栏结构：左边详情、右边操作区各自纵向堆叠，不依赖 space-between 在不定宽元素间分配空间） |

小瑕疵（不影响功能，不记为 bug）：Settle 时如果没有填写 Reason，chatter 日志会显示 "Reason: . Operator: ..."，这里的句点看起来略怪；纯文案问题，不影响数据正确性。

测试中还出现过一次 Correct Settlement 的 Reason 被存成重复文本（"XxxXxx"），复测后不再重现，判断是我当时在同一个浏览器里来回切换 demo-staff/admin 两个登录态时造成的一次性输入异常，不是代码缺陷（不记为 bug）。

## 三、流程说明

同任务 4.4：提交验收前已把 PR 合并到 main 并打版本号 `task-4.5-v1`，演示环境从 main 重建。你委托我先在 demo 里把以上步骤实测一遍，结果见上表；验收中如发现问题仍按"先确认记录、不立即修"处理。
