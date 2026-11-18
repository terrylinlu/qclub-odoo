# 任务 5.1 验收记录：Table Board 实时看板与员工提醒（RT-001～007）

状态：**功能验收通过**（Claude 在 demo 里代你先走了一遍，细节见下）
版本：`task-5.1-v1`（main @ adc36da，PR #57）
演示环境：`make demo`（演示库 `qclub_demo`，从 main @ task-5.1-v1 升级，未重置）

## 一、验收步骤结果

| 步骤 | 内容 | 结果 | 依据 |
|---|---|---|---|
| 1 | 员工打开 Table Board，查看桌台占用/空闲 | ✅ | 实测 12 张桌台卡片正确显示 Free/Occupied，占用卡显示预约编号、顾客姓名、Adelaide 结束时间 |
| 2 | 顾客提交新预约 | ✅ | 收到 toast "New booking QB2026-00019 awaiting deposit · [Demo] American 1 · 19 Nov, 2:00 pm – 19 Nov, 3:00 pm"，未来预约对应桌台仍显示 Free |
| 3 | 顾客付押金 | ✅ | 收到 "Deposit received for booking QB2026-00020 ·…" |
| 4 | 顾客取消预约 | ✅ | 收到 "Booking QB2026-00020 cancelled ·…"，toast 约 6 秒后自动消失 |
| 5 | 找球友帖子有人申请、被接受 | ✅ | 申请阶段无提醒（符合预期）；接受后收到 "New player accepted for booking QB2026-00021 ·…" |
| 6 | 到店标记触发看板刷新 | ✅（间接验证） | 沿用会话前一轮验收时已到店的 QB2026-00017，看板一直正确显示 Occupied；到店本身与步骤 7 结算共用同一个 `notify_board` 钩子 |
| 7 | 结算触发看板刷新 | ✅ | 对 QB2026-00017 执行 Settle（EFTPOS），看板 Chinese 2 立即自动变回 Free，无 toast（符合预期：结算不在四类提醒范围内） |
| 8 | 未到场自动没收触发看板刷新 | ⚠️ 未独立复现 | 需要精确控制定时任务时序，浏览器工具做不到；`notify_board` 挂在和到店/结算同一个状态变更钩子上（代码已读），且被自动化测试 `test_rt_002_arrival_settlement_no_show_refresh_without_alert` 覆盖 |
| 9 | 离线期间事件不补发，重新打开看板读取当前快照 | ✅（顺带验证） | 验证步骤 10 时，员工账号登出改用 AUSHARE 账号期间顾客新建了 QB2026-00022；重新登回员工账号后看板无补发 toast，只显示当时的真实快照 |
| 10 | AUSHARE 员工收不到 Q Club 提醒 | ✅ | `demo-aushare-staff` 登录后 Table Board 显示 "No enabled tables."；Q Club 顾客下单期间该账号全程无 toast |
| 11 | WebSocket 握手失败时仍显示初次快照 | ⚠️ 未独立复现 | 浏览器工具无法可靠模拟网络层断连；`table_board.js` 的 `onMounted` 无条件做一次 RPC（不依赖 bus 连接状态），代码已读确认符合设计 |

**未独立验证的一点**：员工 A、B 两个账号"同时"收到同一条 toast——这次验收因 Chrome 扩展（用于模拟员工 B 的独立会话）未连上，改成单浏览器顺序验证，只确认了员工 A 收到的内容和时机正确。广播机制本身（同一事件发给多个订阅者）由自动化 HTTP 测试覆盖（`test_rt_007_http_filters_channel_requests_and_supports_same_company`），但两个真实浏览器会话"同时"弹出 toast 这件事，建议你自己用两台设备或两个浏览器再确认一次。

## 二、自动化验证（main @ 7485e9d）

| 项目 | 结果 |
|---|---|
| 规格覆盖（`make report`） | 132 条中 131 条有测试且通过；仅 PAY-012（12 张桌视觉核对）按设计不自动化 |
| 测试总数 | 314 个通过，0 失败 |
| `make lint` | 通过 |
| `make iso-check`（AUSHARE 安装前后对比） | 一致 |
| 前端契约测试（`tools/test_realtime_frontend.mjs`） | 4 个全过 |
| CI（PR #57，合并前） | `test`、`e2e` 均全绿 |

## 三、实现过程中的决定

- 订阅范围：跟现有后台公司权限模型一致（能看到哪个网站的预约，就订阅哪个网站的频道），不新增专门的权限字段——你确认过
- 服务端频道校验需要继承 Odoo 核心模型 `ir.websocket`（`_build_bus_channel_list`），这与项目 ISO-002 安全测试的"零容忍核心模型扩展"默认规则冲突——你确认按 `payment.transaction` 的先例做字段/方法级别的精准白名单，不整体放行
- 过程中我跑完整测试发现 4 个问题（上述两条 ISO 冲突 + 1 个测试断言写法问题 + 1 个测试设计本身的 bug），都已修复，314 个测试全绿

## 四、流程说明

同任务 4.6：PR #57 合并到 main 并打版本号 `task-5.1-v1`，演示环境从 main 升级重建（未重置，沿用了之前验收留下的数据）。Claude 在 demo 里先走了一遍上表的步骤，结果如上；两处未独立复现的环节（步骤 8、11）和"两个员工同时收到提醒"这一点，建议你有空时自己再确认一次。
