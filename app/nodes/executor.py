"""执行节点。B07：result 保留结构化对象，另生成 result_text 预览；
数据表由 analyze() 读一次后经 RunnableConfig 注入，每次执行用副本（不再每次重试都读 CSV）。"""
from app.core.result import format_result
from app.tools.csv_io import read_csv
from app.tools.persist import new_chart_path
from app.tools.sandbox import run_code


def _dataset(state, config):
    conf = (config or {}).get("configurable", {}) if isinstance(config, dict) else {}
    df = conf.get("df")
    return df.copy() if df is not None else read_csv(state["df_path"])


def execute(state, config=None):
    chart_path = new_chart_path()
    df = _dataset(state, config)
    result, chart, error = run_code(
        state["code"], df, chart_path, timeout=state.get("exec_timeout", 20)
    )

    update = {
        "result": None if error else result,
        "result_text": "" if error else format_result(result),
        "chart_path": chart or "",
        "error": error or "",
    }
    # 只记第一次执行的报错，用来区分"一次写对"与"reviewer 修好"
    if error and not state.get("initial_error") and state.get("attempts", 0) == 0:
        update["initial_error"] = error
    return update
