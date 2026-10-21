// F4 标记卡（phase5「F4：层 1 面板」第 9 条；F4 迭代 V1 改为分组浮层）。借 Tableau「标记」卡的外观和点选；
// 不借拖字段拼图（那是改数据映射，属于层 2 / 重新分析，M13 §3.2）。
// 迭代 V1：
// - 5 组 12 项（marksGroups.ts）：8 个 F3 开关从工具栏挪进来，加 F4 原有的系列色、轴范围、字号、合并为'其他'。
// - 不适用的项不渲染；整组不适用时 tile aria-disabled（不用 disabled 属性，仍可聚焦），理由常显在 .marks-why 一行。
// - 组可多开：每个 tile 是独立的 toggle button（aria-pressed + aria-controls），各自对应一个 role=region。
// - 开关仍经 onSwitch → setPrefs（按图型存），层 1 仍经 onChange → setEdit；语义、COMPAT、存储都不变。
import { useId, useState } from "react";
import { type Edit, EMPTY_EDIT, FONT_LABEL, FONT_SIZES, type FontSize, isEmptyEdit, PIE_TOP_N, rangeError } from "./layer1";
import { GROUP_ICON, GROUP_LABEL, type Group, groupStates, type Item, whyLine } from "./marksGroups";
import { type Shape, SWITCH_LABEL, type SwitchName, type Switches } from "./switches";

export type Placement = { dir: "up" | "down"; maxHeight: number };

