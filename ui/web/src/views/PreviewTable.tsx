import { useEffect, useMemo, useRef, useState } from "react";
import type { PreviewTable as T } from "../types";
import { IconMore } from "./icons";

// 单元格一律按文本渲染（THREAT_MODEL T9）；缺失值显示成灰色的"空"，和字符串 "null" 区分开
// 原型（proto/genie-shell）：斑马纹、列类型标识、列菜单（排序、按值筛选）。排序和筛选只作用于预览里已加载的行，不改数据集。

type Cell = string | null;
type Sort = { col: number; dir: "asc" | "desc" } | null;

const kindOf = (dtype: string): "num" | "date" | "bool" | "text" =>
  /int|float|decimal|number/i.test(dtype) ? "num" : /date|time/i.test(dtype) ? "date" : /bool/i.test(dtype) ? "bool" : "text";

function TypeMark({ dtype }: { dtype: string }) {
  const k = kindOf(dtype);
  const txt = k === "num" ? "123" : k === "date" ? "日期" : k === "bool" ? "是否" : "Abc";
  return <span className={`col-type col-type-${k}`} title={dtype} aria-label={`类型 ${dtype}`}>{txt}</span>;
}

const NA = "\u0000空";
const keyOf = (v: Cell) => (v === null ? NA : v);
const labelOf = (k: string) => (k === NA ? "（空）" : k === "" ? "（空字符串）" : k);

function compare(a: Cell, b: Cell, num: boolean): number {
  if (a === null) return b === null ? 0 : 1; // 空值永远排最后
  if (b === null) return -1;
  if (num) {
    const x = Number(a), y = Number(b);
    if (Number.isFinite(x) && Number.isFinite(y)) return x - y;
  }
  return a.localeCompare(b, "zh-CN", { numeric: true });
}

