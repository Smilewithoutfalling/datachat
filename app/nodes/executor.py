from app.tools.csv_io import read_csv
from app.tools.persist import new_chart_path
from app.tools.sandbox import run_code


def execute(state):
    chart_path = new_chart_path()
    df = read_csv(state["df_path"])
    result, chart, error = run_code(state["code"], df, chart_path)

    return {
        "result": "" if result is None else str(result)[:3000],
        "chart_path": chart or "",
        "error": error or "",
    }
