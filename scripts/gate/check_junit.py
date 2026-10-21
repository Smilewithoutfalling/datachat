"""G1：断言 oracle 的 junit 结果是"每道题恰好一条且全部通过"。

用法：python scripts/gate/check_junit.py gate.xml
期望数取 len(questions.QUESTIONS)，与 parametrize 同源 —— 抓的是 collection 掉了 params / 被降级成 skip，
不是"题目数变了"。不依赖 shell（Windows runner 默认 pwsh），不解析 pytest 的人类可读输出。
scripts/gate 不是包：以脚本运行时 sys.path[0] 就是本目录，故直接 import questions。
"""
import sys
import xml.etree.ElementTree as ET

import questions


def counts(path: str) -> dict[str, int]:
    root = ET.parse(path).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    return {k: int(suite.get(k, 0)) for k in ("tests", "failures", "errors", "skipped")}


def main(argv: list[str]) -> int:
    expect = {"tests": len(questions.QUESTIONS), "failures": 0, "errors": 0, "skipped": 0}
    got = counts(argv[0])
    print(f"期望 {expect}\n实际 {got}")
    if got != expect:
        print("✗ oracle 结果不符：必须每道题恰好一条且全部通过（不允许 skip）")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
