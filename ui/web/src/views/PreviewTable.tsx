import type { PreviewTable as T } from "../types";

// 单元格一律按文本渲染（THREAT_MODEL T9）；缺失值显示成灰色的"空"，和字符串 "null" 区分开
export function PreviewTable({ table }: { table: T }) {
  if (table.error !== undefined) {
    return (
      <p className="warn" role="alert">
        {table.filename} 读取失败：{table.error}
      </p>
    );
  }
  return (
    <div className="preview">
      <p className="muted">
        {table.filename}：共 {table.total_rows} 行 × {table.total_columns} 列，编码 {table.encoding}
        {table.rows.length < table.total_rows ? `，显示前 ${table.rows.length} 行` : ""}
        {table.truncated_cells > 0 ? `；${table.truncated_cells} 个单元格超 200 字，已截断（末尾带 …）` : ""}
        {table.bidi_stripped > 0 ? `；${table.bidi_stripped} 处方向控制符已从预览中去掉（不影响分析）` : ""}
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th className="rownum">#</th>
              {table.columns.map((c, i) => (
                <th key={i} title={table.dtypes[i]}>
                  {c}
                  <span className="dtype">{table.dtypes[i]}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((r, i) => (
              <tr key={i}>
                <td className="rownum">{i + 1}</td>
                {r.map((v, j) => (
                  <td key={j}>{v === null ? <span className="na">空</span> : v}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
