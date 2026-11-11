# 生产迁移清单：Q Club 改为 TAB Entertainment Pty Ltd

对应规格：`docs/spec/phase4.md` CO-006；演练记录：`docs/spikes/04-multi-company.md`
执行人：**你**（Claude Code 不操作生产）。时机：上线前、Q Club 尚无真实交易时；建议在安装 `qclub_billiard` **之前**完成，模块装上后其记录会自动跟随网站所属的公司。

## 一、执行前

- [ ] 完整备份生产库和文件存储，并确认能恢复（`progress.md` 第八节的备份要求）
- [ ] 确认 Q Club 网站上没有真实订单、付款或发票
- [ ] 准备好 TAB Entertainment 的信息：法定名称、ABN、注册地址、电话、邮箱、Logo
- [ ] 记录现状，迁移后对比：AUSHARE 首页、商城、购物车、结账页截图；Q Club 首页截图
- [ ] （可选）用只读方式导出 AUSHARE 指纹：在生产库上运行 `tools/iso_fingerprint.sql`（`psql -X -qAt -v ON_ERROR_STOP=1`），保存输出

## 二、在后台操作

1. **新建公司**：Settings → Companies → New。填法定名称、ABN（Tax ID）、地址、电话、邮箱、Logo；币种 AUD，国家 Australia。保存。
   - 演练时在命令行建公司出现过一次 `KeyError: 'res.partner.image_1024'`，重试后成功。后台界面如果报错，先确认公司是否已经建出来，再决定重试，不要重复建。
2. **科目表与 GST**（和会计一起）：切换到 TAB Entertainment，Accounting → Settings → Fiscal Localization 选 Australia。演练中会生成 7 个日记账和 21 个税。
3. **用户权限**：
   - 管理员：允许的公司加上 TAB Entertainment。
   - Q Club 员工：默认公司和允许的公司都只设 TAB Entertainment。
   - AUSHARE 员工：保持不变（只有 AUSHAREU）。
4. **网站归属**：Website → Configuration → Settings，选中 Q Club 网站，Company 改为 TAB Entertainment。AUSHARE 网站不动。
5. **商品保持不绑定公司**：Sales → Products 列表加上 Company 列，确认全部为空（演练时 61 个商品全部为空）。以后新建商品也不要填公司，否则在 Q Club 注册的顾客到 AUSHARE 会看不到它。
6. **支付方式**：新建公司时 Odoo 会给 TAB Entertainment 自动复制几项停用的支付方式，保持停用即可。Q Club 的 Stripe 在阶段 4 上线配置时再启用（只限 Q Club 网站）。

## 三、执行后检查

- [ ] AUSHARE：首页、商城、商品页、购物车、结账页与执行前的截图一致；用一个现有顾客账号登录正常
- [ ] AUSHARE 的支付方式、日记账没有变化（Settings → Payment Providers；Accounting → Journals，切换到 AUSHAREU 查看）
- [ ] （可选）再次导出 AUSHARE 指纹并对比：除新公司的停用支付方式外应完全一致（新版 `tools/iso_fingerprint.sql` 已只比较 AUSHARE 公司的支付方式）
- [ ] Q Club：网站正常打开；用现有顾客账号能登录；在 Q Club 新注册的账号归属 TAB Entertainment
- [ ] 只能访问 AUSHAREU 的员工，在后台看不到 Q Club 的桌台和预约（模块安装后检查）

## 四、回退

- 发现问题时，把 Q Club 网站的 Company 改回 AUSHAREU，即可恢复原状；新公司可以保留或归档。
- 如果出现数据问题，用第一节的备份恢复。

## 五、演练记录

| 日期 | 环境 | 结果 |
|---|---|---|
| 2026-11-11 | 本机生产库副本，生产版本代码 `203c9270`，命令行完成第二节第 1、2、4 步 | ✅ 成功；AUSHARE 公司的日记账和支付方式不变；指纹仅多出新公司的 5 个停用支付方式 |
