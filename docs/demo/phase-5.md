# 阶段 5 演示脚本

对应 RT-001–007。运行 `make demo` 后，用 Chrome 或 Edge 打开三个互相独立的浏览器上下文。
本次实现环境的 Docker socket 拒绝访问，`make demo` 启动与下列人工步骤待验收。

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

自动验证入口为 `make lint test iso-check`，另有前端契约测试 `node --experimental-vm-modules tools/test_realtime_frontend.mjs`。
当前没有新增两个浏览器上下文的 Playwright 实时用例。当前环境无法启动 Odoo 或验证 WebSocket，跨上下文时序与测试数据清理尚未实测，浏览器验收按本脚本记录。
