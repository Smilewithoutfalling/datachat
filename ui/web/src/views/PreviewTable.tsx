import { useEffect, useMemo, useRef, useState } from "react";
import type { Client } from "../client";
import type { PreviewTable as T, PreviewTableOk } from "../types";
import { IconMore } from "./icons";

// 单元格一律按文本渲染（THREAT_MODEL T9）；缺失值显示成灰色的"空"，和字符串 "null" 区分开
// 原型（proto/genie-shell）：斑马纹、列类型标识、列菜单（排序、按值筛选）。传了 server 时排序和筛选在后端对全表做（只读，不改数据集）；
// 没传时只作用于已加载的预览行。

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

type Counts = { rows: number; distinct: number; truncated: boolean; items: [string, number][] };

function localCounts(values: Cell[], dtype: string): Counts {
  const m = new Map<string, number>();
  for (const v of values) m.set(keyOf(v), (m.get(keyOf(v)) ?? 0) + 1);
  const items = [...m.entries()].sort((a, b) => compare(a[0] === NA ? null : a[0], b[0] === NA ? null : b[0], kindOf(dtype) === "num"));
  return { rows: values.length, distinct: items.length, truncated: false, items };
}

function ColumnMenu({ name, data, sort, filter, onSort, onFilter, onClose, anchor, error }: {
  name: string; data: Counts | null; sort: "asc" | "desc" | null; filter: Set<string> | null; error?: string;
  onSort: (d: "asc" | "desc" | null) => void; onFilter: (f: Set<string> | null) => void; onClose: () => void;
  anchor: DOMRect;
}) {
  const counts = data?.items ?? [];
  // 已筛选时以筛选为准；否则全选（值还没回来时先空着，回来后由 key 重挂载）
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
        <span>{data ? `${data.rows.toLocaleString()} 行 · ${data.distinct.toLocaleString()} 个不同值${data.truncated ? `（列出最多的 ${counts.length} 个）` : ""}` : error ?? "正在统计…"}</span>
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
        <button type="button" className="primary" disabled={picked.size === 0 || !data}
          onClick={() => (onFilter(all && !data?.truncated ? null : picked), onClose())}>应用</button>
      </div>
    </div>
  );
}

type View = PreviewTableOk & { matched_rows: number; row_numbers: number[] };
const SERVER_ROWS = 50;

