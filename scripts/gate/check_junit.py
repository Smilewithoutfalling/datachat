"""G1：断言 oracle 的 junit 结果是"每道题恰好一条且全部通过"。

用法：python scripts/gate/check_junit.py gate.xml
期望数取 len(questions.QUESTIONS)，与 parametrize 同源 —— 抓的是 collection 掉了 params / 被降级成 skip，
不是"题目数变了"。不依赖 shell（Windows runner 默认 pwsh），不解析 pytest 的人类可读输出。
scripts/gate 不是包：以脚本运行时 sys.path[0] 就是本目录，故直接 import questions。
"""
import sys
import xml.etree.ElementTree as ET

import questions


def _suite(path: str):
    root = ET.parse(path).getroot()
    return root if root.tag == "testsuite" else root.find("testsuite")


def counts(path: str) -> dict[str, int]:
    suite = _suite(path)
    return {k: int(suite.get(k, 0)) for k in ("tests", "failures", "errors", "skipped")}


def failure_messages(path: str) -> list[str]:
    """每条 testcase 的失败文本（failure / error 元素），按文件顺序。

    从 XML 里读而不是从 pytest 的 stdout 里 grep：stdout 是给人看的，pytest 版本、
    -q 级别、输出截断都会改变它；XML 的 message 是契约，pytest 一直写。
    message 属性缺失时退回元素正文（--tb 会把断言消息放在正文里）。
    """
    out = []
    for tc in _suite(path).iter("testcase"):
        for tag in ("failure", "error"):
            el = tc.find(tag)
            if el is not None:
                out.append(el.get("message") or (el.text or ""))
    return out


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
