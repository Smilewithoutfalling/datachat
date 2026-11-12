"""EV-B8：LLM judge —— 给"没有唯一答案"的题一个可校准的二元判定。

契约（docs/roadmap/eval-system-spec.md EV-B8 / phase7 §E4）：
- 只判二元（pass / 不 pass），不打分——0-100 分不可校准；
- confidence=low 或 abstain=True 的样本不计入一致率分母，校准时单列；
- 调用失败抛 JudgeError，绝不返回 pass=False——否则把基础设施故障算成模型错；
- rubric 只能来自题面与 gold，**不许把被评答案喂回去让它"解释"**；
- 防偏差：gold 与 answer 的呈现顺序由 order 参数控制，校准脚本固定一半一半（固定 seed），
  消位置偏见；prompt 明写"长度、文风不作为评分依据"。

judge 模型必须与被评模型**不同家族**（同族偏向自己的答案，审计报告 P1），
通过 DATACHAT_JUDGE_MODEL / DATACHAT_JUDGE_API_KEY / DATACHAT_JUDGE_BASE_URL 配置；
没配 judge 变量时回退 DEEPSEEK_*（本地网关一把 key 多家族，行为等价）。
上线条件：在闸门 25 题人工标注上 judge 与人工一致率 ≥90% 且 κ ≥ 0.7（预登记），
没到就只记录不判定（scripts/eval/judge_calibrate.py 的退出码就是这个判据）。

judge 不进 CI 门禁（要 Key、有成本、有随机性）——它只服务离线校准与报告复核。
"""
from __future__ import annotations

import json
import os
import random
import re

_JUDGE_SYSTEM = (
    "你是数据分析评测的裁判。给你一道题、判定标准、一份标准答案和一个被评回答，"
    "你只做一件事：判断被评回答的**最终结论**是否与标准答案一致。\n"
    "规则：\n"
    "- 只看结论里的数值、标签、名单是否与标准答案一致；表述方式、详细程度、长度、文风一律不作依据。\n"
    "- 被评回答里多出来的解释性内容不算错；但结论与标准答案矛盾就是错。\n"
    "- 标准答案或判定标准里声明了口径（如\"净数量\"\"排除退货\"）时，被评回答必须遵守同一口径。\n"
    "- 无法判定（标准答案信息不足、被评回答没给结论）时 abstain=true。\n"
    "- 你不确定时 confidence 填 low；很有把握填 high。\n"
    "只输出一个 JSON 对象，不要输出其他文字：\n"
    '{"pass": true|false, "reason": "<一句话>", "confidence": "high"|"low", "abstain": true|false}'
)

_JUDGE_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class JudgeError(RuntimeError):
    """judge 调用失败（网络、超时、输出不是合法 JSON 且重试后仍失败）。

    校准脚本捕获后计为失败样本，不参与一致率——与"调用失败不算模型错"同一精神。
    """


def judge_model():
    """从环境构建 judge 用的 ChatModel。缺 DATACHAT_JUDGE_* 时回退 DEEPSEEK_*。

    temperature 固定 0.0：judge 要可复现，随机性会毁掉 κ 校准。
    """
    from app.core.llm import LLMConfig, build_chat_model

    cfg = LLMConfig(
        model=os.getenv("DATACHAT_JUDGE_MODEL") or os.getenv("DEEPSEEK_MODEL") or "deepseek-chat",
        api_key=os.getenv("DATACHAT_JUDGE_API_KEY") or os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DATACHAT_JUDGE_BASE_URL") or os.getenv("DEEPSEEK_BASE_URL") or None,
        temperature=0.0,
    )
    return build_chat_model(cfg, sdk_retries=0)


def _parse(text: str) -> dict:
    m = _JUDGE_JSON_RE.search(text or "")
    if not m:
        raise JudgeError(f"judge 输出里没有 JSON：{(text or '')[:200]!r}")
    try:
        d = json.loads(m.group(0))
    except ValueError as e:
        raise JudgeError(f"judge 输出 JSON 解析失败：{e}；原文 {(text or '')[:200]!r}") from e
    if not isinstance(d, dict) or "pass" not in d:
        raise JudgeError(f"judge JSON 缺 pass 字段：{m.group(0)[:200]!r}")
    return d


def judge(question, answer, gold_summary, rubric, *, model=None, temperature=None,
          order=None, seed=None) -> dict:
    """判一次。返回 {"pass": bool, "reason": str, "confidence": "high"|"low", "abstain": bool}。

    order：None=随机（random.Random(seed) 决定）、"gold_first"（标准答案在前）、
    "answer_first"（被评回答在前）。校准脚本按记录里的 order 字段传，
    保证 40 条样本里两种顺序各半——消位置偏见。
    temperature 参数保留但不再使用（模型在 judge_model 里已固定 0.0）；传了非 None 且非 0 会报错，
    防止调用方悄悄引入随机性。
    """
    if temperature not in (None, 0.0):
        raise ValueError("judge 的 temperature 必须是 0（可复现），别传别的")
    if order not in (None, "gold_first", "answer_first"):
        raise ValueError(f"order 只接受 None/'gold_first'/'answer_first'，收到 {order!r}")
    if order is None:
        order = random.Random(seed).choice(("gold_first", "answer_first"))

    blocks = {
        "gold_first": (
            f"【标准答案】\n{gold_summary}\n\n【被评回答】\n{answer}\n",
            f"【被评回答】\n{answer}\n\n【标准答案】\n{gold_summary}\n",
        ),
        "answer_first": (
            f"【被评回答】\n{answer}\n\n【标准答案】\n{gold_summary}\n",
            f"【标准答案】\n{gold_summary}\n\n【被评回答】\n{answer}\n",
        ),
    }
    body = blocks[order][0]

    prompt = (
        f"【题目】\n{question}\n\n"
        f"【判定标准】\n{rubric}\n\n"
        f"{body}"
        "请按系统规则输出 JSON。"
    )

    m = model if model is not None else judge_model()
    # 调用失败重试一次：网关偶发抖动不该把样本判废；两次都挂才算失败。
    last_err = None
    for attempt in range(2):
        try:
            resp = m.invoke([("system", _JUDGE_SYSTEM), ("human", prompt)])
            text = resp.content if isinstance(resp.content, str) else str(resp.content)
            d = _parse(text)
            break
        except JudgeError as e:
            if attempt == 0:
                continue
            raise JudgeError(f"judge 重试后仍失败：{e}") from e
        except Exception as e:  # 网络/超时/限流等基础设施故障
            last_err = e
            if attempt == 0:
                continue
            raise JudgeError(f"judge 调用失败（重试后）：{last_err!r}") from e
    else:  # pragma: no cover - for/else 只有 break 缺失才走到
        raise JudgeError(f"judge 调用失败：{last_err!r}")

    abstain = bool(d.get("abstain"))
    conf = d.get("confidence") or "low"
    if conf not in ("high", "low"):
        conf = "low"
    return {"pass": bool(d.get("pass")) and not abstain,
            "reason": str(d.get("reason") or ""),
            "confidence": conf,
            "abstain": abstain,
            "order": order}
