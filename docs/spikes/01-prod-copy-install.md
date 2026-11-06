# 穿刺 1：在生产库副本上试装模块

日期：2026-11-06　执行：Claude Code（本机，不接触生产）　限时：半天　结论：**可行**（先启用 `btree_gist` 即可干净安装；AUSHARE 无任何变化）

## 一、问题

1. 模块能否装进**真实的生产库**（99 个模块、3 个公司、有演示数据）？
2. 装上之后，AUSHARE 的页面、菜单、视图、产品、邮件模板、支付方式是否完全不变（ISO-001 在真实数据上）？
3. 用**生产实际运行的 Odoo 版本**（源码提交 `203c9270`，2026-03-17，比测试镜像旧约 7.5 个月），模块的测试能否通过？

## 二、做了什么

| 步骤 | 内容 |
|---|---|
| 数据 | 2026-11-06 的生产手动备份（见穿刺 0 与 `progress.md` 第八节），本机恢复为 `qclub_prodcopy`；每次试装前从它复制一份 `qclub_prodtrial`（数据库 + filestore），`qclub_prodcopy` 保持原样 |
| 代码 | 从 GitHub 下载 `odoo/odoo@203c9270cc8f27307fd8a72e6fd9df504bc84fab`（与生产 `git log` 一致），放在仓库之外；用测试镜像的 Python 及依赖运行，并**遮住镜像自带的新版 Odoo**（Odoo 19 会把 Python 路径上所有 `odoo/addons` 合并，否则新旧核心模块混用） |
| 1 | 不启用 `btree_gist`，安装 `qclub_billiard` |
| 2 | 新复制一份，启用 `btree_gist`，再安装 |
| 3 | 用 `tools/iso_fingerprint.sql` 对比 `qclub_prodcopy`（装前）与 `qclub_prodtrial`（装后） |
| 4 | 在 `qclub_prodtrial` 上用生产代码版本运行模块全部测试 |

全部在本机 Docker 中进行，生产服务器未做任何操作。

## 三、结果

| 步骤 | 结果 |
|---|---|
| 1. 不启用 `btree_gist` 安装 | ❌ 失败：`data type integer has no default operator class for access method "gist"`（与穿刺 0 的预测一致） |
| 2. 启用后安装 | ✅ 成功，无错误、无与本模块相关的警告；模块版本 19.0.1.5.0；排他约束已创建 |
| 3. AUSHARE 指纹 | ✅ **完全一致**（真实数据 2884 行） |
| 4. 测试（生产代码版本） | 110 个中 109 个通过；1 个失败：`TestIsolationHttp.test_iso_001_aushare_homepage_and_shop`（`/shop`） |

**第 4 步唯一失败的原因：测试误报，不是隔离问题。** 该测试断言 AUSHARE 页面不含 "Billiard"、"Booking" 等普通单词；而生产的 AUSHARE 商城本身有商品分类 **"Billiards"**（`/shop/category/billiards-51`），页面自然包含这个词。第 3 步的指纹对比已证明安装前后 AUSHARE 完全没有变化。

## 四、结论

1. **可行**：模块能干净地装进真实生产库，前提是先启用 `btree_gist`
2. **AUSHARE 不受影响**：在真实数据上指纹完全一致，ISO-001 成立
3. **版本差异目前无兼容性问题**：生产旧版 Odoo 上 109/110 测试通过，唯一失败为测试本身的误报
4. **试装方法可复用**：阶段 6 上线彩排、以及生产升级 Odoo 前，用同样方法在新备份上再做一次

## 五、对规格 / 设计的影响

| 影响 | 处理 |
|---|---|
| 生产未启用 `btree_gist` 时模块无法安装 | 已在任务 2.1 设计中：`init()` 自动 `CREATE EXTENSION IF NOT EXISTS btree_gist`（生产上 `odoo` 是库所有者，可执行） |
| ISO-001 网页测试在真实数据上误报 | 把断言改为只检查本模块特有的标记（`/billiard/booking`、`o_qclub`、`qclub_billiard`），不检查普通单词。这是已合并的受保护测试，**需你批准后**单独提交 |
| 规格 | 无需修改 |

## 六、遗留问题

- ISO-001 测试修正：待你批准
- 本机 `qclub_prodcopy`、`qclub_prodtrial` 及其 filestore、试装日志 `~/spike1-logs` 含生产数据：按 `progress.md` 第八节"生产数据副本的保管与清理"在穿刺阶段结束后删除（`qclub_prodcopy` 暂留，供升级 Odoo 前复用）
- 生产 Odoo 源码副本 `~/odoo-src/203c9270…`（1.2 GB，不含数据）可在生产升级后删除
