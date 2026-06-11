from app.tools.csv_io import read_csv


def describe_csv(path: str, n: int = 3) -> str:
    """读取 CSV，生成一段供模型理解的表结构描述（列名 + 类型 + 样例行）。"""
    df = read_csv(path)
    lines = [f"表共有 {len(df)} 行、{len(df.columns)} 列。", "列信息："]
    for c in df.columns:
        lines.append(f"- {c}（{df[c].dtype}）")
    lines.append(f"\n前 {n} 行示例：")
    lines.append(df.head(n).to_string(index=False))
    return "\n".join(lines)
