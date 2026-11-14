#!/usr/bin/env python3
"""生成测试报告：测试总览 + 需求编号对照表。

约定：测试方法名包含小写需求编号，如 test_bk_004_overlap_rejected 对应需求 BK-004。
环境变量：
  SPEC_PREFIXES  参与覆盖检查的编号前缀，默认 CFG,TBL,BK,WEB,SEC,ISO,ADM,BRD,CO,PAY,RF（DEMO 由演示验收检验，阶段 4 的 NS/ST 暂不检查）
  STRICT=1       存在未覆盖需求或失败测试时返回非零退出码（CI 在阶段 1 完成后开启）
"""
import datetime
import glob
import os
import re
import sys
import xml.etree.ElementTree as ET

REPORTS = "docs/reports"
PREFIXES = set(os.environ.get("SPEC_PREFIXES", "CFG,TBL,BK,WEB,SEC,ISO,ADM,BRD,CO,PAY,RF").split(","))
STRICT = os.environ.get("STRICT") == "1"
ROW = re.compile(r"^\|\s*([A-Z]{2,4}-\d{3})\s*\|\s*(.*?)\s*\|\s*$")
TID = re.compile(r"(?:^|_)([a-z]{2,4})_(\d{3})(?=_|$)")


def load_spec():
    spec = {}
    for path in sorted(glob.glob("docs/spec/*.md")):
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        for line in lines:
            m = ROW.match(line)
            if m and m.group(1).split("-")[0] in PREFIXES:
                spec[m.group(1)] = m.group(2)
    return spec


def load_junit():
    path = os.path.join(REPORTS, "junit.xml")
    if not os.path.exists(path):
        return [], None
    root = ET.parse(path).getroot()
    cases = []
    for tc in root.iter("testcase"):
        status = "fail" if (tc.find("failure") is not None or tc.find("error") is not None) else (
            "skip" if tc.find("skipped") is not None else "pass")
        detail = ""
        for tag in ("failure", "error"):
            node = tc.find(tag)
            if node is not None:
                detail = (node.text or "")[:1500]
        cases.append((tc.get("classname", ""), tc.get("name", ""), status, detail))
    return cases, root


def main():
    spec = load_spec()
    cases, _ = load_junit()
    by_id = {}
    for _cls, name, status, _d in cases:
        for m in TID.finditer(name.lower()):
            by_id.setdefault(f"{m.group(1).upper()}-{m.group(2)}", []).append((name, status))

    n_pass = sum(1 for c in cases if c[2] == "pass")
    n_fail = sum(1 for c in cases if c[2] == "fail")
    n_skip = sum(1 for c in cases if c[2] == "skip")
    covered = [i for i in spec if i in by_id]
    uncovered = [i for i in spec if i not in by_id]
    req_failed = [i for i in covered if any(s == "fail" for _n, s in by_id[i])]

    out = [
        "# qclub_billiard 测试报告", "",
        f"生成时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", "",
        "## 一、测试总览", "",
        "| 项目 | 数量 |", "|---|---|",
        f"| 测试总数 | {len(cases)} |", f"| 通过 | {n_pass} |", f"| 失败/错误 | {n_fail} |", f"| 跳过 | {n_skip} |", "",
        "## 二、需求覆盖", "",
        f"参与检查的需求 {len(spec)} 条：已有测试 {len(covered)} 条，**未覆盖 {len(uncovered)} 条**，其中测试失败 {len(req_failed)} 条。", "",
        "| 编号 | 需求 | 测试 | 结果 |", "|---|---|---|---|",
    ]
    for rid, text in spec.items():
        short = text if len(text) <= 60 else text[:60] + "…"
        if rid in by_id:
            names = "<br>".join(n for n, _s in by_id[rid])
            res = "❌ 失败" if any(s == "fail" for _n, s in by_id[rid]) else "✅ 通过"
        else:
            names, res = "—", "⚠️ 未覆盖"
        out.append(f"| {rid} | {short} | {names} | {res} |")

    fails = [c for c in cases if c[2] == "fail"]
    if fails:
        out += ["", "## 三、失败详情", ""]
        for cls, name, _s, detail in fails:
            out += [f"### {cls}.{name}", "", "```", detail.strip(), "```", ""]

    out += ["", "## 四、需要人工验收的项目（自动化无法替代）", "",
            "- [ ] 使用 Stripe 测试卡完成一次真实的网页支付（成功 / 失败 / 中途放弃）",
            "- [ ] 目测 AUSHARE 网站：页面、产品、邮件均无变化",
            "- [ ] 手机浏览器上预约网格的显示和操作",
            "- [ ] 周五/周六跨午夜时段的预约，在页面、邮件上的文案是否清楚",
            "- [ ] 员工实际收到新预约通知"]
    os.makedirs(REPORTS, exist_ok=True)
    path = os.path.join(REPORTS, "report.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    print(f"[report] 测试 {len(cases)}（失败 {n_fail}），需求 {len(spec)}（未覆盖 {len(uncovered)}）-> {path}")
    if STRICT and (uncovered or n_fail):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
