// F4 标记卡（phase5「F4：层 1 面板」第 9 条；F4 迭代 V1 改为分组浮层；V2b 按设计稿 marks-card-edit.png 对齐）。借 Tableau
// 「标记」卡的外观和点选；不借拖字段拼图（那是改数据映射，属于层 2 / 重新分析，M13 §3.2）。
// 迭代 V1（结构和无障碍语义 V2b 保留）：
// - 5 组（marksGroups.ts）：F3 开关从工具栏挪进来，加 F4 原有的系列色、轴范围、字号、合并为'其他'。
// - 不适用的项不渲染；整组不适用时组头 aria-disabled（不用 disabled 属性，仍可聚焦）。
// - 组可多开：每个组头是独立的 toggle button（aria-pressed + aria-controls），各自对应一个 role=region。
// - 开关仍经 onSwitch → setPrefs（按图型存），层 1 经 onChange → setEdit（只存这张图自己设过的字段）。
// V2b（phase5「阶段 5 收尾」B1–B4）：
// - 组从一排 tile 改成竖排组头：图标 + 组名 + 当前值 + 箭头，展开内容紧跟在自己的组头下面。
// - 整组不可用：组头仍在，当前值的位置写理由（groupReason，文案不变），aria-describedby 指向它；.marks-why 一行删掉。
// - 开关是拨动开关（input type=checkbox + role="switch"），可访问名不变。
// - 底部固定区：提示 +「应用到所有{图型}」+「完成」（= 关卡，和 Esc 同一个出口）。
// - 宽度保持 380（不跟设计的 300–316）：颜色组是"每个系列一行 × 自动 + 10 色"，316 宽放不下。
import { type ReactNode, useId, useState } from "react";
import { IconChevronDown, IconChevronRight } from "../views/icons";
import { colorByAvailable, type Edit, type EditPatch, FONT_LABEL, FONT_SIZES, type FontSize, PIE_TOP_N, rangeError, titleOf } from "./layer1";
import { GROUP_ICON, GROUP_LABEL, type Group, type GroupState, groupStates, type Item } from "./marksGroups";
import { compat, KIND_LABEL, type Shape, SWITCH_LABEL, type SwitchName, type Switches } from "./switches";
import { TITLE_MAX } from "./title";

export type Placement = { dir: "up" | "down"; maxHeight: number };

/** 组头的「当前值」（B1）。整组不可用时由调用方换成理由。 */
export function groupValue(g: Group, ctx: { shape: Shape; sw: Switches; edit: Edit; xName: string }): string {
  const { shape, sw, edit, xName } = ctx;
  const on = (s: SwitchName) => sw[s] === true && compat(s, shape).ok;
  switch (g) {
    case "color": {
      if (edit.colorBy === "data" && colorByAvailable(shape.kind, shape.series)) return `按${xName}`;
      const n = Object.keys(edit.colors).length;
      return n ? `已改 ${n} 项` : "自动";
    }
    case "label": return sw.label ? "显示数值" : "不显示";
    case "shape": return on("stack") || on("smooth") || on("radius") ? "已改" : "默认";
    case "axis": return edit.yMin === null && edit.yMax === null ? "自动" : `${edit.yMin ?? "自动"}～${edit.yMax ?? "自动"}`;
    case "text": return `${edit.title ?? "默认标题"} · ${FONT_LABEL[edit.font]}`;
  }
}

