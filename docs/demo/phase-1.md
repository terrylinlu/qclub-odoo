# 阶段 1 演示脚本：后台管理演示

对应 `docs/progress.md` 第三节。每个涉及用户可见功能的任务，都要同步更新本文件和演示数据（`docker/demo_data.py`），并确认 `make demo` 能按脚本走通（AGENTS.md 完成标准）。

## 启动

在 WSL 的仓库目录中：

```bash
make demo          # 首次自动构建演示库 qclub_demo；之后每次运行会升级模块、刷新演示数据
make demo-reset    # 清空演示库，从零重建（约 20 秒）
make demo-stop     # 停止演示服务（保留演示库）
make demo-logs     # 查看演示服务日志
```

请用 **Chrome 或 Edge** 打开（这两个浏览器会把 `*.localhost` 自动解析到本机，不需要改 hosts 文件）：

| 入口 | 地址 |
|---|---|
| 后台 | http://localhost:8069/web/login |
| Q Club 网站 | http://qclub.localhost:8069 |
| AUSHARE 网站 | http://aushare.localhost:8069 |

演示账号（**仅本机一次性演示库的占位账号**，与任何真实环境无关）：

| 登录名 | 密码 | 身份 |
|---|---|---|
| `admin` | `admin` | 管理员 |
| `demo-staff` | `demo` | 员工（Billiard Staff 组：桌台和配置只读） |
| `demo-customer-a` | `demo` | 门户顾客 |
| `demo-customer-b` | `demo` | 门户顾客 |

界面为英语。演示数据全部是假数据，名称带 `[Demo]` 前缀（如 `[Demo] Table 1`）。注意：`make reset` 会连同演示库一起删除。

## 演示步骤

"可演示"一列标明从哪个任务起这一步能真正走通。

| 步骤 | 操作 | 应该看到 | 可演示 |
|---|---|---|---|
| 0 | 运行 `make demo`；用 `admin` 登录后台；分别打开两个网站地址 | 后台登录成功；`qclub.localhost` 标签页标题为"Home \| Q Club"，`aushare.localhost` 为"Home \| AUSHARE" | ✅ 任务 1.0 |
| 1 | 用 `admin` 打开 **Billiards → Tables**；再用 `demo-staff` 登录 | 看到 3 张演示桌台：`[Demo] Table 1`（Chinese 8-Ball，20 AUD/h）、`Table 2`（Snooker，30）、`Table 3`（9-Ball，25）。`demo-staff` 能看到 Tables 和 **Configuration → Settings**，但只能查看不能修改，也看不到 **Table Types** | ✅ 任务 1.1 |
| 2 | 用 `admin` 打开 **Configuration → Settings → Q Club**，把 Deposit 改为 40、Free Cancellation 改为 12 并保存；再把 Deposit 改成 150 | 保存成功；150 被拒绝，提示 "The deposit percentage must be between 0 and 100."（演示后改回 50 / 24） | ✅ 任务 1.1 |
| 3 | 用 `admin` 打开 **Billiards → Opening Hours**；再用 `demo-staff` 查看 | 默认按 Website 分组，Q Club 有 7 段；Friday / Saturday 的 Closes 为 `02:00 (+1 day)`，其余为 `00:00 (+1 day)`；Saturday / Sunday 的 Opens 为 `13:00`，其余为 `14:00`。管理员可直接编辑，员工只读。**加载默认营业时间按钮**：该按钮只在**表单**里、且只在网站**还没有任何营业时间**时显示（演示库建库时已为 Q Club 加载，所以默认看不到）。验证方法：在 Opening Hours 勾选 Q Club 的 7 行 → Actions → Delete；再打开 **Configuration → Settings**，**点开 Q Club 那一行**，表单顶部出现 **Load Default Opening Hours**；点击后页面刷新、按钮消失，Opening Hours 里 7 段恢复。`demo-staff` 任何时候都看不到该按钮 | ✅ 任务 1.2 |
| 4 | 手动新建一条预约；再建一条同桌重叠预约 | 押金自动 = 台费 × 比例；重叠预约被拒绝，提示为清楚的英文说明而不是数据库报错 | 任务 1.3、1.4 |
| 5 | 新建一条营业时间外的预约 | 被拒绝 | 任务 1.3 |
| 6 | 修改桌台单价，再看已有预约、新建预约 | 已有预约价格不变，新预约用新价格 | 任务 1.3 |
| 7 | 把锁定时长改成 1 分钟，新建"待付押金"预约，等 1–2 分钟 | 自动变"已过期"，同一时段可重新预约 | 任务 1.4 |

## 验收

本阶段 31 条规格（含 ADM）在 `make report` 中全部有测试且通过，且上表步骤 0–7 能走通。结果记录到 `docs/acceptance/phase-1.md`，通过后在 main 上打标签 `phase-1-demo`。
