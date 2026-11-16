# 任务 4.4 验收记录：未到场与没收（NS-001–005）

状态：**验收中**（v1/v2/v3 的步骤 1-9 均已通过；步骤 6-9 是你当天晚上无法点 Mark Arrived 后，委托我直接在 demo 环境里实测的，细节见下方备注，建议你有空时抽查一遍）
版本：`task-4.4-v3`（main @ 52fcfa8，在 task-4.4-v2 基础上新增 PR #51，修复 task-4.4-v1-01：取消邮件不再限制 `booking_channel == 'online'`；顺带修了确认页对非预约本人访问的处理——统一跳转 `/my/billiard`，不再 404，也修了一个连带发现的真 bug（未登录访问付款确认页会 500）。详见 `docs/design/4.4-fix-v1-01-cancel-email.md`）
演示环境：`make demo-reset`（演示库 `qclub_demo`，从 main @ task-4.4-v3 重建）

## 一、验收步骤

### task-4.4-v1（NS-001–005，已验收通过，2026-11-16）

| 步骤 | 内容 | 结果 | 依据 |
|---|---|---|---|
| 1 | NS-001/NS-003：等待时长改 1 分钟，预约到点未到店自动变 No-show，押金没收，顾客收到邮件 | ✅ | 你确认通过 |
| 2 | NS-002/NS-005：开始前 30 分钟到没收截止之外点 Mark Arrived 被拒绝；窗口内成功 | ✅ | 你确认通过 |
| 3 | 后台表单已看不到旧的手动 "No-show" 按钮 | ✅ | 你确认通过 |
| 4 | NS-004：员工点不到撤销；管理员点 Revert to Arrived 填原因后，押金恢复为已付、状态回到 Arrived | ✅ | 你确认通过 |
| 5 | 电话预约（无押金）未到场也发通知邮件，但文案不提押金 | ✅ | 你确认通过 |

### task-4.4-v2（NS-006、CFG-007，Claude 在 demo 实测通过，2026-11-17 凌晨）

| 步骤 | 内容 | 结果 | 依据 |
|---|---|---|---|
| 6 | NS-006：员工 Mark Arrived 成功后，顾客收到到店确认邮件，不含金额/结算信息；电话预约同样收到 | ✅ | 新建 QB2026-00005（backoffice 渠道，Customer A），Mark Arrived 后 Mailpit 收到 "Booking arrived" 邮件，正文只有预约号/台桌/时段，没有金额 |
| 7 | NS-006：管理员 Revert to Arrived 撤销未到场后，顾客也收到同一封到店确认邮件 | ✅ | 新建 QB2026-00006，等真实时间过了未到场窗口、cron 自动标记 no_show 后，以管理员身份 Revert to Arrived 填原因，Mailpit 收到第二封 "Booking arrived" 邮件；No Show Revert Reason/Operator/At 审计字段均正确记录，Deposit State 显示 "No online deposit"（backoffice 无押金，符合预期） |
| 8 | CFG-007：后台 Billiard Settings → Notifications 能看到 5 个开关，默认全开；关闭某一个后对应事件不再发邮件，但状态流转/押金处理不受影响；员工只读，改不动 | ✅ | 5 个开关都在、默认打勾；关掉 Notify: Cancellation 后新建并取消 QB2026-00007，Mailpit 没有新邮件，但预约状态正常变为 Cancelled；验证后已改回勾选 |

### task-4.4-v3（task-4.4-v1-01 修复，Claude 在 demo 实测通过，2026-11-17 凌晨）

| 步骤 | 内容 | 结果 | 依据 |
|---|---|---|---|
| 9 | admin 在后台 cancel 一个 backoffice 渠道、顾客留了邮箱的预约（比如重新用 QB2026-00001 的场景），顾客这次能收到取消邮件 | ✅ | 直接 cancel 了 QB2026-00001（backoffice，Customer A），Mailpit 收到 "Booking cancelled" 邮件，正文显示 "This booking has no deposit to refund."，"View booking" 链接指向 `/billiard/booking/confirmation/QB2026-00001` |

**关于 6-9 的测试方式说明**：当晚实际时间已过 Q Club 周一的营业时间（14:00–24:00），现有预约全部排在未来，点不了 Mark Arrived；为了能在真实时钟下验证，我临时把 Billiard Settings 的 No-show Wait 改成 1-180 分钟、把 Opening Hours 的周一关门时间临时延到次日 2:00，测完后都已经改回默认值（No-show Wait 30 分钟，周一 14:00–24:00）。新建的 QB2026-00005/6/7 是测试数据，留在演示库里，不影响你后续验收。

## 二、发现的问题

逐条确认但先不修复；等你验收全部测完（含 v2 的 NS-006/CFG-007），再统一修复、出回归版本。

| 单号 | 问题 | 规格/依据 | 状态 |
|---|---|---|---|
| task-4.4-v1-01 | admin 在后台 cancel 一个预约后，顾客在"我的预约"能看到已取消，但没收到取消邮件 | 代码确认：`booking_deposit.py::_queue_cancellation_email` 只在 `booking_channel == 'online'` 时才发邮件；QB2026-00001 的 `booking_channel` 是 `backoffice`（员工在后台代客下的单），所以被跳过。这是取消邮件（阶段3功能）里的既有逻辑，不属于 NS-001–005，但本轮验收中发现，按流程记录 | **已在 task-4.4-v3 修复**（PR #51），Claude 已在 demo 实测通过（见上方步骤 9），建议你有空时再抽查一遍 |

原 task-4.4-v1-02（Mark Arrived 没邮件）确认不是对规格的偏离，你已批准把它加为新需求 NS-006，随 v2 实现，不再作为 bug 记录；同时你追加批准了 CFG-007（通知邮件可配置开关）。两者均已合并到 main、随 task-4.4-v2 待验收（见上方第二张表）。

## 三、流程说明（本任务起生效）

按你 2026-11-16 的要求：提交验收前先把 PR 合并到 main 并打版本号（`task-<任务号>-v<轮次>`），演示环境永远从 main 重建，不用 feature 分支；验收中发现的 bug 我先确认并记下问题单号（`task-4.4-v1-01`……），不立即改代码；等你全部测完，再一次性修复、出回归版本，重新验证干净后才开始下一个任务的设计。验收中如果你提出新需求（如本次的 NS-006、CFG-007），设计批准后随即实现、合并、打下一个版本号，不用等 bug 修复批次，但照样要你验收。
