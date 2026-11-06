# 穿刺 0：生产环境底数

日期：2026-11-06　执行：terrylinlu（生产服务器上只读检查）+ Claude Code（整理结论）　限时：半天　结论：**可行**（`btree_gist` 可由 Odoo 账号启用）；另发现**无备份**等运维 / 安全问题，见第四节

> 本文件第二节是检查表。请在生产服务器上逐项执行，把输出（去掉密码、IP 等敏感信息）发给 Claude Code，由 Claude Code 填写第三至六节。
> **全部是只读操作**：不安装、不修改、不重启任何东西。数据库查询都放在只读事务里。

## 一、问题

1. 生产 PostgreSQL 的版本？有没有 `btree_gist` 扩展可用？Odoo 使用的数据库账号能否启用它？（BK-004 排他约束的前提）
2. 生产 Odoo 的版本和构建日期？是否与测试镜像同属 19.0？部署方式（直接安装 / Docker）、`addons_path`、服务名？
3. 生产库已安装哪些模块？（决定 AUSHARE 隔离回归的范围，穿刺 1 用）
4. 两个网站的 id、名称、域名？Q Club 是否为 id 3？
5. 反向代理（Nginx 等）是否转发 Odoo 的 WebSocket（`/websocket`，通常对应 8072 端口）？Odoo 的 `workers`、`proxy_mode` 如何配置？（穿刺 5）
6. 备份方式和频率？是否演练过恢复？（穿刺 1 需要一份备份）

## 二、检查表（在生产服务器上执行）

### A. PostgreSQL 与 `btree_gist`（问题 1）

用 Odoo 平时连接数据库的那个账号连接生产库（把 `<生产库名>` 换成实际库名，例如 `AUSHARE`），执行：

```sql
BEGIN READ ONLY;

-- 1. PostgreSQL 版本
SELECT version();

-- 2. btree_gist 是否可用、是否已安装（installed_version 非空表示已安装）
SELECT name, default_version, installed_version
FROM pg_available_extensions WHERE name = 'btree_gist';

-- 3. btree_gist 是否为"可信扩展"（PostgreSQL 13 起为 true：有建库对象权限的非超级用户也能启用）
SELECT name, version, superuser, trusted
FROM pg_available_extension_versions WHERE name = 'btree_gist' ORDER BY version DESC LIMIT 1;

-- 4. 当前账号是什么角色、能否在本库创建对象
SELECT current_user,
       r.rolsuper   AS is_superuser,
       r.rolcreatedb AS can_create_db,
       has_database_privilege(current_user, current_database(), 'CREATE') AS can_create_in_db,
       pg_get_userbyid(d.datdba) AS db_owner
FROM pg_roles r, pg_database d
WHERE r.rolname = current_user AND d.datname = current_database();

ROLLBACK;
```

### B. Odoo 版本与部署（问题 2）

```bash
# 部署方式：有没有 Docker 容器在跑 Odoo
docker ps --format '{{.Names}}  {{.Image}}' 2>/dev/null | grep -i odoo

# 直接安装时：服务名与状态
systemctl list-units --type=service | grep -i odoo

# Odoo 版本（直接安装时；Docker 时在容器内执行）
odoo --version 2>/dev/null || odoo-bin --version 2>/dev/null

# 配置文件里与本项目相关的几项（请勿发送 admin_passwd、db_password 等密码行）
grep -E '^\s*(addons_path|workers|proxy_mode|gevent_port|longpolling_port|max_cron_threads|db_name|dbfilter|list_db)\s*=' /etc/odoo/odoo.conf
```

也可以在后台 **Settings → 页面底部** 查看 Odoo 版本号和构建日期。

### C. 已安装模块、网站（问题 3、4）

```sql
BEGIN READ ONLY;

SELECT name, latest_version FROM ir_module_module
WHERE state = 'installed' ORDER BY name;

SELECT id, name, domain FROM website ORDER BY id;

SELECT id, name FROM res_company ORDER BY id;

ROLLBACK;
```

### D. 反向代理与 WebSocket（问题 5）

```bash
# Nginx 配置中与 Odoo、WebSocket 相关的部分
grep -rnE 'upstream|proxy_pass|8069|8072|websocket|Upgrade|Connection' /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null
```

### E. 备份（问题 6）

请简要说明：备份由谁、用什么方式（Odoo 数据库管理页面 / `pg_dump` / 云服务商快照）、多久一次、存在哪里、最近一次恢复演练是什么时候。

## 三、结果

> 原始输出已由执行人核对；本节只保留摘要，不记录 IP 地址、主机名、密码或客户数据。

### A. PostgreSQL 与 `btree_gist`

| 项目 | 结果 |
|---|---|
| PostgreSQL | 16.15（Ubuntu 24.04 软件包），与测试环境同为 16 |
| `btree_gist` | 1.7 可用；AUSHARE 库中**尚未启用**（`installed_version` 为空） |
| 是否可信扩展 | `trusted = t` |
| AUSHARE 库所有者 | `odoo` |
| 能登录的数据库账号 | `odoo`、`postgres`、`ubuntu`，**三者都是超级用户**，都能在 AUSHARE 中建对象 |

### B. Odoo 版本与部署

