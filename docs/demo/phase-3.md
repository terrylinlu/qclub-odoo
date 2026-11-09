# 阶段 3 演示脚本：约球留言板

状态：**已定稿（修订版）**（2026-11-09 评审通过：留言板并入预约页，取消昵称）
对应规格：BRD-001 至 BRD-029（`docs/spec/phase3.md`）

## 启动与账号

与阶段 2 相同：`make demo`，用 **Chrome 或 Edge** 打开。数据不新鲜时先运行 `make demo-reset`。

| 入口 | 地址 |
|---|---|
| Q Club 预约页（含留言板） | http://qclub.localhost:8069/billiard/booking |
| AUSHARE（应看不到） | http://aushare.localhost:8069/billiard/booking |
| 后台 | http://localhost:8069/web/login |
| 邮件（Mailpit） | http://localhost:8025 |

演示账号（密码均为 `demo`）：`demo-customer-a`、`demo-customer-b`、`demo-customer-c`（新增）、`demo-staff`；`admin` / `admin`。
建议用普通窗口和无痕窗口分别登录不同顾客。

## 任务 3.1 可演示部分

本任务只有后台配置，显示名规则由自动测试验证；用户能看到的留言板功能从 3.2 开始。

1. 运行 `make demo`，用管理员登录后台 Billiard Settings → Q Club → **Online Board** 分组：默认人数 3、频率 5；输入 0 无法保存。
2. `demo-staff` 不能修改配置。网站菜单中没有 Board，My Account 页面不变。

## 页面草图（文字描述，设计时细化）

留言板全部在预约页 `/billiard/booking` 内，不跳转页面：

- **网格**：有开放帖子的预约，占用的每一格在 "Booked" 外显示标记（如 "Join · 2"）；普通占用格仍灰色不可点
- **帖子面板**（网格下方，位置同 "Selected booking"）：显示名（未登录为 Q Club Player，登录后为姓名）、时段、桌台、技术水平、消息、剩余名额、**Apply to join**、已接受的球友、回复和回复框；每条内容旁有 Report
- **当日列表**（面板下方）："Players wanted on Fri 13 Nov"，随日期切换，点一条等于点对应格子
- **发帖人视角**：点自己已确认预约的格子，面板显示 **Find players**；发帖后面板多一个申请列表，每条有 Accept / Decline，已接受的可 Remove
- **后台 Board 菜单**：Posts、Replies、Reports、Banned Customers

## 演示步骤

| 步骤 | 操作 | 应该看到 | 规格 |
|---|---|---|---|
| 1 | 顾客 A 在预约页提交一个未来时段，`demo-staff` 在后台 Confirm | 预约变为 Confirmed；顾客 A 点网格上自己的格子，面板显示 **Find players**；确认页也有该按钮 | BRD-004、BRD-006 |
| 2 | 顾客 A 点一条待付押金的预约的格子 | 没有 Find players，提示需先确认 | BRD-004 |
| 3 | 顾客 A 点 Find players，首次需同意社区须知 | 同意后在面板内继续发帖，全程不离开预约页 | BRD-029 |
| 4 | 发帖：消息、Intermediate、需要 2 人 | 该预约占用的每一格显示 "Join · 2"；网格下方当日列表出现这条；时段和桌台来自预约 | BRD-005、BRD-007 |
| 5 | **不登录**打开预约页对应日期，点带标记的格子 | 面板打开；发帖人和回复者都显示 **Q Club Player**；页面和接口响应中无姓名、电话、邮箱、预约编号；点 Apply 跳转登录，登录后回到预约页并展开原帖，此时显示发帖人的姓名 | BRD-003、BRD-008、BRD-009 |
| 6 | 点一个没有帖子的占用格；打开 AUSHARE 的预约地址 | 占用格不可点；AUSHARE **404** | BRD-008、BRD-027 |
| 7 | 顾客 B 回复一条内容，其中包含 `<script>alert(1)</script>` 和一个网址 | 按原文显示，不执行、网址不是链接 | BRD-010、BRD-025 |
| 8 | 顾客 B 点 Apply to join 并附留言 | 顾客 A 在面板看到申请；Mailpit 收到 Q Club 版式邮件，只有姓名、没有联系方式，链接打开预约页并展开该帖 | BRD-008、BRD-011、BRD-018、BRD-019 |
| 9 | 顾客 A 接受 B；顾客 C 也申请，A 接受 C | 标记和剩余名额归零，已接受列表显示两人的姓名（未登录时显示 Q Club Player）；其他人不能再申请 | BRD-012、BRD-013 |
| 10 | 查看后台该预约 | 时段、金额、状态都没有变化；没有新增预约 | BRD-014 |
| 11 | 员工把该预约改到另一个时段 | 标记和面板显示新时段；B、C 收到时段变更邮件 | BRD-017、BRD-018 |
| 12 | 顾客 B 举报顾客 C 的一条回复；`demo-staff` 在后台 Reports 隐藏该回复并标记已处理 | 面板显示 "This reply was removed."；后台保留原文和操作记录 | BRD-020、BRD-021、BRD-022 |
| 13 | `admin` 封禁顾客 C；C 尝试回复 | C 能看但不能回复；C 的预约不受影响；`demo-staff` 没有封禁入口 | BRD-023 |
| 14 | 员工取消该预约 | 帖子立即关闭：标记和当日列表中的条目消失，格子恢复空闲；用邮件里的链接打开，面板只读显示 "This post is closed."；B 收到通知 | BRD-015、BRD-016、BRD-018 |

## 验收标准

1. 本阶段 29 条规格在 `make report` 中全部有测试且通过；阶段 1–2 的 43 条保持通过
2. `make lint`、`make test`、`make iso-check`、`make e2e` 通过（AUSHARE 不受影响）
3. 上述步骤 1–14 由你亲手走通
4. **人工项**：在手机浏览器上（或 Chrome 手机模拟）查看预约页上的标记、帖子面板、发帖和回复是否可用
5. 并发接受（BRD-013）、频率限制（BRD-024）由自动测试覆盖，不在演示中手动操作