export function MarksCard({ shape, sw, onSwitch, edit, onChange, items, palette, pieCount, placement }: {
  shape: Shape;
  sw: Switches;
  onSwitch: <K extends SwitchName>(s: K, v: Switches[K]) => void;
  edit: Edit;
  onChange: (e: Edit) => void;
  items: string[]; // 系列名（饼图是扇区名），按 index
  palette: readonly string[];
  pieCount: number; // 饼图合并前的类目数（非饼图为 0）
  placement: Placement;
}) {
  const uid = useId();
  const [open, setOpen] = useState<Set<Group>>(() => new Set());
  const [lo, setLo] = useState(edit.yMin === null ? "" : String(edit.yMin));
  const [hi, setHi] = useState(edit.yMax === null ? "" : String(edit.yMax));
  const states = groupStates(shape);
  const why = whyLine(states);
  const pie = shape.kind === "pie";
  const repeat = pie && pieCount > palette.length && !edit.other; // 第 8 条：类目多于色数，颜色会重复
  const toNum = (s: string) => (s.trim() === "" ? null : Number(s));
  const range = { yMin: toNum(lo), yMax: toNum(hi) };
  const err = rangeError(range);
  const setRange = (l: string, h: string) => {
    setLo(l);
    setHi(h);
    const r = { yMin: toNum(l), yMax: toNum(h) };
    if (!rangeError(r)) onChange({ ...edit, ...r });
  };
  const setColor = (i: number, c: number | null) => {
    const colors = { ...edit.colors };
    if (c === null) delete colors[i];
    else colors[i] = c;
    onChange({ ...edit, colors });
  };
  const toggle = (g: Group) => {
    const n = new Set(open);
    if (n.has(g)) n.delete(g);
    else n.add(g);
    setOpen(n);
  };
  const check = (s: "label" | "stack" | "smooth" | "gradient" | "radius" | "marks" | "zoom") => (
    <label key={s} className="marks-item">
      <span className="marks-key">{SWITCH_LABEL[s]}</span>
      <input type="checkbox" aria-label={SWITCH_LABEL[s]} checked={sw[s] === true} onChange={(e) => onSwitch(s, e.target.checked)} />
    </label>
  );
  const renderItem = (it: Item) => {
    switch (it) {
      case "colors":
        return (
          <div key={it} className="marks-colors">
            {repeat && (
              <div className="marks-note" data-testid="marks-repeat">{pieCount} 类，多于 {palette.length} 色，颜色会重复</div>
            )}
            <div className="marks-swatch-list">
              {items.map((name, i) => (
                <div key={i} className="marks-item">
                  <span className="marks-key" title={name}>{name}</span>
                  <span className="swatches">
                    <button type="button" className="swatch auto" aria-pressed={edit.colors[i] === undefined}
                      aria-label={`${name} 自动`} onClick={() => setColor(i, null)}>自动</button>
                    {palette.map((c, k) => (
                      <button key={k} type="button" className="swatch" aria-pressed={edit.colors[i] === k} style={{ background: c }}
                        aria-label={`${name} 颜色 ${k + 1}`} onClick={() => setColor(i, k)} />
                    ))}
                  </span>
                </div>
              ))}
            </div>
          </div>
        );
      case "other":
        return (
          <label key={it} className="marks-item wide">
            <input type="checkbox" aria-label="合并为'其他'" checked={edit.other} onChange={(e) => onChange({ ...edit, other: e.target.checked })} />
            <span>超过 {PIE_TOP_N + 1} 项时，前 {PIE_TOP_N} 项以外合并为'其他'</span>
          </label>
        );
      case "legend":
        return (
          <div key={it} className="marks-item">
            <span className="marks-key">{SWITCH_LABEL.legend}</span>
            <span className="seg" role="group" aria-label={SWITCH_LABEL.legend}>
              {(["bottom", "top"] as const).map((v) => (
                <button key={v} type="button" aria-pressed={sw.legend === v} onClick={() => onSwitch("legend", v)}>
                  {v === "bottom" ? "下" : "上"}
                </button>
              ))}
            </span>
          </div>
        );
      case "range":
        return (
          <div key={it} className="marks-range">
            <div className="marks-item">
              <span className="marks-key">y 轴范围</span>
              <span className="marks-inputs">
                <input aria-label="y 轴最小值" inputMode="decimal" placeholder="自动" value={lo} className={err ? "bad" : ""}
                  onChange={(e) => setRange(e.target.value, hi)} />
                <span className="tilde">～</span>
                <input aria-label="y 轴最大值" inputMode="decimal" placeholder="自动" value={hi} className={err ? "bad" : ""}
                  onChange={(e) => setRange(lo, e.target.value)} />
              </span>
            </div>
            {err && <span className="warn small" role="alert">{err}</span>}
            {shape.kind === "bar" && range.yMin !== null && range.yMin > 0 && !err && (
              <span className="marks-note">柱图 y 轴不从 0 开始会夸大差异</span>
            )}
          </div>
        );
      case "font":
        return (
          <div key={it} className="marks-item">
            <span className="marks-key">字号</span>
            <span className="seg" role="group" aria-label="字号">
              {(Object.keys(FONT_SIZES) as FontSize[]).map((f) => (
                <button key={f} type="button" aria-pressed={edit.font === f} onClick={() => onChange({ ...edit, font: f })}>
                  {FONT_LABEL[f]} {FONT_SIZES[f]}
                </button>
              ))}
            </span>
          </div>
        );
      case "sort":
        return null; // 排序留在工具栏（第 1 条）
      default:
        return check(it);
    }
  };
  const style = placement.dir === "up"
    ? { bottom: "calc(100% + 4px)", maxHeight: placement.maxHeight }
    : { top: "calc(100% + 4px)", maxHeight: placement.maxHeight };
  return (
    <div className="marks-card" data-testid="marks-card" data-dir={placement.dir} style={style}>
      <div className="marks-head">
        <span className="marks-title">标记</span>
        <button type="button" className="marks-reset" disabled={isEmptyEdit(edit)}
          onClick={() => { setLo(""); setHi(""); onChange(EMPTY_EDIT); }}>重置</button>
      </div>
      <div className="marks-tiles" role="group" aria-label="样式分组">
        {states.map((g) => {
          const on = g.ok && open.has(g.group);
          return (
            <button key={g.group} type="button" id={`${uid}-t-${g.group}`} className={`marks-tile${on ? " on" : ""}`}
              aria-pressed={on} aria-controls={`${uid}-r-${g.group}`} aria-disabled={g.ok ? undefined : true}
              aria-describedby={g.ok ? undefined : `${uid}-why`} onClick={() => g.ok && toggle(g.group)}>
              <span className="marks-icon" aria-hidden>{GROUP_ICON[g.group]}</span>
              <span>{GROUP_LABEL[g.group]}</span>
              {g.group === "color" && repeat && <span className="marks-dot" aria-label="颜色会重复" />}
            </button>
          );
        })}
      </div>
      <div className="marks-why" id={`${uid}-why`} data-testid="marks-why">{why}</div>
      {states.filter((g) => g.ok && open.has(g.group)).map((g) => (
        <div key={g.group} id={`${uid}-r-${g.group}`} role="region" aria-labelledby={`${uid}-t-${g.group}`}
          className="marks-pop" data-testid={`marks-${g.group}`}>
          {g.items.map(renderItem)}
        </div>
      ))}
    </div>
  );
}
