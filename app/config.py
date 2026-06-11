"""路径锚定到项目根目录，避免因运行时 cwd 不同导致结果保存到错误位置。

之前 outputs 用相对路径，从不同目录启动时图表会落在别处或找不到。
这里以本文件位置推出项目根，所有产物目录都基于它。
"""
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OUTPUT_DIR = os.path.join(PROJECT_ROOT, "outputs")
CHART_DIR = os.path.join(OUTPUT_DIR, "charts")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
RUNS_LOG = os.path.join(OUTPUT_DIR, "runs.jsonl")


def ensure_dirs():
    os.makedirs(CHART_DIR, exist_ok=True)