| 项目 | 结果 |
|---|---|
| 版本 | Odoo Server 19.0，源码安装，git 提交 `203c9270`，**2026-03-17** |
| 测试 / 演示镜像 | `odoo:19.0`，构建于 2026-11-02 → 生产代码**旧约 7.5 个月** |
| 部署 | 非 Docker；`/opt/odoo-server`，Python 虚拟环境，systemd 服务 `odoo.service` |
| 运行身份 | 系统用户 `ubuntu` |
| 配置文件 | `/opt/odoo-server/odoo.conf` |
| `addons_path` | `/opt/odoo-server/addons`, `/opt/odoo-server/custom_addons` |
| `workers` / `max_cron_threads` | 5 / 2（多进程，另有 1 个 gevent 进程） |
| `proxy_mode` | True |
| `longpolling_port` | 8072（Odoo 19 中的新名称为 `gevent_port`） |
| `list_db` / `dbfilter` | **均未设置**（`list_db` 默认为 True） |
| 监听地址 | 8069、8072 都监听 `0.0.0.0`（所有网卡） |
| `/web/database/manager` | 返回 500（`psycopg2.InterfaceError: Cursor already closed`，Odoo 自身缺陷），**不等于已禁用** |

### C. 模块、网站、公司、支付

| 项目 | 结果 |
|---|---|
| 已安装模块 | 99 个，均为 19.0；含 `account`、`l10n_au`、`sale`、`stock`、`event`、`website_sale`、`website_blog`、`payment_stripe`、`payment_paypal`、`google_gmail`、`microsoft_outlook` 等 |
| 网站 | id 1 **AUSHARE**（`https://shop.aushare.com.au`）；id 3 **Q Club**（`https://cueclub.com.au`） |
| 网站所属公司 | 两个网站都属于公司 2 **AUSHAREU PTY LTD**，币种 **AUD** |
| 公司 | 共 3 个：AUSHAREU PTY LTD，以及演示数据带来的 "My Company (San Francisco)"、"My Company (Chicago)" |
| 演示数据 | `base`、`website`、`website_sale` 的 `demo = t`：**建库时装了演示数据** |
| 演示默认账户 | `admin`、`demo`、`portal` 三个登录名**都不存在**（已删除或改名）——已核查 |
| 启用的支付方式 | 仅 1 个：`custom`（公司 2）；**Stripe 模块已装但未启用** |
| 产品 | 61 个，无挂在 Q Club 网站下的产品 |

### D. 反向代理

| 站点 | 域名 | HTTPS | `/websocket` → 8072 | `Upgrade` / `Connection` 头 | `proxy_http_version 1.1` |
|---|---|---|---|---|---|
| `aushare-shop` | shop.aushare.com.au | ✅ Certbot | ✅ | ✅ | ✅ |
| `odoo` | cueclub.com.au、www.cueclub.com.au | ✅ | ✅ | ✅ | ❌ **缺少** |

### E. 备份

**目前从未做过任何备份**，也没有恢复演练。

## 四、结论

1. **`btree_gist`：可行。** PostgreSQL 16、扩展可用且为可信扩展；Odoo 使用的 `odoo` 账号是 AUSHARE 的所有者（且为超级用户），能执行 `CREATE EXTENSION btree_gist`。BK-004 的排他约束方案**不需要改**。
2. **版本差异需要处理。** 生产代码（2026-03-17）比测试镜像（2026-11-02）旧约 7.5 个月：缺少安全补丁，且"测试环境通过"不等于"生产能装"。
3. **品牌与支付风险比预想小。** 两个网站同属一个公司、币种 AUD，与 AGENTS.md 一致；生产没有启用 Stripe，Q Club 押金可单独配置 Stripe 并限定在 Q Club 网站，不触碰 AUSHARE 现有结账。
4. **实时通知：** Q Club 站点的 Nginx 缺 `proxy_http_version 1.1`，WebSocket 很可能无法升级（穿刺 5 提前发现）。
5. **运维与安全（与本模块无关，但影响上线）：**
   - 🔴 **无任何备份**——最高优先级
   - 🟠 数据库管理接口未禁用（`list_db` / `dbfilter` 未设置），只靠主密码保护
   - 🟠 8069 / 8072 监听所有网卡：若 AWS 安全组未拦截，可绕过 Nginx 与 HTTPS 直接访问
   - 🟡 生产 Odoo 缺 7.5 个月的补丁
   - 🟡 Odoo 以有 sudo 权限的 `ubuntu` 用户运行；三个数据库账号都是超级用户
   - ✅ 演示默认账户已不存在

## 五、对规格 / 设计的影响

| 影响 | 处理 |
|---|---|
| 生产库尚未启用 `btree_gist` | 模块在 `init()` 中执行 `CREATE EXTENSION IF NOT EXISTS btree_gist`（生产上 `odoo` 是库所有者，必定成功；已启用时无操作）。小改动，阶段 2 第一个任务一并完成，需有测试 |
| 生产与测试代码版本不同 | 穿刺 1 使用生产的代码版本（提交 `203c9270`）在生产库副本上试装；生产升级到最新 19.0 后再固定测试镜像与之对齐 |
| 生产装有演示数据、有 3 个公司 | 测试库为单公司、无演示数据。不改设计；穿刺 1 在真实副本上验证安装与 `iso-check` |
| Q Club 域名为 `cueclub.com.au` | 阶段 2 预约页、邮件中的链接以网站域名生成，不写死 |
| Stripe 未启用 | 穿刺 3：为 Q Club 单独配置 Stripe 并限定 Q Club 网站 |
| Q Club 站点 WebSocket 配置缺一行 | 穿刺 5 / 阶段 5 前：在 `/etc/nginx/sites-available/odoo` 的 `location /websocket` 中加 `proxy_http_version 1.1;` |
| 规格 | **无需修改** |

## 六、遗留问题

- AWS 安全组是否已拦截 8069 / 8072（需在 AWS 控制台确认）
- 穿刺 1 需要的生产备份：首次手动备份完成后，在本机恢复为 `qclub_prodcopy`
- 生产升级到最新 19.0：需先在副本上验证，安排维护窗口
- 以上运维 / 安全事项列入 `docs/progress.md` 第八节待办，由你决定时间并执行
