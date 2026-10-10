"""评测报告生成。

B11 口径修正：
- 正确率 = 判对题数 / 全部题数（旧版分母只算执行成功的题，数字虚高）。
  "执行成功中的正确率"仍保留，但明确标为条件正确率，不作为主指标。
- 修复率：没有任何题初始报错时为 None（报告显示 N/A），不再记作 100%。
- 分类统计：某类没有题时按空集计算（旧版 `items or self.results` 会退回到全部题）。
- 新增：基础设施失败数（LLM 超时/限流/缺 Key）、平均耗时、平均 token。
"""
import hashlib
import json
import os
import platform
import subprocess
from datetime import datetime

from app.eval.cases import CATEGORY_MAP


_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _git(*args):
    return subprocess.run(["git", "-C", _REPO, *args], capture_output=True, text=True, timeout=5)


def _sha_from_files(short: bool):
    """不依赖 git 命令：直接读 .git/HEAD 与 refs（Windows 上 conda 环境常常找不到 git，B27）。"""
    git_dir = os.path.join(_REPO, ".git")
    head = open(os.path.join(git_dir, "HEAD"), encoding="utf-8").read().strip()
    sha = head
    if head.startswith("ref:"):
        ref = head.split(" ", 1)[1].strip()
        path = os.path.join(git_dir, *ref.split("/"))
        if os.path.exists(path):
            sha = open(path, encoding="utf-8").read().strip()
        else:
            sha = ""
            packed = os.path.join(git_dir, "packed-refs")
            if os.path.exists(packed):
                for line in open(packed, encoding="utf-8"):
                    parts = line.strip().split(" ")
                    if len(parts) == 2 and parts[1] == ref:
                        sha = parts[0]
    if not sha:
        return None
    return (sha[:7] if short else sha) + "?"      # "?"：没能检查工作区是否有未提交改动


def git_sha(short: bool = True) -> str:
    """当前 commit；工作区有改动时加 -dirty。git 不可用时退回读 .git 文件，并在末尾加 "?"。"""
    try:
        r = _git("rev-parse", *(["--short"] if short else []), "HEAD")
        sha = r.stdout.strip()
        if sha:
            dirty = _git("status", "--porcelain", "--untracked-files=no").stdout.strip()
            return sha + ("-dirty" if dirty else "")
    except Exception:
        pass
    try:
        return _sha_from_files(short) or "unknown"
    except Exception:
        return "unknown"


def run_metadata(llm_config=None, data_path: str | None = None) -> dict:
    """报告里记下复现所需的环境：模型、温度、接口、依赖版本、数据文件指纹（B27）。"""
    meta = {"python": platform.python_version()}
    try:
        import pandas
        meta["pandas"] = pandas.__version__
    except Exception:
        pass
    if llm_config is not None:
        meta["model"] = getattr(llm_config, "model", None)
        meta["temperature"] = getattr(llm_config, "temperature", None)
        base = getattr(llm_config, "base_url", None) or ""
        meta["base_url_host"] = base.split("//")[-1].split("/")[0] or None
    if data_path and os.path.exists(data_path):
        meta["data_sha256"] = hashlib.sha256(open(data_path, "rb").read()).hexdigest()[:12]
    return meta


def datasets_metadata(datasets: dict) -> dict:
    """阶段 3：每张数据表的指纹，以及旁边有没有数据字典（B38：sample_eval 以前没有字典，"有/无字典"两组其实一样）。"""
    from app.tools.dictionary import dict_path_for
    out = {}
    for name, path in datasets.items():
        if not os.path.exists(path):
            continue
        d = dict_path_for(path)
        out[name] = {"path": os.path.relpath(path, _REPO).replace(os.sep, "/"),
                     "sha256": hashlib.sha256(open(path, "rb").read()).hexdigest()[:12],
                     "dictionary_file": os.path.exists(d)}   # 文件是否存在；本次是否使用看顶层 use_dictionary
    return out


# ---------------------------------------------------------------- 结果对象的可还原存储
def _enc(x):
    import math

    import numpy as np
    import pandas as pd
    if isinstance(x, np.generic):
        x = x.item()
    if isinstance(x, tuple):
        return {"t": [_enc(i) for i in x]}
    if isinstance(x, (pd.Timestamp, pd.Period)):
        return str(x.date()) if isinstance(x, pd.Timestamp) and x == x.normalize() else str(x)
    if x is None or x is pd.NaT or x is pd.NA or (isinstance(x, float) and math.isnan(x)):
        return None
    if isinstance(x, (str, int, float, bool)):
        return x
    return str(x)


def _dec(x):
    if isinstance(x, dict) and "t" in x:
        return tuple(_dec(i) for i in x["t"])
    return float("nan") if x is None else x


def _index(labels, names):
    import pandas as pd
    labels = [_dec(v) for v in labels]
    if labels and all(isinstance(v, tuple) for v in labels):
        return pd.MultiIndex.from_tuples(labels, names=names)
    return pd.Index(labels, name=names[0] if names else None)


