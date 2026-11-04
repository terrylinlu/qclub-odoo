# 测试环境校准记录（2026-11-04）

分支：`chore/calibrate-test-env`。没有执行 Git 写操作、业务实现、规格修改、已有测试修改或生产操作。

## 命令结果

耗时由 `/usr/bin/time` 测量，单位为秒，退出码为外层命令退出码。

| 命令 / 阶段 | 耗时 | 退出码 | 结果 |
|---|---:|---:|---|
| make up（沙箱） | 0.30 | 2 | Docker socket 权限拒绝 |
| make up（审批后） | 1.21 | 0 | 测试数据库健康，基础模板已存在 |
| make test（沙箱） | 0.20 | 2 | Docker socket 权限拒绝 |
| make report（基线测试完成前） | 0.09 | 0 | 使用原有 JUnit，不能作为本次验证证据 |
| make test（审批后，基线） | 14.51 | 0 | 3 通过，含 without-demo 警告 |
| make report（基线后） | 0.03 | 0 | 3 通过，39 条业务需求未覆盖 |
| make test（修正布尔参数） | 7.48 | 0 | 3 通过，without-demo 警告消失 |
| make test（临时失败插件，见下） | 7.88 | 2 | 1 failure、1 error，解析器退出 1 |
| make report（失败路径） | 0.03 | 0 | 报告显示失败/错误 2；默认非 STRICT 模式退出 0 |
| make lint（沙箱） | 0.07 | 2 | Docker socket 权限拒绝 |
| docker image inspect（沙箱） | 0.06 | 1 | Docker socket 权限拒绝 |
| make lint（审批后） | 19.14 | 2 | 9 个已有 lint 问题，见下 |
| docker image inspect（审批后） | 0.13 | 0 | 摘要见下 |
| make test（删除临时插件后） | 8.02 | 0 | 3 通过，0 失败，0 错误 |
| make report（最终） | 0.03 | 0 | 3 通过，39 条业务需求未覆盖 |

Docker 操作在沙箱内被拒绝，随后经权限审批运行。未静默绕过权限检查。

## 修改及校准方法

仅将 Makefile 的两处及 docker/docker-compose.test.yml 的一处 `--without-demo=all` 改为 `--without-demo=True`。

为避免修改已有 tests/__init__.py，临时插件位于 addons/qclub_billiard/calibration_addons/qclub_env_calibration，依赖 qclub_billiard。仅包含两个临时测试，分别 self.fail 和 raise RuntimeError。执行命令：

```sh
make test MODULE=qclub_env_calibration 'ODOO=docker compose -f docker/docker-compose.test.yml run --rm -T odoo odoo --addons-path=/mnt/extra-addons,/mnt/extra-addons/qclub_billiard/calibration_addons'
```

解析器识别准确，因此未修改解析器，也无需新增解析器回归测试或更改 lint 的测试运行方式。
真实失败原始日志、JUnit 和失败报告保存在 docs/reports/calibration-failure/。这些文件按现有 .gitignore 不入库。临时插件已完整删除，git status 确认不存在临时测试改动。

三个冒烟方法均在最终 JUnit 中识别为通过：test_000_module_installed、test_001_two_websites_exist、test_002_btree_gist_available。Odoo tests.stats 的计数包含额外统计，判定使用真实 Starting 行和最终 3 tests 汇总。

## 未完成项及规则差异

make lint 未通过，9 个问题均来自原有文件，未自动修复或忽略：

- addons/qclub_billiard/__init__.py：F401（1 个）。
- addons/qclub_billiard/__manifest__.py：B018（1 个）。
- addons/qclub_billiard/tests/__init__.py：F401（1 个，属于受保护的已有测试）。
- tools/make_report.py：EXE001（1 个）、SIM115（2 个）。
- tools/odoo_log_to_junit.py：EXE001（1 个）、SIM115（2 个）。

因此尚未满足 AGENTS.md 的 lint 全绿要求。修复这些问题需要扩大此次允许的修改范围；不应通过忽略检查掩盖问题。

AGENTS.md 的原始修改目录限制不含 Makefile/tools，本次用户指令明确授权相关环境工具工作。Compose 中已有数据库测试密码字面值，与“密钥只通过环境变量提供”的规则不一致；未打印其值或更改凭据配置。39 条业务需求目前均未覆盖，此次仅校准环境，未实现业务需求。报告中的支付、网站回归等人工验收项未执行。

Makefile 现有测试管道含 `|| true`，本次确认测试失败可由解析器传递为 make 非零退出码；未验证其他基础设施故障路径。Odoo 另有 http-interface 默认值警告，非本次 without-demo 警告，未修改。

## Odoo 镜像摘要

```text
odoo@sha256:5e755c725b3c43cf0be16d579904e1418300db3a2c44952f928eaddbcb0cc16d
```

未修改镜像标签。

## 真实失败日志片段

```text
2026-11-04 05:44:21,728 1 INFO qclub_test odoo.addons.qclub_env_calibration.tests.test_calibration: Starting TestCalibration.test_environment_error ... 
2026-11-04 05:44:21,730 1 INFO qclub_test odoo.addons.qclub_env_calibration.tests.test_calibration: ====================================================================== 
2026-11-04 05:44:21,730 1 ERROR qclub_test odoo.addons.qclub_env_calibration.tests.test_calibration: ERROR: TestCalibration.test_environment_error
Traceback (most recent call last):
  File "/mnt/extra-addons/qclub_billiard/calibration_addons/qclub_env_calibration/tests/test_calibration.py", line 10, in test_environment_error
    raise RuntimeError("CALIBRATION intentional runtime error")
RuntimeError: CALIBRATION intentional runtime error
 
2026-11-04 05:44:21,731 1 INFO qclub_test odoo.addons.qclub_env_calibration.tests.test_calibration: Starting TestCalibration.test_environment_failure ... 
2026-11-04 05:44:21,732 1 INFO qclub_test odoo.addons.qclub_env_calibration.tests.test_calibration: ====================================================================== 
2026-11-04 05:44:21,732 1 ERROR qclub_test odoo.addons.qclub_env_calibration.tests.test_calibration: FAIL: TestCalibration.test_environment_failure
Traceback (most recent call last):
  File "/mnt/extra-addons/qclub_billiard/calibration_addons/qclub_env_calibration/tests/test_calibration.py", line 7, in test_environment_failure
    self.fail("CALIBRATION intentional assertion failure")
AssertionError: CALIBRATION intentional assertion failure
 
2026-11-04 05:44:21,734 1 INFO qclub_test odoo.addons.base.models.ir_attachment: filestore gc 0 checked, 0 removed 
2026-11-04 05:44:21,734 1 INFO qclub_test odoo.service.server: 2 post-tests in 0.01s, 6 queries 
2026-11-04 05:44:21,735 1 INFO qclub_test odoo.tests.stats: qclub_env_calibration: 4 tests 0.01s 6 queries 
2026-11-04 05:44:21,735 1 ERROR qclub_test odoo.tests.result: 1 failed, 1 error(s) of 2 tests when loading database 'qclub_test'
```

## 建议提交文件

- Makefile
- docker/docker-compose.test.yml
- docs/test-env-calibration.md

不提交临时测试、业务文件或 docs/reports/ 下的生成产物。
