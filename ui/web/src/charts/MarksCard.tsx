// F4 层 1 面板：借鉴 Tableau「标记」卡的外观和点选（S 10-20）。只借外观：一排小方块按钮，点一下展开自己的浮层；
// 不借拖字段拼图（那是改数据映射，属于层 2 / 重新分析，M13 §3.2）。改动经 setEdit 存 localStorage，EChart 整体重算。
import { useState } from "react";
import { type Edit, EMPTY_EDIT, FONT_LABEL, FONT_SIZES, type FontSize, hasAxis, isEmptyEdit, PIE_TOP_N, rangeError } from "./layer1";
import type { Kind } from "./switches";

type Tab = "color" | "axis" | "text" | "other";

export function MarksCard({ kind, edit, onChange, items, palette }: {
  kind: Kind;
  edit: Edit;
  onChange: (e: Edit) => void;
  items: string[]; // 系列名（饼图是扇区名），按 index
  palette: readonly string[];
}) {
  const [tab, setTab] = useState<Tab | null>(null);
  const [lo, setLo] = useState(edit.yMin === null ? "" : String(edit.yMin));
  const [hi, setHi] = useState(edit.yMax === null ? "" : String(edit.yMax));
  const axis = hasAxis(kind);
  const pie = kind === "pie";
  const toNum = (s: string) => (s.trim() === "" ? null : Number(s));
  const range = { yMin: toNum(lo), yMax: toNum(hi) };
  const err = rangeError(range);
  const setRange = (l: string, h: string) => {
    setLo(l);
    setHi(h);
    const r = { yMin: toNum(l), yMax: toNum(h) };
    if (!rangeError(r)) onChange({ ...edit, ...r });
  };
  const tiles: { id: Tab; icon: string; label: string; off?: string }[] = [
    { id: "color", icon: "◐", label: "颜色" },
    { id: "axis", icon: "↕", label: "轴范围", off: axis ? undefined : "饼图没有 y 轴" },
    { id: "text", icon: "A", label: "字号" },
    { id: "other", icon: "◔", label: "合并", off: pie ? undefined : "只有饼图能合并为'其他'" },
  ];
  const setColor = (i: number, c: number | null) => {
    const colors = { ...edit.colors };
    if (c === null) delete colors[i];
    else colors[i] = c;
    onChange({ ...edit, colors });
  };
  return (
    <div className="marks-card" data-testid="marks-card">
      <div className="marks-head">
        <span className="marks-title">标记</span>
        <button type="button" className="marks-reset" disabled={isEmptyEdit(edit)}
          onClick={() => { setLo(""); setHi(""); onChange(EMPTY_EDIT); }}>重置</button>
      </div>
      <div className="marks-tiles" role="tablist">
        {tiles.map((t) => (
          <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} disabled={!!t.off} title={t.off}
            className={`marks-tile${tab === t.id ? " on" : ""}`} onClick={() => setTab(tab === t.id ? null : t.id)}>
            <span className="marks-icon" aria-hidden>{t.icon}</span>
            <span>{t.label}</span>
          </button>
        ))}
      </div>
      {tab === "color" && (
        <div className="marks-pop" data-testid="marks-color">
          {items.map((name, i) => (
            <div key={i} className="marks-row">
              <span className="marks-name" title={name}>{name}</span>
              <span className="swatches">
                <button type="button" className={`swatch auto${edit.colors[i] === undefined ? " on" : ""}`} aria-label={`${name} 自动`}
                  onClick={() => setColor(i, null)}>自动</button>
                {palette.map((c, k) => (
                  <button key={k} type="button" className={`swatch${edit.colors[i] === k ? " on" : ""}`} style={{ background: c }}
                    aria-label={`${name} 颜色 ${k + 1}`} onClick={() => setColor(i, k)} />
                ))}
              </span>
            </div>
          ))}
        </div>
      )}
      {tab === "axis" && axis && (
        <div className="marks-pop" data-testid="marks-axis">
          <label>最小 <input aria-label="y 轴最小值" inputMode="decimal" placeholder="自动" value={lo} className={err ? "bad" : ""}
            onChange={(e) => setRange(e.target.value, hi)} /></label>
          <label>最大 <input aria-label="y 轴最大值" inputMode="decimal" placeholder="自动" value={hi} className={err ? "bad" : ""}
            onChange={(e) => setRange(lo, e.target.value)} /></label>
          {err && <span className="warn small" role="alert">{err}</span>}
          {kind === "bar" && range.yMin !== null && range.yMin > 0 && !err && (
            <span className="marks-note">柱图 y 轴不从 0 开始会夸大差异</span>
          )}
        </div>
      )}
      {tab === "text" && (
        <div className="marks-pop seg" data-testid="marks-text">
          {(Object.keys(FONT_SIZES) as FontSize[]).map((f) => (
            <button key={f} type="button" className={edit.font === f ? "on" : ""} onClick={() => onChange({ ...edit, font: f })}>
              {FONT_LABEL[f]} {FONT_SIZES[f]}
            </button>
          ))}
        </div>
      )}
      {tab === "other" && pie && (
        <div className="marks-pop" data-testid="marks-other">
          <label>
            <input type="checkbox" checked={edit.other} onChange={(e) => onChange({ ...edit, other: e.target.checked })} />
            超过 {PIE_TOP_N + 1} 项时，前 {PIE_TOP_N} 项以外合并为'其他'
          </label>
        </div>
      )}
    </div>
  );
}
