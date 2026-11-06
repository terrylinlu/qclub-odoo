# 穿刺 2：同一公司下的品牌区分（邮件部分）

日期：2026-11-06　执行：Claude Code（本机，不接触生产）　限时：半天　结论：**有条件可行**（邮件必须用本模块自己的版式和 Q Club 发件人；生产要为 Q Club 另配发件邮箱）

## 一、问题

两个网站共用公司 AUSHAREU PTY LTD。任务 2.2 第一次给顾客发邮件（"Booking received – awaiting deposit"），会不会显示成 AUSHARE：发件人、页眉页脚、logo、链接域名？
（Stripe 账单商户名、发票抬头属于阶段 4，本次只记录待办，不验证。）

## 二、做了什么

在 Odoo shell 中读取配置，并用 Odoo 默认的通知版式（`mail.mail_notification_light`，大多数模块的邮件都用它）渲染一封测试邮件，看收件人会看到什么；**全部回滚，不发送、不保存**。分别在：

- `qclub_demo`（演示库）
- `qclub_prodcopy`（本机的生产备份副本，真实配置；只读出发件服务器的服务商和发件过滤，不读取账号密码）

## 三、结果（以生产副本为准）

| 项目 | 结果 | 对 Q Club 的影响 |
|---|---|---|
| 发件服务器 | 只有 1 个：AUSHARE 的腾讯企业邮，发件过滤 = `service@aushare.com.au` | Q Club 邮件会从 AUSHARE 的邮箱发出（Odoo 按发件过滤改写发件人） |
| 默认发件人 | 未设置 `mail.default.from`、别名域名 | 系统邮件发件人回落到公司或 OdooBot |
| 默认版式页脚 | "AUSHAREU PTY LTD"、AUSHARE 的电话、`service@aushare.com.au`、"Powered by Odoo" | 顾客看到的是 AUSHARE 的联系方式 |
| 默认版式 logo | `/logo.png?company=2`，即公司 logo | 显示 AUSHARE 的 logo |
| 系统基础网址 `web.base.url` | `https://shop.aushare.com.au` | 用它生成的链接会指向 AUSHARE；必须改用 Q Club 网站自己的域名（`cueclub.com.au`） |
| 网站 | AUSHARE = `shop.aushare.com.au`，Q Club = `cueclub.com.au`，同属公司 2 | 网站本身有各自的名称、域名、logo，可用于品牌化 |

## 四、结论

**有条件可行。** Odoo 的默认邮件版式按"公司"取名称、logo 和联系方式，同公司下无法区分网站，所以：

1. 预约邮件**不用 Odoo 默认版式**，由本模块自带一个 Q Club 版式：标题、logo 和链接都取自 Q Club **网站**（名称、logo、域名），页脚写 Q Club 的联系方式，不出现公司名、AUSHARE 联系方式和 "Powered by Odoo"
2. 发件人取自 Q Club 的预约设置（新配置项），不使用公司邮箱
3. **生产上线前**（阶段 4 之前即可，阶段 2 不对外）：需要一个 Q Club 自己的发件邮箱（例如 `bookings@cueclub.com.au`），并在 Odoo 中添加一个只用于该地址的发件服务器（发件过滤 = 该地址），同时为 `cueclub.com.au` 配好 SPF / DKIM。否则邮件仍会被改写成从 `service@aushare.com.au` 发出，或被收件方当成伪造邮件

## 五、对规格 / 设计的影响

- 任务 2.2 设计说明第六节按第四节结论设计邮件
- 新增生产待办（`progress.md` 第八节）：Q Club 发件邮箱、发件服务器、SPF / DKIM
- Stripe 账单商户名、发票抬头：阶段 4 的设计中处理（穿刺 3 一起看）