function ColumnMenu({ name, dtype, values, sort, filter, onSort, onFilter, onClose, anchor }: {
  name: string; dtype: string; values: Cell[]; sort: "asc" | "desc" | null; filter: Set<string> | null;
  onSort: (d: "asc" | "desc" | null) => void; onFilter: (f: Set<string> | null) => void; onClose: () => void;
  anchor: DOMRect;
}) {
  const counts = useMemo(() => {
    const m = new Map<string, number>();
    for (const v of values) m.set(keyOf(v), (m.get(keyOf(v)) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => compare(a[0] === NA ? null : a[0], b[0] === NA ? null : b[0], kindOf(dtype) === "num"));
  }, [values, dtype]);
  const [picked, setPicked] = useState<Set<string>>(() => new Set(filter ?? counts.map(([k]) => k)));
  const all = picked.size === counts.length;
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const down = (e: MouseEvent) => !box.current?.contains(e.target as Node) && onClose();
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", key);
    return () => (document.removeEventListener("mousedown", down), document.removeEventListener("keydown", key));
  }, [onClose]);
  const W = 280;
  const left = Math.max(8, Math.min(anchor.right - W, window.innerWidth - W - 8));
  const top = Math.min(anchor.bottom + 4, window.innerHeight - 420);
  const toggle = (k: string) => setPicked((p) => { const n = new Set(p); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  return (
    <div ref={box} className="col-menu" role="dialog" aria-label={`${name} 列操作`} style={{ left, top, width: W }}>
      <div className="col-menu-head">
        <strong>{name}</strong>
        <span>{values.length} 行 · {counts.length} 个不同值</span>
      </div>
      <div className="col-menu-sec">排序</div>
      <button type="button" className={sort === "asc" ? "on" : undefined} onClick={() => (onSort("asc"), onClose())}>↑ 升序排序</button>
      <button type="button" className={sort === "desc" ? "on" : undefined} onClick={() => (onSort("desc"), onClose())}>↓ 降序排序</button>
      <button type="button" disabled={!sort} onClick={() => (onSort(null), onClose())}>清除排序</button>
      <div className="col-menu-sec">筛选</div>
      <div className="col-menu-list">
        <label className="col-check col-check-all">
          <input type="checkbox" checked={all} ref={(el) => { if (el) el.indeterminate = !all && picked.size > 0; }}
            onChange={() => setPicked(all ? new Set() : new Set(counts.map(([k]) => k)))} />
          <span>（全选）</span>
        </label>
        {counts.map(([k, n]) => (
          <label key={k} className="col-check">
            <input type="checkbox" checked={picked.has(k)} onChange={() => toggle(k)} />
            <span className={k === NA ? "na" : undefined}>{labelOf(k)}</span>
            <span className="col-count">{n}</span>
          </label>
        ))}
      </div>
      <div className="col-menu-foot">
        <button type="button" className="link" disabled={!filter} onClick={() => (onFilter(null), onClose())}>清除筛选</button>
        <button type="button" className="primary" disabled={picked.size === 0}
          onClick={() => (onFilter(all ? null : picked), onClose())}>应用</button>
      </div>
    </div>
  );
}

export function PreviewTable({ table }: { table: T }) {
  const [sort, setSort] = useState<Sort>(null);
  const [filters, setFilters] = useState<Record<number, Set<string>>>({});
  const [menu, setMenu] = useState<{ col: number; rect: DOMRect } | null>(null);

  const rows = useMemo(() => {
    if (table.error !== undefined) return [];
    let rs = table.rows.map((r, i) => ({ r: r as Cell[], n: i + 1 }));
    for (const [c, set] of Object.entries(filters)) rs = rs.filter(({ r }) => set.has(keyOf(r[Number(c)])));
    if (sort) {
      const num = kindOf(table.dtypes[sort.col] ?? "") === "num";
      rs = [...rs].sort((a, b) => (sort.dir === "asc" ? 1 : -1) * compare(a.r[sort.col], b.r[sort.col], num));
    }
    return rs;
  }, [table, sort, filters]);

  if (table.error !== undefined) {
    return (
      <p className="warn" role="alert">
        {table.filename} 读取失败：{table.error}
      </p>
    );
  }
  const active = Object.keys(filters).length > 0 || sort;
  return (
    <div className="preview">
      <div className="table-scroll">
        <table className="zebra">
          <thead>
            <tr>
              <th className="rownum">#</th>
              {table.columns.map((c, i) => {
                const k = kindOf(table.dtypes[i] ?? "");
                const on = sort?.col === i || filters[i];
                return (
                  <th key={i} className={`col-${k}${on ? " col-on" : ""}`} aria-sort={sort?.col === i ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}>
                    <span className="col-head">
                      <TypeMark dtype={table.dtypes[i] ?? ""} />
                      <span className="col-name" title={c}>{c}</span>
                      {sort?.col === i ? <span className="col-flag">{sort.dir === "asc" ? "↑" : "↓"}</span> : null}
                      {filters[i] ? <span className="col-flag" title="已筛选">⏷</span> : null}
                      <button type="button" className="icon col-more" aria-label={`${c} 列操作`} title="列操作"
                        onClick={(e) => setMenu(menu?.col === i ? null : { col: i, rect: e.currentTarget.getBoundingClientRect() })}>
                        <IconMore size={14} />
                      </button>
                    </span>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map(({ r, n }) => (
              <tr key={n}>
                <td className="rownum">{n}</td>
                {r.map((v, j) => (
                  <td key={j} className={kindOf(table.dtypes[j] ?? "") === "num" ? "num" : undefined}>
                    {v === null ? <span className="na">空</span> : v}
                  </td>
                ))}
              </tr>
            ))}
            {rows.length === 0 ? (
              <tr><td className="rownum" /><td colSpan={table.columns.length} className="muted">没有符合筛选条件的行</td></tr>
            ) : null}
          </tbody>
        </table>
      </div>
      {menu ? (
        <ColumnMenu key={menu.col} name={table.columns[menu.col]} dtype={table.dtypes[menu.col] ?? ""}
          values={table.rows.map((r) => (r as Cell[])[menu.col])} anchor={menu.rect}
          sort={sort?.col === menu.col ? sort.dir : null} filter={filters[menu.col] ?? null}
          onSort={(d) => setSort(d ? { col: menu.col, dir: d } : null)}
          onFilter={(f) => setFilters((x) => { const n = { ...x }; if (f) n[menu.col] = f; else delete n[menu.col]; return n; })}
          onClose={() => setMenu(null)} />
      ) : null}
      <p className="table-foot muted">
        {table.filename}：共 {table.total_rows} 行 × {table.total_columns} 列，编码 {table.encoding}
        {table.rows.length < table.total_rows ? `，显示前 ${table.rows.length} 行` : ""}
        {active ? `；排序和筛选只作用于这 ${table.rows.length} 行，当前显示 ${rows.length} 行` : ""}
        {table.truncated_cells > 0 ? `；${table.truncated_cells} 个单元格超 200 字，已截断（末尾带 …）` : ""}
        {table.bidi_stripped > 0 ? `；${table.bidi_stripped} 处方向控制符已从预览中去掉（不影响分析）` : ""}
      </p>
    </div>
  );
}