def dump_obj(v):
    """把结果对象存成可还原的 JSON（用于 --rescore 离线重新打分）。时间值存成字符串，
    还原后不再是 Timestamp/Period，比较器对月份标签有归一规则，个别题可能与在线打分不同。"""
    import numpy as np
    import pandas as pd
    try:
        if isinstance(v, pd.DataFrame):
            return {"kind": "frame", "index": [_enc(i) for i in v.index], "index_names": list(v.index.names),
                    "columns": [_enc(c) for c in v.columns], "column_names": list(v.columns.names),
                    "values": [[_enc(x) for x in row] for row in v.itertuples(index=False, name=None)]}
        if isinstance(v, pd.Series):
            return {"kind": "series", "index": [_enc(i) for i in v.index], "index_names": list(v.index.names),
                    "name": _enc(v.name), "values": [_enc(x) for x in v.values]}
        if isinstance(v, np.generic):
            v = v.item()
        if isinstance(v, tuple):
            return {"kind": "tuple", "data": [dump_obj(x) for x in v]}
        if isinstance(v, list):
            return {"kind": "list", "data": [dump_obj(x) for x in v]}
        if isinstance(v, dict):
            return {"kind": "dict", "data": [[_enc(k), dump_obj(x)] for k, x in v.items()]}
        return {"kind": "value", "data": _enc(v)}
    except Exception:
        return {"kind": "repr", "data": str(v)[:2000]}


def load_obj(d):
    import pandas as pd
    if d is None:
        return None
    k = d.get("kind")
    if k == "frame":
        cols = _index(d["columns"], d.get("column_names") or [None])
        return pd.DataFrame([[_dec(x) for x in row] for row in d["values"]],
                            index=_index(d["index"], d.get("index_names") or [None]), columns=cols)
    if k == "series":
        return pd.Series([_dec(x) for x in d["values"]], index=_index(d["index"], d.get("index_names") or [None]),
                         name=_dec(d.get("name")) if d.get("name") is not None else None)
    if k == "tuple":
        return tuple(load_obj(x) for x in d["data"])
    if k == "list":
        return [load_obj(x) for x in d["data"]]
    if k == "dict":
        return {_dec(key): load_obj(x) for key, x in d["data"]}
    return _dec(d.get("data")) if k == "value" else d.get("data")


