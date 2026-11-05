# qclub-odoo

Q Club 台球厅在线预约系统（Odoo 19 社区版模块 `qclub_billiard`）。

- 开发规则：[AGENTS.md](AGENTS.md)（Codex 与 Claude Code 共用）
- 需求规格：`docs/spec/`
- 命令入口：`make help`

## 快速开始

```
make up       # 首次约需几分钟：拉镜像、构建基础模板库
make test     # 运行测试
make report   # 生成 docs/reports/report.md
make demo     # 启动本机演示环境 http://localhost:8069（见 docs/demo/phase-1.md）
```

## 首次接入校准

`tools/odoo_log_to_junit.py` 按日志格式解析测试结果，首次运行后请对照
`docs/reports/odoo-test.log` 检查：冒烟测试的 3 个用例是否都被识别为"通过"。
解析与真实日志不一致时，先修解析器，再开始写业务代码。
