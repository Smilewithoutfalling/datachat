# -*- coding: utf-8 -*-
"""#139 ② 前缀缓存行为学探针。

问题：#119 实锚显示网关 11-23 起不报 cache 字段——cache 是真关了，还是只是记账没了？
方法：A/B 交错对照。
  A 组：同一大提示（~4k token）连打 6 次——若服务端前缀缓存（vLLM/SGLang 常默认开）
        还在，第 2 发起应显著快于第 1 发（TTFT 受 prefill 支配）。
  B 组：每发在提示最前面塞唯一 nonce（前缀立刻分叉，缓存必 miss），同尺寸 6 次，
        作为「全量 prefill」的基线。
判读：median(A 后 5 发) < 0.6 * median(B) → 缓存行为在场（只是不记账）；
      A ≈ B → 缓存真关。交错执行控网关负载波动。
"""
import io
import json
import statistics
import sys
import time

sys.path.insert(0, r"D:\Coding\claude\datachat")  # 只读 LLMConfig，不改仓库
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
) * 40  # 约 4k token 量级


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
        timeout=120.0,
    )
    dt = (time.perf_counter() - t0) * 1000
    r.raise_for_status()
    data = r.json()
    usage = data.get("usage") or {}
    return {
        "latency_ms": round(dt),
        "prompt_tokens": usage.get("prompt_tokens"),
        "prompt_tokens_details": usage.get("prompt_tokens_details"),
        "completion_tokens": usage.get("completion_tokens"),
        "system_fingerprint": data.get("system_fingerprint"),
        "finish": (data.get("choices") or [{}])[0].get("finish_reason"),
    }


calls = []
with httpx.Client(trust_env=False) as client:  # 内网网关：绝不走系统代理
    client.headers["Authorization"] = f"Bearer {cfg.api_key}"
    # 预热 1 发（建连接/TLS），不计入
    one_call(client, "PREFIX-warm\n" + FILLER)
    for i in range(6):
        a = one_call(client, "PREFIX-SAME\n" + FILLER)
        a["arm"] = "A_same"
        a["i"] = i
        calls.append(a)
        print(f"A{i}: {a['latency_ms']}ms prompt={a['prompt_tokens']} details={a['prompt_tokens_details']}", flush=True)
        b = one_call(client, f"PREFIX-UNIQUE-nonce-{i}-{time.time_ns()}\n" + FILLER)
        b["arm"] = "B_unique"
        b["i"] = i
        calls.append(b)
        print(f"B{i}: {b['latency_ms']}ms prompt={b['prompt_tokens']} details={b['prompt_tokens_details']}", flush=True)

a_all = [c["latency_ms"] for c in calls if c["arm"] == "A_same"]
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
dest = r"D:\Coding\deepseekharness\审查\cache_probe_139.json"
with open(dest, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

print(f"\nA首发={a_first}ms  A后5发中位={med_a_rest}ms  B中位={med_b}ms  比值={ratio:.2f}")
if ratio < 0.6:
    print("VERDICT: 缓存行为在场（重复前缀明显加速；记账字段缺失只是上报口径变化）")
elif ratio < 0.85:
    print("VERDICT: 部分加速，证据不干净，按保守口径处理")
else:
    print("VERDICT: 两组同速——缓存大概率真关，预算按翻倍占位")
print("saved", dest)
