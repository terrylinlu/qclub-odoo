# 任务 4.5 验收记录：现场结算（ST-001、ST-005–007）

状态：**验收中**（Claude 已在 demo 实测通过，待你抽查）
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
| — | 无功能性问题。测试中出现过一次 Correct Settlement 的 Reason 被存成重复文本（"XxxXxx"），复测后不再重现，判断是我当时在同一个浏览器里来回切换 demo-staff/admin 两个登录态时造成的一次性输入异常，不是代码缺陷；已用第二次干净的更正操作验证字段存储、chatter 日志都正确 | 不算 bug，仅记录供参考 |

小瑕疵（不影响功能，不记为 bug）：Settle 时如果没有填写 Reason，chatter 日志会显示 "Reason: . Operator: ..."，这里的句点看起来略怪；纯文案问题，不影响数据正确性。

## 三、流程说明

同任务 4.4：提交验收前已把 PR 合并到 main 并打版本号 `task-4.5-v1`，演示环境从 main 重建。你委托我先在 demo 里把以上步骤实测一遍，结果见上表；验收中如发现问题仍按"先确认记录、不立即修"处理。