export function PreviewTable({ table, server, onViewNote }: { table: T; server?: { c: Client; datasetId: string }; onViewNote?: (s: string | null) => void }) {
  const [sort, setSort] = useState<Sort>(null);
  const [filters, setFilters] = useState<Record<number, Set<string>>>({});
  const [menu, setMenu] = useState<{ col: number; rect: DOMRect; data: Counts | null; error?: string } | null>(null);
  const [view, setView] = useState<View | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const seq = useRef(0);

  const ok = table.error === undefined ? table : null;

  const refresh = (nextSort: Sort, nextFilters: Record<number, Set<string>>) => {
    setSort(nextSort);
    setFilters(nextFilters);
    if (!server || !ok) return;
    if (!nextSort && Object.keys(nextFilters).length === 0) return setView(null), setErr(""), onViewNote?.(null);
    const n = ++seq.current;
    setBusy(true);
    const f: Record<string, (string | null)[]> = {};
    for (const [c, set] of Object.entries(nextFilters)) f[c] = [...set].map((k) => (k === NA ? null : k));
    server.c.tableView(server.datasetId, { table: ok.name, sort_col: nextSort?.col ?? null, sort_dir: nextSort?.dir ?? "asc", filters: f, rows: SERVER_ROWS })
      .then((v) => {
        if (n !== seq.current) return;
        setView(v);
        setErr("");
        const shown = Math.min(v.matched_rows, v.rows.length);
        onViewNote?.(`${Object.keys(nextFilters).length ? `筛选后 ${v.matched_rows.toLocaleString()} 行` : "已排序"}（共 ${v.total_rows.toLocaleString()} 行）`
          + `${shown < v.matched_rows ? `，显示前 ${shown} 行` : ""} · 只读`);
      })
      .catch((e: unknown) => n === seq.current && setErr(e instanceof Error ? e.message : "排序筛选失败"))
      .finally(() => n === seq.current && setBusy(false));
  };

  const openMenu = (col: number, rect: DOMRect) => {
    if (menu?.col === col) return setMenu(null);
    if (!ok) return;
    if (!server) return setMenu({ col, rect, data: localCounts(ok.rows.map((r) => (r as Cell[])[col]), ok.dtypes[col] ?? "") });
    setMenu({ col, rect, data: null });
    server.c.columnValues(server.datasetId, ok.name, col).then(
      (r) => setMenu((m) => (m?.col === col ? { ...m, data: { rows: r.rows, distinct: r.distinct, truncated: r.truncated, items: r.values.map((x) => [keyOf(x.value), x.count] as [string, number]) } } : m)),
      () => setMenu((m) => (m?.col === col ? { ...m, error: "统计失败" } : m)),
    );
  };

  const rows = useMemo(() => {
    if (!ok) return [];
    if (server) {
      if (view) return view.rows.map((r, i) => ({ r: r as Cell[], n: view.row_numbers[i] ?? i + 1 }));
      return ok.rows.map((r, i) => ({ r: r as Cell[], n: i + 1 }));
    }
    let rs = ok.rows.map((r, i) => ({ r: r as Cell[], n: i + 1 }));
    for (const [c, set] of Object.entries(filters)) rs = rs.filter(({ r }) => set.has(keyOf(r[Number(c)])));
    if (sort) {
      const num = kindOf(ok.dtypes[sort.col] ?? "") === "num";
      rs = [...rs].sort((a, b) => (sort.dir === "asc" ? 1 : -1) * compare(a.r[sort.col], b.r[sort.col], num));
    }
    return rs;
  }, [ok, server, view, sort, filters]);

  if (table.error !== undefined) {
    return (
      <p className="warn" role="alert">
        {table.filename} 读取失败：{table.error}
      </p>
    );
  }
  const active = Object.keys(filters).length > 0 || sort;
  const foot = !active ? "" : server
    ? view ? `；已对全表排序筛选：符合 ${view.matched_rows.toLocaleString()} 行，显示前 ${rows.length} 行` : busy ? "；正在对全表排序筛选…" : ""
    : `；排序和筛选只作用于这 ${table.rows.length} 行，当前显示 ${rows.length} 行`;
  return (
    <div className={`preview${busy ? " is-busy" : ""}`}>
      {err ? <p className="warn" role="alert">{err}</p> : null}
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
                        onClick={(e) => openMenu(i, e.currentTarget.getBoundingClientRect())}>
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
        <ColumnMenu key={`${menu.col}:${menu.data ? "ok" : "wait"}`} name={table.columns[menu.col]} data={menu.data} error={menu.error} anchor={menu.rect}
          sort={sort?.col === menu.col ? sort.dir : null} filter={filters[menu.col] ?? null}
          onSort={(d) => refresh(d ? { col: menu.col, dir: d } : null, filters)}
          onFilter={(f) => { const n = { ...filters }; if (f) n[menu.col] = f; else delete n[menu.col]; refresh(sort, n); }}
          onClose={() => setMenu(null)} />
      ) : null}
      <p className="table-foot muted">
        {table.filename}：共 {table.total_rows} 行 × {table.total_columns} 列，编码 {table.encoding}
        {!view && table.rows.length < table.total_rows ? `，显示前 ${table.rows.length} 行` : ""}
        {foot}
        {table.truncated_cells > 0 ? `；${table.truncated_cells} 个单元格超 200 字，已截断（末尾带 …）` : ""}
        {table.bidi_stripped > 0 ? `；${table.bidi_stripped} 处方向控制符已从预览中去掉（不影响分析）` : ""}
      </p>
    </div>
  );
}
