# 阶段 3 演示脚本：约球留言板

状态：**已定稿**（2026-11-09 评审通过）
对应规格：BRD-001 至 BRD-029（`docs/spec/phase3.md`）

## 启动与账号

与阶段 2 相同：`make demo`，用 **Chrome 或 Edge** 打开。数据不新鲜时先运行 `make demo-reset`。

| 入口 | 地址 |
|---|---|
| Q Club 留言板 | http://qclub.localhost:8069/billiard/board |
| AUSHARE（应看不到） | http://aushare.localhost:8069/billiard/board |
| 后台 | http://localhost:8069/web/login |
| 邮件（Mailpit） | http://localhost:8025 |

演示账号（密码均为 `demo`）：`demo-customer-a`、`demo-customer-b`、`demo-customer-c`（新增）、`demo-staff`；`admin` / `admin`。
建议用普通窗口和无痕窗口分别登录不同顾客。

## 页面草图（文字描述，设计时细化）

- **Board 列表**：卡片按时间排序：时段、桌台、昵称、技术水平、消息摘要、"2 spots left"；顶部按日期和技术水平筛选；"Create post" 按钮
- **帖子详情**：上方是帖子信息和 **Apply to join** 按钮；中间是已接受的球友；下方是回复和回复框；每条内容旁有 Report
- **发帖人视角**：多一个申请列表，每条有 Accept / Decline；已接受的可 Remove
- **后台 Board 菜单**：Posts、Replies、Reports、Banned Customers

## 演示步骤

| 步骤 | 操作 | 应该看到 | 规格 |
|---|---|---|---|
| 1 | 顾客 A 在预约页提交一个未来时段，`demo-staff` 在后台 Confirm | 预约变为 Confirmed；顾客 A 的确认页出现 **Find players** | BRD-004、BRD-006 |
| 2 | 待付押金的预约打开发帖页（用另一条未确认的预约） | 不能发帖，提示需先确认 | BRD-004 |
| 3 | 顾客 A 点 Find players，首次需设置昵称并同意社区须知；试填邮箱形式的昵称 | 邮箱形式被拒绝；设置为 `CueMaster` 后进入发帖页 | BRD-001、BRD-002、BRD-029 |
| 4 | 发帖：消息、Intermediate、需要 2 人 | 帖子出现在留言板；时段和桌台来自预约 | BRD-005、BRD-007 |
| 5 | **不登录**打开留言板和帖子详情 | 能看；只显示昵称；页面和接口响应中无姓名、电话、邮箱、预约编号；点 Apply 跳转登录，登录后回到原帖 | BRD-003、BRD-008、BRD-009 |
| 6 | 打开 AUSHARE 的同一地址 | **404** | BRD-027 |
| 7 | 顾客 B 设置昵称、回复一条内容，其中包含 `<script>alert(1)</script>` 和一个网址 | 按原文显示，不执行、网址不是链接 | BRD-010、BRD-025 |
| 8 | 顾客 B 点 Apply to join 并附留言 | 顾客 A 看到申请；Mailpit 收到 Q Club 版式邮件，只有昵称 | BRD-011、BRD-018、BRD-019 |
| 9 | 顾客 A 接受 B；顾客 C 也申请，A 接受 C | 剩余名额归零，已接受列表显示两个昵称；其他人不能再申请 | BRD-012、BRD-013 |
| 10 | 查看后台该预约 | 时段、金额、状态都没有变化；没有新增预约 | BRD-014 |
| 11 | 员工把该预约改到另一个时段 | 帖子显示新时段；B、C 收到时段变更邮件 | BRD-017、BRD-018 |
| 12 | 顾客 B 举报顾客 C 的一条回复；`demo-staff` 在后台 Reports 隐藏该回复并标记已处理 | 前台显示 "This reply was removed."；后台保留原文和操作记录 | BRD-020、BRD-021、BRD-022 |
| 13 | `admin` 封禁顾客 C；C 尝试回复 | C 能看但不能回复；C 的预约不受影响；`demo-staff` 没有封禁入口 | BRD-023 |
| 14 | 员工取消该预约 | 帖子立即关闭，从列表消失，详情只读显示 "This post is closed."；B 收到通知 | BRD-015、BRD-016、BRD-018 |

## 验收标准

1. 本阶段 29 条规格在 `make report` 中全部有测试且通过；阶段 1–2 的 43 条保持通过
2. `make lint`、`make test`、`make iso-check`、`make e2e` 通过（AUSHARE 不受影响）
3. 上述步骤 1–14 由你亲手走通
4. **人工项**：在手机浏览器上（或 Chrome 手机模拟）查看留言板、发帖和回复是否可用
5. 并发接受（BRD-013）、频率限制（BRD-024）由自动测试覆盖，不在演示中手动操作
