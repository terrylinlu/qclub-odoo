# 生产升级清单：Odoo 核心从 `203c9270`（2026-03-17）升级到对齐测试镜像的版本

对应：`docs/progress.md` 第八节"🟡 升级生产 Odoo 到最新 19.0"。
执行人：**你**（Claude Code 不操作生产，AGENTS.md 红线）。Claude Code 负责在本机生产库副本上彩排、验证兼容性、整理出这份可执行清单；真正的 `git checkout`、`systemctl restart` 等操作由你在生产上执行。

状态：**2026-11-19 范围已确认（对齐测试镜像版本，先写清单后彩排），待彩排**。

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

1. 恢复一份生产备份为 `qclub_prodcopy`（复用已有流程）
2. 复制一份 `qclub_prodtrial_upgrade`，保持 `qclub_prodcopy` 不动作为"升级前"基线
3. 下载目标提交 `86ab4d9c...` 的源码（同穿刺 1 的下载方式），跟现在本机已有的 `203c9270` 源码分开存放
4. 在 `qclub_prodtrial_upgrade` 上用**旧源码**（`203c9270`）启动一次，确认能正常跑（复现现状）
5. 换成**新源码**，跑 `odoo -u all --stop-after-init`（升级全部 99 个已装模块到新版本的 schema/数据），记录：
   - 升级耗时
   - 是否有 ERROR/CRITICAL（WARNING 可以接受，但要看是不是本模块相关）
   - 升级后 `ir.module.module` 里各模块的版本号是否都正常更新
6. **指纹对比**：`tools/iso_fingerprint.sql` 比较升级前（`qclub_prodcopy`，老核心）与升级后（`qclub_prodtrial_upgrade`，新核心）——这次预期会有一些差异（新版本核心本身可能调整了一些数据/配置默认值，不是 `qclub_billiard` 引起的），需要人工过一遍差异内容，确认都是 Odoo 核心本身版本之间的正常变化，不是数据丢失或损坏
7. 在升级后的新核心上，装 `qclub_billiard`（用新源码而不是旧源码），跑 `make` 同等的 lint/test/iso-check 流程，确认模块在"生产真实数据 + 新核心"组合下仍然全绿
8. 用新源码对升级后的库做一次备份恢复演练（复用 Phase 6 第四节的方法），确认升级后的备份流程依然可行
9. 清理本机产生的所有数据副本（跟 Phase 6 一样的清理纪律）

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
| 待执行 | 本机生产库副本 | 待彩排 |

## 七、跟其他待办的先后关系

- 跟 **Phase 6 上线彩排**（`docs/deploy/phase6-go-live-rehearsal.md`）的关系：建议**先做这次 Odoo 核心升级，再做 Phase 6 的正式上线彩排**——这样 Phase 6 彩排时就不用再套用"旧源码遮盖镜像"的特殊处理，直接在生产实际运行的新核心上彩排，结果更贴近真实上线情况
- 跟 **公司拆分**（`docs/deploy/company-split.md`）没有先后依赖，两件事互相独立，顺序不影响结果
- 跟 **Q Club 专用发件邮箱**（`docs/progress.md` 第八节）没有依赖关系
