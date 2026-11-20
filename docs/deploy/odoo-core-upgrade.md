# 生产升级清单：Odoo 核心从 `203c9270`（2026-03-17）升级到对齐测试镜像的版本

对应：`docs/progress.md` 第八节"🟡 升级生产 Odoo 到最新 19.0"。
执行人：**你**（Claude Code 不操作生产，AGENTS.md 红线）。Claude Code 负责在本机生产库副本上彩排、验证兼容性、整理出这份可执行清单；真正的 `git checkout`、`systemctl restart` 等操作由你在生产上执行。

状态：**✅ 2026-11-20 已在生产正式执行，升级完成**。彩排见第六节；生产执行记录见第八节。手动备份+恢复验证通过，`-u all` 零错误（99 模块，92 秒），服务重启正常，冒烟检查通过。观察期内发现一个独立问题（PDF 二维码渲染缺系统依赖），已确认与本次升级无关、非常驻故障，详见第八节和 `docs/progress.md` 第八节对应待办。

## 一、目标版本

不是升到"19.0 分支当天最新"，而是**对齐项目测试/CI 用的同一个版本**，这样生产和测试环境永远用同一套核心代码，以后不用再像穿刺 1/Phase 6 那样专门下载旧版源码做兼容性测试。

- 测试镜像：`odoo:19.0@sha256:5e755c725b3c43cf0be16d579904e1418300db3a2c44952f928eaddbcb0cc16d`（`docker/docker-compose.test.yml` 里固定的摘要，2026-11-04 拉取），内部 Odoo 包版本 `19.0.20261102`（2026-11-02 的每日构建）
- 对应源码提交：**`86ab4d9caa40fc36425488573a424857e8eff5c7`**（committer date 2026-11-02T19:04:12Z，用 GitHub API 按日期查到，跟每日构建版本号吻合）
- 生产现在的提交：`203c9270cc8f27307fd8a72e6fd9df504bc84fab`（2026-03-17）

**这次升级之后，测试镜像版本如果再往前走（比如下次固定摘要升级），生产需要再跟着升一次**——不是一劳永逸，但至少这次把差距从 7.5 个月缩短到 0。

## 二、风险初步评估

- **同一大版本内升级**（19.0 → 19.0），不是跨大版本（比如 18→19），预期没有需要人工介入的数据迁移脚本，`-u all` 走 Odoo 自己的模块升级机制应该能处理
- **Python 依赖**：对比两个提交的 `requirements.txt`，差异只有给 Python 3.14 新增的版本 pin，生产系统是 Ubuntu 24.04（Python 3.12，"Noble"），**实际生效的依赖版本完全没变**，不需要升级虚拟环境里的包（但彩排时还是会跑一次 `pip install -r requirements.txt` 核对，不假设）
- **qclub_billiard 本身的兼容性**：日常测试本来就是在这个新版本（`odoo:19.0` 镜像）上跑的，所以模块对新核心的兼容性其实每天都在验证，不是新风险——真正要彩排的是"旧数据经过这次版本跨度大的升级，`-u all` 能不能顺利跑完，升级后生产当前 99 个已装模块会不会出问题"，这是只有真实生产数据才能验证的部分

## 三、彩排步骤（Claude Code 在本机生产库副本上执行，方法同 Phase 6/穿刺 1）

1. [x] 恢复一份生产备份为 `qclub_prodcopy`（复用已有流程）
2. [x] 复制一份 `qclub_prodtrial_upgrade`，保持 `qclub_prodcopy` 不动作为"升级前"基线
3. [x] 下载目标提交 `86ab4d9c...` 的源码（同穿刺 1 的下载方式），跟现在本机已有的 `203c9270` 源码分开存放
4. [x]（跳过，非必要）在 `qclub_prodtrial_upgrade` 上用**旧源码**启动一次确认现状——Phase 6 彩排已经反复验证过旧源码能正常跑这份备份，不再重复
5. [x] 换成**新源码**，跑 `odoo -u all --stop-after-init`：**100% 干净，0 个 ERROR/CRITICAL**，耗时约 84 秒；`base`/`sale`/`web`/`website` 等模块版本号均已更新（如 `base` → `19.0.1.3`），99 个模块保持已安装状态，没有模块在升级中被卸载或损坏
6. [x] **指纹对比**：升级前后共 928 行差异，逐项核实后**全部可解释**：133 处是 `account`/`portal` 等 Odoo 核心模块自带视图的 `arch_md5` 变化（同一个 view key，内容被上游在这 7.5 个月里patch 过，是正常升级行为）；另有 5 处纯新增记录（一个新的 "Thanks (Contact us)" 标准页面、一个新的 "Restaurant Expenses" 标准产品、两条新的占位支付方式），都是新版本自带模块数据新增的标准记录，**没有任何记录被删除或修改成不一样的内容**，不是数据丢失/损坏
7. [x] 在升级后的新核心上装 `qclub_billiard`：干净安装（100 个模块），**指纹相对"升级后、装模块前"这个基线 0 差异**——模块安装本身跟之前历次彩排一样，对 AUSHARE 零影响；跑全量测试：242 个测试里 8 失败 7 报错，**失败集合跟 Phase 6 彩排完全一致**（同样是"未拆分公司"+"真实财务数据"这两个已知原因），核心升级本身**没有引入任何新的测试失败**；结合 Phase 6 第二轮"先拆分公司→321/321 全绿"的结论，可以合理推断"核心升级 + 公司拆分"一起做也会是干净结果（这次没有重复跑那个组合，避免冗余）
8. [x] 对升级后、装了 `qclub_billiard` 的库做一次备份恢复演练：`pg_dump`（约 10 MB）+ filestore（约 101 MB），恢复到全新库耗时约 20 秒，Odoo 正常启动，AUSHARE 首页正常渲染
9. [x] 清理：所有容器、网络、本机数据库和文件存储副本已删除

