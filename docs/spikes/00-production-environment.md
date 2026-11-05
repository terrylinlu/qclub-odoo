# 穿刺 0：生产环境底数

日期：2026-11-06（计划）　执行：你（生产服务器上只读检查）+ Claude Code（整理结论）　限时：半天　结论：**待填写**

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

（待填写）

## 四、结论

（待填写）

## 五、对规格 / 设计的影响

（待填写）

## 六、遗留问题

（待填写）
