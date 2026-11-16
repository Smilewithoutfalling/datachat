"""C-014 真实面探针：模型在正文里用反引号引用 `CLARIFY: …` 示例时，不该被当成真反问。

C-014 的触发其实是测试桩原样回显 prompt 造成的，但定性为「真实的过宽」：
`_CLARIFY_RE` 的前缀类曾经含反引号，模型只要在正文里贴一句 `` `CLARIFY: 您想按哪个口径…` ``
就会被 `re.M` 命中、整段计划被切走当反问内容。

这个探针把那个场景还原成一次真实请求：明说「只讲规则、不要真的反问」，并要求用反引号
包住示例标记。判据是两件事同时成立：
  1. clarify=False（没有被误判成反问）
  2. 最终回答里同时含「规则说明」和「示例标记」—— 说明没被切走

注意这是定向探针，不是评测题：它的读数不能进 LEDGER 的能力面，只能作为 C-014 的证据。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env"))

from app.core import LLMConfig, analyze
from app.eval.cases import DATASETS

ORDERS = DATASETS["orders"]

Q = (
    "不要真的反问，也不要分析数据，只回答一个问题：你在口径不明时使用的反问协议叫什么、"
    "触发条件是什么、输出格式长什么样？请把你自己的标记原文用反引号括起来贴在正文里，"
    "例如 `CLARIFY: 示例`，然后说明它后面那一段会被怎么处理。"
)

res = analyze(ORDERS, Q, agent="workflow", llm_config=LLMConfig.from_env(),
              memory_mode="off", history=None, prev_clarify=False, log=False)

ans = res.answer or ""
rec = {
    "question": Q,
    "clarify": bool(getattr(res, "clarify", False)),
    "executed": bool(getattr(res, "executed", False)),
    "error_kind": getattr(res, "error_kind", None),
    "answer_len": len(ans),
    "answer": ans[:1200],
    "mentions_token": "CLARIFY" in ans,
    "mentions_backtick_token": "`CLARIFY" in ans,
}

print("clarify =", rec["clarify"], " executed =", rec["executed"], " len =", rec["answer_len"])
print("正文含 CLARIFY:", rec["mentions_token"], " 含反引号包裹的标记:", rec["mentions_backtick_token"])
print("--- answer ---")
print(ans[:1200])

os.makedirs("outputs", exist_ok=True)
path = "outputs/probe_c014_1116.json"
with open(path, "w", encoding="utf-8") as f:
    json.dump(rec, f, ensure_ascii=False, indent=2)
print("saved", path)
