#!/usr/bin/env python3
"""把 Odoo 测试日志转换成 JUnit XML，并给出通过/失败判定。

用法: odoo_log_to_junit.py <odoo-test.log> <junit.xml>
退出码: 0=全部通过；1=有失败，或没有运行任何测试；2=安装阶段出错

注意：这是按日志格式解析的，Odoo 版本不同日志格式可能有差异。
首次接入真实日志时需要用真实输出校准（见 README），校准前不要相信"0 个失败"。
"""
import re
import sys
from xml.sax.saxutils import escape, quoteattr

LOG_LINE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+ ")
START = re.compile(r"odoo\.addons\.(\w+)\.tests\.[\w.]+: Starting (\w+)\.(\w+)")
FAIL = re.compile(r" (?:ERROR|CRITICAL) \S+ \S+: (FAIL|ERROR): (\w+)\.(\w+)")
SUMMARY = re.compile(r"(\d+) failed, (\d+) error\(s\) of (\d+) tests")


def main(log_path, xml_path):
    lines = open(log_path, encoding="utf-8", errors="replace").read().splitlines()
    order, module_of, kinds, details = [], {}, {}, {}
    current, summary, install_error = None, None, False

    for ln in lines:
        if LOG_LINE.match(ln):
            current = None
            m = START.search(ln)
            if m:
                mod, cls, name = m.groups()
                key = f"{cls}.{name}"
                if key not in module_of:
                    order.append(key)
                    module_of[key] = mod
                continue
            m = FAIL.search(ln)
            if m:
                kind, cls, name = m.groups()
                key = f"{cls}.{name}"
                if key not in module_of:
                    order.append(key)
                    module_of[key] = "unknown"
                kinds[key] = kind
                details[key] = [ln]
                current = key
                continue
            m = SUMMARY.search(ln)
            if m:
                summary = tuple(int(x) for x in m.groups())
            if " CRITICAL " in ln:
                install_error = True
        elif current:
            details[current].append(ln)
        elif "Traceback (most recent call last)" in ln:
            install_error = True

    failures = sum(1 for k in kinds.values() if k == "FAIL")
    errors = sum(1 for k in kinds.values() if k == "ERROR")
    total = len(order)

    cases = []
    for key in order:
        cls, name = key.split(".", 1)
        head = f'<testcase classname={quoteattr(module_of[key] + "." + cls)} name={quoteattr(name)}'
        if key in kinds:
            tag = "failure" if kinds[key] == "FAIL" else "error"
            body = escape("\n".join(details[key])[:4000])
            cases.append(f"{head}><{tag} message={quoteattr(kinds[key])}>{body}</{tag}></testcase>")
        else:
            cases.append(head + "/>")
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<testsuite name="qclub_billiard" tests="{total}" failures="{failures}" errors="{errors}">\n'
        + "\n".join(cases) + "\n</testsuite>\n"
    )
    open(xml_path, "w", encoding="utf-8").write(xml)

    print(f"[junit] 共 {total} 个测试，失败 {failures}，错误 {errors} -> {xml_path}")
    if total == 0:
        print("[junit] 没有检测到任何被运行的测试。" + ("日志中有安装阶段错误，请先查看 odoo-test.log。" if install_error else ""))
        return 2 if install_error else 1
    if summary and (summary[0] + summary[1]) > (failures + errors):
        print(f"[junit] Odoo 汇总行报告 {summary[0]} 失败 / {summary[1]} 错误，但解析器只识别到 {failures + errors} 个。"
              "解析规则需要按真实日志校准，已按失败处理。")
        return 1
    if install_error:
        print("[junit] 日志中有安装阶段错误，已按失败处理。")
        return 2
    return 1 if (failures or errors) else 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2]))
