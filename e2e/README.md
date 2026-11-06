# 占用网格端到端测试

前提仅需 Docker 和运行中的 `make demo` 演示环境。
首次或旧预约过期后用 `make demo-reset` 重建演示数据。
Q Club 开启 Online Booking，关闭 Login Required to View Availability。

在仓库根目录运行：

```sh
make e2e
```

每次运行先用 `e2e/Dockerfile` 构建本地镜像 `qclub-e2e:1.56.1`，重复运行利用 Docker 层缓存。
由于 MCR 镜像的大层下载在此环境反复被重置，改用 Docker Hub 的 `node:22-bookworm` 安装 Chromium。
Dockerfile 中的 Playwright 版本必须与 `e2e/package.json` 中固定的 `@playwright/test` 1.56.1 匹配。
无需在宿主机安装 Node.js 或浏览器，WSL Ubuntu 26.04 也可使用镜像内的 Debian Bookworm 浏览器环境。
容器内执行 `npm ci --no-audit --no-fund` 和 `npx playwright test`。
以宿主用户 UID/GID 运行，设置 `HOME=/tmp`，生成的测试结果不会归 root 所有。

默认 Q Club 地址为 `http://qclub.localhost:8069`，可覆盖：

```sh
E2E_BASE_URL=http://qclub.localhost:8069 make e2e
```

`E2E_BASE_URL` 和 `CI` 会传入容器。容器使用 host 网络及 host IPC，
Chromium 自行将 `*.localhost` 解析为回环地址，通过宿主网络访问演示服务器。
AUSHARE API 隔离测试直接访问 `127.0.0.1`，使用基础 URL 的协议及端口，
并显式发送 `Host: aushare.localhost:<端口>`，不依赖 Node 的 `*.localhost` DNS 解析。

仅使用 Chromium，分别运行桌面与 Pixel 7 手机视口。
占用测试会在允许日期范围内寻找演示预约；若找不到未来占用，请重建演示数据。
测试不创建或修改预约，网格本任务只读。
失败时可查看 `e2e/test-results/` 中保留的 trace。