export function MarksCard({ shape, sw, onSwitch, edit, onChange, items, palette, pieCount, placement, onReset, dirty, labelTooMany,
  xName = "", titlePlaceholder = "", hasKindDefault = false, onApplyToKind, onClearKind, onDone }: {
  shape: Shape;
  sw: Switches;
  onSwitch: <K extends SwitchName>(s: K, v: Switches[K]) => void;
  edit: Edit; // 生效的层 1（图型默认 ← 这张图自己设过的）
  onChange: (p: EditPatch) => void; // 只传这次改动的字段
  items: string[]; // 颜色组列出的项：系列名；饼图和按类目着色时是类目名
  palette: readonly string[];
  pieCount: number; // 饼图合并前的类目数（非饼图为 0）
  placement: Placement;
  onReset: () => void; // 重置 = 这张图自己的层 1 改动清空 + 开关回到设计默认（不动图型默认）
  dirty: boolean;
  labelTooMany?: boolean; // 类目太多，数值标签的设计默认降为关：在开关下面说一句
  xName?: string; // x 轴名（按类目着色的选项名 / 当前值）
  titlePlaceholder?: string; // 后端标题
  hasKindDefault?: boolean;
  onApplyToKind?: () => void;
  onClearKind?: () => void;
  onDone?: () => void;
}) {
  const uid = useId();
  // V2a 验收 P0-3：打开时默认展开第一组（颜色），免得只剩组头、内容区是空的
  const [open, setOpen] = useState<Set<Group>>(() => new Set<Group>(["color" as Group]));
  const [lo, setLo] = useState(edit.yMin === null ? "" : String(edit.yMin));
  const [hi, setHi] = useState(edit.yMax === null ? "" : String(edit.yMax));
  const [title, setTitle] = useState(edit.title ?? "");
  const states = groupStates(shape);
  const pie = shape.kind === "pie";
  const byData = edit.colorBy === "data" && colorByAvailable(shape.kind, shape.series);
  const catCount = pie ? pieCount : byData ? items.length : 0;
  const repeat = (pie ? !edit.other : byData) && catCount > palette.length; // 类目多于色数，颜色会重复
  const xLabel = xName || "类目";
  const kindLabel = KIND_LABEL[shape.kind];
  const toNum = (s: string) => (s.trim() === "" ? null : Number(s));
  const range = { yMin: toNum(lo), yMax: toNum(hi) };
  const err = rangeError(range);
  const setRange = (l: string, h: string) => {
    setLo(l);
    setHi(h);
    const r = { yMin: toNum(l), yMax: toNum(h) };
    if (!rangeError(r)) onChange(r);
  };
  const setColor = (i: number, c: number | null) => {
    const colors = { ...edit.colors };
    if (c === null) delete colors[i];
    else colors[i] = c;
    onChange({ colors });
  };
  const toggle = (g: Group) => {
    const n = new Set(open);
    if (n.has(g)) n.delete(g);
    else n.add(g);
    setOpen(n);
  };
  const toggleSwitch = (name: string, checked: boolean, set: (v: boolean) => void, note?: ReactNode) => (
    <label key={name} className="marks-item sw">
      <span className="marks-key">{name}</span>
      <input type="checkbox" role="switch" className="switch" aria-label={name} checked={checked} onChange={(e) => set(e.target.checked)} />
      {note}
    </label>
  );
  const check = (s: "label" | "stack" | "smooth" | "gradient" | "radius" | "marks" | "zoom") =>
    toggleSwitch(SWITCH_LABEL[s], sw[s] === true, (v) => onSwitch(s, v),
      s === "label" && labelTooMany ? <span className="marks-note" data-testid="label-too-many">类目过多，数值标签默认关闭</span> : null);
  const renderItem = (it: Item) => {
    switch (it) {
      case "colorBy":
        return (
          <div key={it} className="marks-item">
            <span className="marks-key">按列着色</span>
            <select aria-label="按列着色" value={edit.colorBy}
              onChange={(e) => onChange({ colorBy: e.target.value === "data" ? "data" : "series", colors: {} })}>
              <option value="series">不按列（每个系列一色）</option>
              <option value="data">{xLabel}</option>
            </select>
          </div>
        );
      case "colors":
        return (
          <div key={it} className="marks-colors">
            {repeat && (
              <div className="marks-note" data-testid="marks-repeat">{catCount} 类，多于 {palette.length} 色，颜色会重复</div>
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
        return toggleSwitch("合并为'其他'", edit.other, (v) => onChange({ other: v }),
          <span className="marks-note plain">超过 {PIE_TOP_N + 1} 项时，前 {PIE_TOP_N} 项以外合并为'其他'</span>);
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
      case "title":
        return (
          <div key={it} className="marks-item">
            <span className="marks-key">标题</span>
            <input className="marks-title-input" aria-label="标题" placeholder={titlePlaceholder || "默认标题"} value={title}
              maxLength={TITLE_MAX * 2} onChange={(e) => { setTitle(e.target.value); onChange({ title: titleOf(e.target.value) }); }} />
          </div>
        );
      case "font":
        return (
          <div key={it} className="marks-item">
            <span className="marks-key">字号</span>
            <span className="seg" role="group" aria-label="字号">
              {(Object.keys(FONT_SIZES) as FontSize[]).map((f) => (
                <button key={f} type="button" aria-pressed={edit.font === f} onClick={() => onChange({ font: f })}>
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
  const head = (g: GroupState) => {
    const on = g.ok && open.has(g.group);
    const valId = `${uid}-v-${g.group}`;
    return (
      <button type="button" id={`${uid}-t-${g.group}`} className={`marks-ghead${on ? " on" : ""}`} data-group={g.group}
        aria-pressed={on} aria-controls={`${uid}-r-${g.group}`} aria-disabled={g.ok ? undefined : true}
        aria-describedby={g.ok ? undefined : valId} onClick={() => g.ok && toggle(g.group)}>
        <span className="marks-icon" aria-hidden>{GROUP_ICON[g.group]}</span>
        <span className="marks-gname">{GROUP_LABEL[g.group]}</span>
        <span className={`marks-gval${g.ok ? "" : " why"}`} id={valId} data-testid={`marks-val-${g.group}`}>
          {g.ok ? groupValue(g.group, { shape, sw, edit, xName: xLabel }) : g.reason}
        </span>
        {g.group === "color" && repeat && <span className="marks-dot" aria-label="颜色会重复" />}
        <span className="marks-chev" aria-hidden>{on ? <IconChevronDown size={11} /> : <IconChevronRight size={11} />}</span>
      </button>
    );
  };
  const style = placement.dir === "up"
    ? { bottom: "calc(100% + 4px)", maxHeight: placement.maxHeight }
    : { top: "calc(100% + 4px)", maxHeight: placement.maxHeight };
  const count = items.length; // N = 颜色组列出的项数：系列数；饼图和按类目着色时是类目数
  return (
    <div className="marks-card" data-testid="marks-card" data-dir={placement.dir} style={style}>
      <div className="marks-head">
        <span className="marks-title">标记</span>
        <span className="marks-count" data-testid="marks-count">{count} 个图形元素</span>
        <span className="marks-spacer" />
        {hasKindDefault && (
          <button type="button" className="marks-reset" onClick={onClearKind}>清除{kindLabel}默认</button>
        )}
        <button type="button" className="marks-reset" disabled={!dirty}
          onClick={() => { setLo(""); setHi(""); setTitle(""); onReset(); }}>重置</button>
      </div>
      <div className="marks-body" role="group" aria-label="样式分组">
        {states.map((g) => (
          <div key={g.group} className="marks-group">
            {head(g)}
            {g.ok && open.has(g.group) && (
              <div id={`${uid}-r-${g.group}`} role="region" aria-labelledby={`${uid}-t-${g.group}`}
                className="marks-pop" data-testid={`marks-${g.group}`}>
                {g.items.map(renderItem)}
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="marks-foot">
        <p className="marks-hint">改动只作用于这张图，不改动原始数据。</p>
        <button type="button" className="marks-apply" onClick={onApplyToKind}>应用到所有{kindLabel}</button>
        <p className="marks-hint">已单独改过的图保持不变</p>
        <button type="button" className="primary marks-done" onClick={onDone}>完成</button>
      </div>
    </div>
  );
}
