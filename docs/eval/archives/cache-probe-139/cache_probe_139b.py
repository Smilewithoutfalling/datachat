# -*- coding: utf-8 -*-
"""#139 ② 探针 b：加大提示让 prefill 占主导 + A 组连发排除逐出干扰。

首跑（3k token、A/B 交错）比值 0.88，未过缓存阈但离 1.0 有距离——3k prefill
在 ~800ms 总延迟里占比太小，信号被稀释。本跑 FILLER ×100（~8k token），
A 组 6 连发（无交错），若服务端前缀缓存在场，A[1:] 应显著快于 B。
"""
import io
import json
import statistics
import sys
import time

sys.path.insert(0, r"D:\Coding\claude\datachat")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace")

from dotenv import load_dotenv

load_dotenv(r"D:\Coding\claude\datachat\.env")

import httpx
from app.core import LLMConfig

cfg = LLMConfig.from_env()
print(f"model={cfg.model} base={cfg.base_url} key_len={len(cfg.api_key or '')}")

FILLER = (
    "数据分析规范条目：所有口径变更必须留痕；数字必须可溯源到代码执行的 result 对象；"
    "结论只允许引用执行结果中的值，禁止凭空构造；百分比要么用 0-1 小数要么乘以一百，"
    "同一次回答内不得混用两种刻度；时间序列对齐时优先按月份键；拒答题必须复述缺失字段。"
) * 100  # 约 8k token 量级


def one_call(client, system_text):
    t0 = time.perf_counter()
    r = client.post(
        cfg.base_url.rstrip("/") + "/chat/completions",
        json={
            "model": cfg.model,
            "messages": [
                {"role": "system", "content": system_text},
                {"role": "user", "content": "请只回复两个字：OK"},
            ],
            "max_tokens": 8,
            "temperature": 0.0,
            "stream": False,
        },
        timeout=180.0,
    )
    dt = (time.perf_counter() - t0) * 1000
    r.raise_for_status()
    usage = (r.json() or {}).get("usage") or {}
    return {
        "latency_ms": round(dt),
        "prompt_tokens": usage.get("prompt_tokens"),
        "prompt_tokens_details": usage.get("prompt_tokens_details"),
    }


calls = []
with httpx.Client(trust_env=False) as client:
    client.headers["Authorization"] = f"Bearer {cfg.api_key}"
    one_call(client, "PREFIX-warm\n" + FILLER)  # 预热不计
    for i in range(6):  # A 连发：同前缀背靠背
        a = one_call(client, "PREFIX-SAME\n" + FILLER)
        a["arm"] = "A_burst"
        calls.append(a)
        print(f"A{i}: {a['latency_ms']}ms prompt={a['prompt_tokens']} details={a['prompt_tokens_details']}", flush=True)
    for i in range(6):  # B：唯一前缀
        b = one_call(client, f"PREFIX-UNIQUE-nonce-{i}-{time.time_ns()}\n" + FILLER)
        b["arm"] = "B_unique"
        calls.append(b)
        print(f"B{i}: {b['latency_ms']}ms prompt={b['prompt_tokens']} details={b['prompt_tokens_details']}", flush=True)

a_all = [c["latency_ms"] for c in calls if c["arm"] == "A_burst"]
a_first = a_all[0]
a_rest = a_all[1:]
b_all = [c["latency_ms"] for c in calls if c["arm"] == "B_unique"]
med_a_rest = statistics.median(a_rest)
med_b = statistics.median(b_all)
ratio = med_a_rest / med_b if med_b else float("nan")

out = {
    "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    "model": cfg.model,
    "filler_chars": len(FILLER),
    "calls": calls,
    "a_first_ms": a_first,
    "a_rest_median_ms": med_a_rest,
    "b_median_ms": med_b,
    "ratio_a_rest_over_b": round(ratio, 3),
}
dest = r"D:\Coding\deepseekharness\审查\cache_probe_139b.json"
with open(dest, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

print(f"\nA首发={a_first}ms  A后5发中位={med_a_rest}ms  B中位={med_b}ms  比值={ratio:.2f}")
if ratio < 0.6:
    print("VERDICT_B: 缓存行为在场（重复大前缀明显加速；不记账只是上报口径变化）")
elif ratio < 0.85:
    print("VERDICT_B: 部分加速，证据不干净，按保守口径处理")
else:
    print("VERDICT_B: 大前缀下仍同速——缓存真关，预算按翻倍占位")
print("saved", dest)