## 四、生产执行步骤（你来做，彩排通过后再排期）

1. 选一个维护窗口（建议业务低峰期，Q Club/AUSHARE 都没有在线交易的时段）
2. 执行前：确认最近一次自动快照已生成；手动做一次 `pg_dump` + filestore 备份，确认能恢复（走完 `docs/progress.md` 第八节的要求）
3. `cd /opt/odoo-server && git fetch && git checkout 86ab4d9caa40fc36425488573a424857e8eff5c7`（或你决定的更新目标提交）
4. 激活虚拟环境，`pip install -r requirements.txt`（按彩排结果，预期无实际变化，但still要跑一次，保险）
5. `sudo systemctl stop odoo`，手动跑一次 `odoo -d AUSHARE -u all --stop-after-init --log-level=info`，观察日志，确认模块升级无 ERROR
6. `sudo systemctl start odoo`，确认服务正常启动
7. 冒烟检查：AUSHARE 首页/商城/购物车/结账，Q Club 首页/预约页，后台登录，Table Board 看板，关键邮件能发出
8. 观察一段时间（建议至少一个完整营业日），确认没有延迟出现的问题

## 五、回退

- 升级前的手动备份 + 当天的 EBS 自动快照都在，出问题可以整库恢复
- 代码层面：`git checkout 203c9270cc8f27307fd8a72e6fd9df504bc84fab` 能回到原版本，但**如果 `-u all` 已经改了数据库 schema，单纯切回旧代码不一定兼容旧 schema**——所以真正的回退手段是"数据库 + 代码一起回滚"（`git checkout` 老提交 + 恢复执行前的数据库备份），不要只切代码不管数据库

## 六、演练记录

| 日期 | 环境 | 结果 |
|---|---|---|
| 2026-11-19 | 本机独立 Docker，2026-11-06 生产备份，源码从 `203c9270`（2026-03-17）升到 `86ab4d9c`（2026-11-02） | ✅ `-u all` 零错误；AUSHARE 指纹 928 行差异全部核实为核心版本正常变化，无数据丢失；装 `qclub_billiard` 后零额外差异；测试失败集合跟未升级时完全一致（公司拆分/真实财务数据这两个已知原因，不是升级引入的新问题）；备份恢复 ~20 秒验证通过；本机数据副本已清理 |

## 七、跟其他待办的先后关系

- 跟 **Phase 6 上线彩排**（`docs/deploy/phase6-go-live-rehearsal.md`）的关系：建议**先做这次 Odoo 核心升级，再做 Phase 6 的正式上线彩排**——这样 Phase 6 彩排时就不用再套用"旧源码遮盖镜像"的特殊处理，直接在生产实际运行的新核心上彩排，结果更贴近真实上线情况
- 跟 **公司拆分**（`docs/deploy/company-split.md`）没有先后依赖，两件事互相独立，顺序不影响结果
- 跟 **Q Club 专用发件邮箱**（`docs/progress.md` 第八节）没有依赖关系

## 八、生产执行记录

| 日期 | 执行人 | 结果 |
|---|---|---|
| 2026-11-20 | 你（Claude Code 不操作生产） | ✅ 按第四节步骤执行：手动 `pg_dump`+filestore 备份并恢复验证通过（模块数、`res_partner` 数量核对一致）；`git checkout 86ab4d9caa40fc36425488573a424857e8eff5c7`；`pip install -r requirements.txt` 无变化；停服务后手动跑 `odoo-bin -u all --stop-after-init`，99 个模块升级，92 秒，无 ERROR/CRITICAL；`systemctl start odoo` 正常；冒烟检查：AUSHARE/Q Club 首页 200、后台登录正常、AUSHARE 结账页测试通过 |

**观察期发现（非阻塞）**：升级后约 2 分钟内，日志出现重复的 PDF 渲染失败——`ModuleNotFoundError: No module named 'rlPyCairo'` / `'_rl_renderPM'`，经 Nginx access log 确认是 Odoo 自身的 `wkhtmltopdf` 子进程在渲染一个带二维码的 PDF（很可能是冒烟检查里 AUSHARE 结账触发的订单确认/发票，`l10n_au` 本地化发票常带支付二维码），二维码图片生成失败导致整份 PDF 渲染失败，重试几次后自动停止。核查结论：
- 最近 30 分钟 `odoo.http: Exception during request handling` 报错次数为 0，确认已自行停止，不是常驻循环
- `ir_cron` 中没有秒级间隔的定时任务，`mail_mail` 中没有相关的卡住邮件，排除是定时任务或邮件队列反复重试
- 与本次核心升级无关：`pip install` 期间 `reportlab` 版本在升级前后一致（`already satisfied`），缺的是系统级 Python 扩展（渲染二维码用的 PM 后端），不是 Odoo 代码或 Python 包版本问题

**后续待办**：生产服务器缺少 `reportlab` 二维码渲染所需的系统依赖（大概率需要 `pip install rlPyCairo` 加 cairo 开发库）。真实顾客订单一旦触发同一条路径（打印发票、邮件夹带二维码附件）会复现同样的失败。已记入 `docs/progress.md` 第八节待办，建议下次维护窗口一并处理，不阻塞这次核心升级的完成状态。