class EvalReport:
    def __init__(self, results: list, meta: dict | None = None):
        """results: list[dict] from EvalRunner.run_all()；meta: run_metadata() 的结果"""
        self.results = results
        self.meta = meta or {}
        self.total = len(results)
        self.by_category = {}
        self.by_dataset = {}
        for r in results:
            cat = r["case"].category
            self.by_category.setdefault(cat, []).append(r)
            self.by_dataset.setdefault(getattr(r["case"], "dataset", "sales"), []).append(r)

    def _items(self, items):
        return self.results if items is None else items

    def _rate(self, items: list, key: str):
        total = len(items)
        if total == 0:
            return None
        return sum(1 for r in items if r.get(key)) / total * 100

    def execution_success_rate(self, items=None):
        return self._rate(self._items(items), "executed")

    def correctness_rate(self, items=None):
        """主指标：分母是全部题。"""
        return self._rate(self._items(items), "correct")

    def conditional_correctness_rate(self, items=None):
        """条件正确率：只在执行成功的题里算（仅供诊断）。"""
        executed = [r for r in self._items(items) if r.get("executed")]
        return self._rate(executed, "correct")

    def reviewer_fix_rate(self, items=None):
        """初始报错的题中，最终执行成功的比例；没有初始报错时无定义（None）。"""
        errored = [r for r in self._items(items) if r.get("initial_error")]
        return self._rate(errored, "executed")

    def infra_error_count(self, items=None):
        return sum(1 for r in self._items(items) if r.get("infra_error"))

    def avg(self, key, items=None):
        vals = [r[key] for r in self._items(items) if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    def summary(self) -> dict:
        def block(items):
            return {
                "n": len(items),
                "correct": sum(1 for r in items if r.get("correct")),
                "executed": sum(1 for r in items if r.get("executed")),
                "correctness_rate": self.correctness_rate(items),
                "execution_success_rate": self.execution_success_rate(items),
                "conditional_correctness_rate": self.conditional_correctness_rate(items),
                "reviewer_fix_rate": self.reviewer_fix_rate(items),
                "initial_errors": sum(1 for r in items if r.get("initial_error")),
                "infra_errors": self.infra_error_count(items),
                "avg_duration_s": self.avg("duration_s", items),
                "avg_tokens": self.avg("tokens", items),
            }
        agents = sorted({r.get("agent", "workflow") for r in self.results})
        return {
            "time": datetime.now().isoformat(timespec="seconds"),
            "git_sha": git_sha(),
            "agent": agents[0] if len(agents) == 1 else agents,
            **self.meta,
            "overall": block(self.results),
            "by_category": {k: block(v) for k, v in self.by_category.items()},
            "by_dataset": {k: block(v) for k, v in self.by_dataset.items()},
        }

    def to_json(self, path: str, extra: dict | None = None) -> None:
        """写出带 SHA 的报告：汇总 + 每题明细（结果对象只存文本预览）。"""
        rows = []
        for r in self.results:
            c = r["case"]
            rows.append({
                "id": c.id, "category": c.category, "dataset": getattr(c, "dataset", "sales"),
                "question": c.question,
                "correct": r.get("correct"), "executed": r.get("executed"),
                "initial_error": r.get("initial_error"), "infra_error": r.get("infra_error"),
                "error_kind": r.get("error_kind"), "error": r.get("error"),
                "attempts": r.get("attempts"), "duration_s": r.get("duration_s"),
                "tokens": r.get("tokens"), "code": r.get("code"),
                "expected": str(r.get("expected"))[:500], "actual": str(r.get("actual"))[:500],
                "answer": (r.get("answer") or "")[:2000],
                # 可还原的结构化结果：比较器改了之后可以用 run_eval.py --rescore 离线重新打分（B26）
                "expected_obj": dump_obj(r.get("expected")),
                "actual_obj": dump_obj(r.get("actual")) if r.get("executed") else None,
            })
        data = {**self.summary(), **(extra or {}), "cases": rows}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    @staticmethod
    def _pct(v):
        return "N/A" if v is None else f"{v:.1f}%"

    def print_summary(self):
        s = self.summary()
        o = s["overall"]
        print("=" * 60)
        print("  DataChat 评测报告")
        print(f"  时间: {s['time']}    commit: {s['git_sha']}    agent: {s['agent']}")
        if s.get("model"):
            print(f"  模型: {s['model']}    temperature: {s.get('temperature')}    数据指纹: {s.get('data_sha256')}")
        print(f"  总用例: {self.total}")
        print("=" * 60)

        print("\n  📊 全局指标")
        print(f"  输出正确率（分母=全部题）: {self._pct(o['correctness_rate'])}  ({o['correct']}/{o['n']})")
        print(f"  代码执行成功率:           {self._pct(o['execution_success_rate'])}  ({o['executed']}/{o['n']})")
        print(f"  条件正确率（仅执行成功）: {self._pct(o['conditional_correctness_rate'])}  "
              f"({o['correct']}/{o['executed']})")
        print(f"  Reviewer 修复率:          {self._pct(o['reviewer_fix_rate'])}  "
              f"(初始报错 {o['initial_errors']} 条)")
        print(f"  基础设施失败（LLM 超时/限流/缺 Key 等）: {o['infra_errors']} 条")
        if o["avg_duration_s"] is not None:
            print(f"  平均耗时: {o['avg_duration_s']:.2f} 秒/题")
        tok = o["avg_tokens"]
        print(f"  平均 token: {'N/A' if tok is None else format(tok, '.0f')}")

        print("\n  📂 分类指标")
        print(f"  {'分类':<10} {'用例数':<6} {'正确率':<9} {'执行成功率':<11} {'修复率':<8}")
        print(f"  {'-' * 52}")
        for cat_key in CATEGORY_MAP:
            b = s["by_category"].get(cat_key)
            if not b:
                continue
            cat_name = CATEGORY_MAP.get(cat_key, cat_key)
            print(f"  {cat_name:<10} {b['n']:<6} {self._pct(b['correctness_rate']):<9} "
                  f"{self._pct(b['execution_success_rate']):<11} {self._pct(b['reviewer_fix_rate']):<8}")
        if len(s["by_dataset"]) > 1:
            print("\n  🗂  分表指标")
            for name, b in s["by_dataset"].items():
                print(f"  {name:<10} {b['n']:<6} {self._pct(b['correctness_rate']):<9} "
                      f"{self._pct(b['execution_success_rate']):<11} {self._pct(b['reviewer_fix_rate']):<8}")
        print()

    def print_details(self, verbose=False):
        """打印每条用例的结果。verbose=True 时打印 code 和 result。"""
        for i, r in enumerate(self.results, 1):
            case = r["case"]
            status = "✅" if r.get("correct") else ("⚠️" if r.get("executed") else "❌")
            icon = "📊" if case.has_chart else "  "
            print(f"  {i:2d}. {status} {icon} [{case.id}] {case.question[:50]}")
            if r.get("initial_error"):
                print(f"      🔧 初始报错，修复后 {'成功' if r['executed'] else '仍失败'}"
                      f"（重试{r['attempts']}次）")
            if not r.get("executed") and r.get("error"):
                err_preview = r["error"].replace("\n", " ")[:120]
                print(f"      ❌ 错误[{r.get('error_kind')}]: {err_preview}")
            if r.get("executed") and not r.get("correct") and verbose:
                print(f"      📝 期望: {str(r.get('expected'))[:80]}")
                print(f"      🔧 实际: {str(r.get('actual'))[:80]}")
            if verbose and r.get("code"):
                print(f"      💻 code: {r['code'][:150]}")
        print()
