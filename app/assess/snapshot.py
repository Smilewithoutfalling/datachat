"""节点边界快照（阶段 7.5 第 1 步，docs/roadmap/phase75-assess.md §2 第 1 步）。

开关：`analyze(..., snapshot_dir=...)` 或环境变量 `DATACHAT_SNAPSHOT_DIR`（参数优先）。都没有时
service 里一个 SnapshotRecorder 都不建，所有快照分支都是 `if snapshot is not None`，现有行为与输出逐字节不变
（`tests/test_assess_snapshot.py::test_snapshot_off_is_byte_identical` 钉住）。

一次运行一个 JSONL 文件（`<UTC 时间>_<trace_id>.jsonl`），三类行：

- `kind=run`（第一行）：版本、trace_id、原问题与改写后的问题、数据集（原样 + 绝对路径 + 每张表的
  sha256 指纹）、列名、today、编码、记忆模式、重试与超时参数；评测批带 `case_id`（7.5b B2，
  `analyze(..., case_id=...)` 传入，产品调用不传就没有这个键）。
- `kind=node`（每个节点结束一行）：节点名、第几次出现、该节点的**输入 AgentState**（可序列化部分；
  df 不存，存的是数据集路径和指纹）、输出的 updates、耗时、token 增量（从本轮 UsageTracker 取差）、
  本节点的模型调用（prompt 的 sha256 与字符数、模型原始响应文本、是否截断），以及 today。
- `kind=end`（最后一行）：错误、本轮 usage、各节点耗时。

**today**：`analyze(today=...)` 给了就用它（today_source=param），否则取本地日期（today_source=local_date），
一律写进快照。回放只用快照里的 today，不读当天日期（`app/assess/replay.py`）。截至本步，图里的节点（第 3 步起七个）
都不读 today；读 today 的只有图之前的问题改写（M7，`service._maybe_rewrite`），它的结果
（改写后的问题）已经在 node 行的 input_state.question 里，改写记录在 run 行的 rewrite。
其他时间：会话历史里的时间戳在进图之前已经渲染进 memory_state / memory_history 两个字符串，随 state 一起存下；
run 行的 started_at_utc 只是记录，不注入任何 prompt。

快照写失败（磁盘满、权限）只记日志，绝不影响分析本身：评估层只观测。
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import hashlib
import json
import logging
import os

logger = logging.getLogger("datachat.assess.snapshot")

ENV = "DATACHAT_SNAPSHOT_DIR"
VERSION = 1
WIRE_KEY = "__wire__"
# 第 3 步 S3-3：replan 调模型（planner 的第二次），回放时按模型节点比 prompt；scope_gate 是确定性节点，按 executor 那样比 updates
LLM_NODES = ("planner", "codegen", "reviewer", "replan", "summarizer")
_ALWAYS_WIRE = {"result"}          # 结构化结果一律走 wire（JSON 会把 tuple 变 list、NaN 写成非法 JSON）
_TOKEN_FIELDS = ("calls", "input_tokens", "output_tokens", "total_tokens", "estimated_tokens")


def resolve_dir(param: str | None) -> str | None:
    if param:
        return os.fspath(param)
    return os.environ.get(ENV) or None


def sha256_text(text) -> str:
    if not isinstance(text, str):
        text = repr(text)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ state 编解码
def _plain(v) -> bool:
    try:
        s = json.dumps(v, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        return False
    try:
        return json.loads(s) == v and type(json.loads(s)) is type(v)
    except Exception:  # noqa: BLE001
        return False


def encode_value(key: str, v):
    from app.tools import wire
    if key in _ALWAYS_WIRE or not _plain(v):
        return {WIRE_KEY: wire.encode(v)}
    return v


def decode_value(v):
    if isinstance(v, dict) and set(v) == {WIRE_KEY}:
        from app.tools import wire
        return wire.decode(v[WIRE_KEY])
    return v


def encode_state(state: dict) -> dict:
    return {k: encode_value(k, v) for k, v in (state or {}).items()}


def decode_state(d: dict) -> dict:
    return {k: decode_value(v) for k, v in (d or {}).items()}


# ------------------------------------------------------------------ 数据集指纹
def _file_sha(path: str) -> tuple[str, int]:
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


def dataset_fingerprint(dataset) -> dict:
    """每张表文件的 sha256 + 字节数，另给一个合并指纹（按表名排序）。字典文件不算（它不进 df）。"""
    from app.tools.dataset import table_paths
    tables = table_paths(dataset)
    if tables is None:
        p = os.fspath(dataset)
        tables = [(os.path.splitext(os.path.basename(p))[0], p)]
    files = []
    for name, path in tables:
        sha, size = _file_sha(path)
        files.append({"table": name, "path": os.path.abspath(path), "sha256": sha, "bytes": size})
    combined = hashlib.sha256("\n".join(f"{f['table']}:{f['sha256']}" for f in files).encode()).hexdigest()
    return {"sha256": combined, "files": files}


def dataset_columns(df) -> dict:
    from app.tools.dataset import is_multi
    if is_multi(df):
        return {str(k): [str(c) for c in v.columns] for k, v in df.items()}
    return {"": [str(c) for c in df.columns]}


def _abs_dataset(dataset):
    if isinstance(dataset, (list, tuple)):
        return [os.path.abspath(os.fspath(p)) for p in dataset]
    return os.path.abspath(os.fspath(dataset))


# ------------------------------------------------------------------ 记录器
class SnapshotRecorder:
    """一次 analyze 一个。所有公开方法都吞掉自身异常（只记日志）：快照坏了，分析照常。"""

    def __init__(self, directory: str, trace_id: str, today=None):
        self.directory = directory
        self.trace_id = trace_id
        self.today = today or _dt.date.today()
        self.today_source = "param" if today else "local_date"
        stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.started_at_utc = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        self.path = os.path.join(directory, f"{stamp}_{trace_id}.jsonl")
        self._f = None
        self._broken = False
        self._calls: list = []
        self._prev_usage = None
        self._seq = 0
        self._occ: dict = {}
        self._dataset_fp = None
        self._begun = False

    # -------------------------------------------------------------- 内部
    def _write(self, rec: dict) -> None:
        if self._broken:
            return
        try:
            if self._f is None:
                os.makedirs(self.directory, exist_ok=True)
                self._f = open(self.path, "a", encoding="utf-8")
            self._f.write(json.dumps(rec, ensure_ascii=False, default=repr) + "\n")
            self._f.flush()
        except Exception as e:  # noqa: BLE001
            self._broken = True
            logger.warning("快照写入失败（不影响分析）trace=%s: %s", self.trace_id, e)

    def _usage_delta(self, tracker) -> dict:
        if tracker is None:
            return {}
        cur = dataclasses.asdict(tracker.snapshot())
        prev = self._prev_usage or {k: 0 for k in _TOKEN_FIELDS}
        self._prev_usage = cur
        delta = {k: (cur.get(k) or 0) - (prev.get(k) or 0) for k in _TOKEN_FIELDS}
        delta["reported"] = cur.get("reported")
        delta["estimated"] = cur.get("estimated")
        return delta

    # -------------------------------------------------------------- 公开
    def begin(self, *, original_question, question, dataset, encoding, df, agent, memory_mode, rewrite,
              max_attempts, exec_timeout, tracker=None, case_id=None) -> None:
        try:
            ds = dataset if isinstance(dataset, str) else [os.fspath(p) for p in dataset]
            fp = dataset_fingerprint(dataset)
            self._dataset_fp = fp["sha256"]
            if tracker is not None:
                self._prev_usage = dataclasses.asdict(tracker.snapshot())
            rec = {
                "kind": "run", "version": VERSION, "trace_id": self.trace_id,
                "started_at_utc": self.started_at_utc,
                "today": self.today.isoformat(), "today_source": self.today_source,
                "injected_timestamps": {"today": self.today.isoformat()},
                "agent": agent, "question": original_question, "rewritten_question": question,
                "rewrite": rewrite, "memory_mode": memory_mode,
                "dataset": ds, "dataset_abs": _abs_dataset(dataset), "encoding": encoding,
                "dataset_fingerprint": fp, "columns": dataset_columns(df),
                "multi": isinstance(df, dict),
                "max_attempts": max_attempts, "exec_timeout": exec_timeout,
            }
            if case_id is not None:      # 7.5b B2：评测批的题号。不传就不写这个键——
                rec["case_id"] = case_id  # 产品调用不传，快照字节与之前完全一致
            self._write(rec)
            self._begun = True
        except Exception as e:  # noqa: BLE001
            self._broken = True
            logger.warning("快照初始化失败（不影响分析）trace=%s: %s", self.trace_id, e)

    def attach(self, client) -> None:
        """包住 client.invoke_message（实例属性覆盖，只在开关打开时做）：记下每次成功调用的 prompt 哈希与原始响应。"""
        try:
            from app.core.llm import is_truncated, message_text
            orig = client.invoke_message
            calls = self._calls

            def invoke_message(prompt):
                msg = orig(prompt)
                try:
                    calls.append({"prompt_sha256": sha256_text(prompt),
                                  "prompt_chars": len(prompt) if isinstance(prompt, str) else None,
                                  "response": message_text(msg), "truncated": bool(is_truncated(msg))})
                except Exception:  # noqa: BLE001
                    pass
                return msg
            client.invoke_message = invoke_message
        except Exception as e:  # noqa: BLE001
            logger.warning("快照挂载模型记录失败（不影响分析）trace=%s: %s", self.trace_id, e)

    def node(self, name: str, input_state: dict, updates: dict, duration_s: float, tracker=None) -> None:
        if not self._begun:
            return
        try:
            self._seq += 1
            self._occ[name] = self._occ.get(name, 0) + 1
            calls, self._calls[:] = list(self._calls), []
            self._write({
                "kind": "node", "seq": self._seq, "node": name, "occurrence": self._occ[name],
                "today": self.today.isoformat(),
                "dataset": {"label": (input_state or {}).get("df_path"), "fingerprint": self._dataset_fp},
                "input_state": encode_state(input_state), "updates": encode_state(updates),
                "duration_s": round(duration_s, 4), "tokens": self._usage_delta(tracker),
                "llm_calls": calls,
            })
        except Exception as e:  # noqa: BLE001
            logger.warning("快照节点记录失败（不影响分析）trace=%s node=%s: %s", self.trace_id, name, e)

    def end(self, res) -> None:
        """没写过 run 行（读数据失败、没有 Key 这类在进图之前就结束的运行）时不落文件。"""
        try:
            if not self._begun:
                return
            pending, self._calls[:] = list(self._calls), []
            usage = res.usage
            self._write({
                "kind": "end", "error": res.error, "error_kind": res.error_kind,
                "usage": dataclasses.asdict(usage) if dataclasses.is_dataclass(usage) else usage,
                "timings": dict(res.timings), "pending_llm_calls": pending,
                "ended_at_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            })
        except Exception as e:  # noqa: BLE001
            logger.warning("快照收尾失败（不影响分析）trace=%s: %s", self.trace_id, e)
        finally:
            try:
                if self._f is not None:
                    self._f.close()
            except Exception:  # noqa: BLE001
                pass


def start(directory: str | None, trace_id: str, today=None) -> SnapshotRecorder | None:
    d = resolve_dir(directory)
    return SnapshotRecorder(d, trace_id, today) if d else None


# ------------------------------------------------------------------ 读取
@dataclasses.dataclass
class Snapshot:
    path: str
    run: dict
    nodes: list
    end: dict | None

    def find(self, node: str, occurrence: int = 1) -> dict:
        for r in self.nodes:
            if r["node"] == node and r["occurrence"] == occurrence:
                return r
        raise KeyError(f"快照里没有第 {occurrence} 次 {node}（{self.path}）")


def load(path: str) -> Snapshot:
    run, nodes, end = None, [], None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            k = rec.get("kind")
            if k == "run":
                run = rec
            elif k == "node":
                nodes.append(rec)
            elif k == "end":
                end = rec
    if run is None:
        raise ValueError(f"不是快照文件（缺 run 行）：{path}")
    return Snapshot(path, run, nodes, end)


def list_snapshots(directory: str) -> list[str]:
    return sorted(os.path.join(directory, f) for f in os.listdir(directory) if f.endswith(".jsonl"))

