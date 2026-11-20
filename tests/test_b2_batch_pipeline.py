"""7.5b B2（phase75b-eval-assess.md §B2 验收 ①②③）：case_id 贯通 + record/replay/assess 三件套。

- case_id 只进快照 run 行、不进 prompt：给了 → run 行有键、契约报告的题键用 case_id；
  没给 → run 行没有这个键、题键回退 文件名::问题（产品路径快照字节与 B2 之前完全一致）。
- record_batch → replay_batch --recorded → assess：CI 三步的进程内版，单表用例走
  plan→codegen→answer 全链。
- 回放哨兵不能只会绿灯：改坏一条已录 prompt 哈希，--recorded 必须报不一致、退出 1。
"""
import importlib.util
import json
import os

from app.assess.runner import assess_dir
from app.assess.snapshot import list_snapshots, load
from app.core.service import analyze
from tests.test_assess_cli import _model

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cli(name: str):
    spec = importlib.util.spec_from_file_location(name[:-3], os.path.join(ROOT, "scripts", "assess", name))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- ① case_id 贯通
def test_case_id_lands_in_run_row_and_becomes_report_key(sample_path, tmp_path):
    analyze(sample_path, "总销量", chat_model=_model("result = int(df['units'].sum())", "见结果"),
            snapshot_dir=str(tmp_path), case_id="agg_013")
    snap = load(list_snapshots(str(tmp_path))[0])
    assert snap.run["case_id"] == "agg_013"
    assert {r["key"] for r in assess_dir(str(tmp_path))["runs"]} == {"agg_013"}


def test_without_case_id_key_absent_and_fallback_key(sample_path, tmp_path):
    analyze(sample_path, "总销量", chat_model=_model("result = int(df['units'].sum())", "见结果"),
            snapshot_dir=str(tmp_path))
    snap = load(list_snapshots(str(tmp_path))[0])
    assert "case_id" not in snap.run                       # 不传不写键：产品路径字节不变
    assert {r["key"] for r in assess_dir(str(tmp_path))["runs"]} == {"sample.csv::总销量"}


# ---------------------------------------------------------------- ②③ 跑批 → 回放 → 报告
def test_record_replay_assess_end_to_end(tmp_path):
    d = str(tmp_path / "snap")
    assert _cli("record_batch.py").main([d, "--ids", "agg_013"]) == 0
    files = list_snapshots(d)
    assert len(files) == 1 and load(files[0]).run["case_id"] == "agg_013"
    # 回放是确定性的（fake_llm 场景固定 + --recorded 拿录下的响应），两次跑结果一致
    assert _cli("replay_batch.py").main([d, "--recorded"]) == 0
    rep = assess_dir(d)
    assert rep["summary"]["runs"] == 1 and rep["runs"][0]["key"] == "agg_013"
    assert rep["runs"][0]["verdicts"]                                    # 契约报告有内容，不是空壳


def test_replay_batch_fails_on_tampered_prompt_hash(tmp_path):
    """改坏一处已录的 prompt 哈希 → --recorded 报不一致、退出 1。哨兵必须抓得住漂移。"""
    d = str(tmp_path / "snap")
    assert _cli("record_batch.py").main([d, "--ids", "agg_013"]) == 0
    path = list_snapshots(d)[0]
    rows, tampered = [], False
    with open(path, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if not tampered and rec.get("kind") == "node" and rec.get("llm_calls"):
                rec["llm_calls"][0]["prompt_sha256"] = "0" * 64
                tampered = True
            rows.append(json.dumps(rec, ensure_ascii=False))
    assert tampered
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
    assert _cli("replay_batch.py").main([d, "--recorded"]) == 1
