# 阶段 5 演示脚本

对应 RT-001–007。运行 `make demo` 后，用 Chrome 或 Edge 打开三个互相独立的浏览器上下文。

✅ 已在 demo 里人工走通（2026-11-19，Claude 验收）：步骤 1-7、9、10 全部实测通过。步骤 8（未到场自动没收触发看板刷新）
与步骤 11（WebSocket 握手失败时的静态快照降级）受限于浏览器工具（无法精确控制定时任务时序、无法可靠模拟网络层断连），
未独立复现；这两步底层机制（notify_board 挂在同一个 `_write_deposit` 状态变更钩子上、`table_board.js` 的 onMounted
无条件做初次 RPC）已走读代码确认，且步骤 8 的业务逻辑由自动化测试 `test_rt_002_arrival_settlement_no_show_refresh_without_alert`
覆盖。步骤 9 是在验证步骤 10（AUSHARE 隔离）时顺带验证的：员工 A 登出改用 AUSHARE 账号期间，顾客在 Q Club 新建了一笔预约
（QB2026-00022），员工 A 重新登录后看板只显示当前快照，没有补发错过的 toast。

| 上下文 | 入口与账号 | 用途 |
|---|---|---|
| 员工 A | http://localhost:8069/web/login，`demo-staff` | Billiards → Table Board |
| 员工 B | http://localhost:8069/web/login，`demo-staff-realtime` | 保持在 Bookings 等其他后台页面 |
| 顾客 | http://qclub.localhost:8069/billiard/booking，`demo-customer-realtime` | 在线提交、支付、取消、找球友 |

以上演示账号密码均为本机占位值 `demo`。员工 A、B 仅有 Q Club 所属公司权限。
演示数据沿用 12 张桌台和既有营业时间，新增员工和顾客账号便于独立验收。

| 步骤 | 操作 | 预期结果 |
|---|---|---|
| 1 | 员工 A 打开 Table Board | 所有启用桌台按卡片显示 Free 或 Occupied。占用卡显示预约编号、姓名和 Adelaide 结束时间。页面仅显示当前状态 |
| 2 | 顾客提交一个未来整点的预约 | A、B 均收到 `New booking … awaiting deposit`。该未来预约对应桌台当前仍显示 Free |
| 3 | 顾客通过既有测试支付流程付押金 | A、B 均收到 `Deposit received for booking …`，重复付款通知不重复提醒 |
| 4 | 顾客取消这条尚未开始的预约 | A、B 均收到 `Booking … cancelled`，toast 自动消失且可关闭 |
| 5 | 顾客对另一条未来已确认预约发找球友帖，另一位顾客申请，帖主接受 | A、B 均收到 `New player accepted for booking …`。申请提交或拒绝不产生这条提醒 |
| 6 | 营业时间内准备一条已确认预约，在开始前 30 分钟至开始后等待截止时间内，由 B 标记 Arrived | A 的对应卡片自动显示 Occupied、预约编号、顾客姓名和结束时间 |
| 7 | B 对这条到店预约执行 Settle | A 的对应卡片自动变为 Free。到店及结算只更新看板 |
| 8 | 对另一条已确认预约等待到未到场截止时间，由定时任务标记 No-show | A 的对应卡片自动显示 Free |
| 9 | 关闭 A 的后台，在顾客端完成一次新预约提交，再重新登录 A | 不补发离线时错过的 toast。重新打开看板读取当前快照 |
| 10 | 另一个独立上下文用 `demo-aushare-staff` 登录后台，顾客在 Q Club 再提交预约 | 该员工收不到 Q Club 提醒，其 Table Board 没有 Q Club 桌台 |
| 11 | 在浏览器开发工具阻止 WebSocket 连接后重新打开 Table Board | 看板仍能显示初次 RPC 快照，之后需手动刷新 |

每条 toast 仅含预约编号、桌台、时段和事件。核对其中没有金额、支付方式、电话或邮箱。
多网站属于同一公司的场景按已确认方案共享该公司的员工访问权限，员工订阅该公司下可访问的网站频道。

自动验证入口为 `make lint test iso-check`（314 个测试全绿），另有前端契约测试 `node --experimental-vm-modules tools/test_realtime_frontend.mjs`（4 个全过）。
当前没有新增两个浏览器上下文的 Playwright 实时用例；Claude 本轮验收时 Chrome 扩展（员工 B 的独立会话）未连上，改为单浏览器顺序验证（同一账号在 localhost 域共享 cookie，无法同时登录两个不同后台用户），
员工 A 收到 toast 的内容和时机均已实测确认；"A、B 同时收到"这一点未用两个真正独立的会话同时验证过，留给你用两台设备或两个不同浏览器再确认一次。
