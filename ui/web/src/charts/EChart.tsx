// 一张结构化图 = 一个 ECharts 实例（F3 第 5 条）。option 原样交给 ECharts：不 eval、不执行 formatter、不拼 option，
// 只过一遍 prepare（纵深防御）。canvas renderer：用户字符串画成像素，不进 DOM（THREAT_MODEL §2.3）。
// F3 第五步：EChart 持有后端原始 spec，图型 / 开关 / 主题任何一个变了都整体重算 prepare + setOption(notMerge)；
// 主题变了先 setTheme（主题的默认值层：背景、轴色）。取代第四步"切主题只调 setTheme"的路径——渐变色值由 prepare 写死，
// setTheme 换主题对象不会重算它。实例始终不重建（data-instance 不变，e2e 钉住）。
// F3 第六步：交互态（缩放窗口、图例显隐）在 datazoom / legendselectchanged 发生时写进 view，下一次重算（开关 / 主题）和导出
// 都带上它，导出和屏幕走同一条 prepare。view 变化本身**不**触发 setOption：屏幕上 ECharts 已经画成这样了，再整体重设一遍
// 结果相同，却会在拖动 / 滚轮途中重建 dataZoom 组件、打断手势（偏离方案第 2 条"view 变化也走整体 setOption"，DEVLOG [42]）。
// 屏幕是真相源，view 是它的镜像（S 10-19 第二轮，同 F2"status 是真相源"）：每次重算 setOption 之后从实例回读一次
// （viewFromRendered），开关关掉 dataZoom → 回读不到区间 → zoom 清空；图例项变了 → 只剩现存项。这样不需要维护
// "哪些变化要清空 view"的列表。换图型、spec 变化时仍先清空再算：类目轴 / 系列都换了，旧区间不该带到新图上。
// 回读只读 getOption() 的 dataZoom[0].start/end 和 legend[0].selected 两处（公开 API）；selected 的名字当场换成 index，
// 不往外带。view 不持久化。
import { init } from "echarts/core";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { download, exportPng } from "./exportPng";
import { safeFilename } from "./filename";
import { effectiveKind, normalize, type Ctx, type Option, prepare, type UiState } from "./prepare";
import { registerCharts } from "./register";
import {
  asKind, asXKind, asZoom, canChangeKind, viewFromRendered, compat, EMPTY_VIEW, hiddenFromSelected, KINDS, KIND_LABEL, type Kind, type Shape,
  SWITCHES, SWITCH_LABEL, SWITCH_VALUES, type SwitchName, type Switches, type View,
} from "./switches";
import { getChartTheme, subscribeChartTheme } from "./themes";
import { getPrefs, setPrefs, subscribePrefs } from "./uiPrefs";

export type ChartSpec = { v: number; kind: string; truncated: boolean; x_kind?: string; option: Record<string, unknown> };

const CHOICE_LABEL: Partial<Record<SwitchName, Record<string, string>>> = {
  legend: { bottom: "图例在下", top: "图例在上" },
  sort: { off: "不排序", desc: "降序", asc: "升序" },
};

export function EChart({ spec }: { spec: ChartSpec }) {
  const ref = useRef<HTMLDivElement>(null);
  const inst = useRef<ReturnType<typeof init> | null>(null);
  const theme = useSyncExternalStore(subscribeChartTheme, getChartTheme);
  const themeApplied = useRef(theme);
  const [target, setTarget] = useState<Kind | null>(null); // 换成什么图型：不持久化，刷新回到后端图型
  const view = useRef<View>(EMPTY_VIEW);
  const shown = useRef<Option | null>(null); // 屏幕上当前这份 prepare 产物：legendselectchanged 的名字按它换成 index
  const viewFor = useRef<{ spec: ChartSpec; target: Kind | null } | null>(null);
  const [light, setLight] = useState(false); // 导出为浅色（经典配色）：不持久化
  const [exportFailed, setExportFailed] = useState(false);
  const src = asKind(spec.kind);
  const kind = effectiveKind(spec, { kind: target, sw: getPrefs(src ?? "bar") });
  const prefKind = kind ?? "bar";
  const sw = useSyncExternalStore(subscribePrefs, () => getPrefs(prefKind));
  const ui: UiState = useMemo(() => ({ kind: target, sw }), [target, sw]);

  // 兼容性按"换完之后"的 option 算（系列数、图型）；换图型的可选项按后端原始 option 算
  const base = useMemo(() => normalize(JSON.parse(JSON.stringify(spec.option)) as Option, {} as Ctx), [spec]);
  const shape: Shape | null = kind ? { kind, series: kind === "pie" ? 1 : seriesCount(base), xKind: asXKind(spec.x_kind) } : null;

  useEffect(() => {
    registerCharts();
    const el = ref.current!;
    const chart = init(el, themeApplied.current, { renderer: "canvas" });
    inst.current = chart;
    el.dataset.instance = chart.id;
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(el);
    return () => {
      ro.disconnect();
      chart.dispose();
      inst.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = inst.current;
    if (!chart) return;
    if (themeApplied.current !== theme) {
      chart.setTheme(theme); // 默认值层先换；option 紧接着整体重设
      themeApplied.current = theme;
    }
    if (viewFor.current?.spec !== spec || viewFor.current.target !== target) {
      view.current = EMPTY_VIEW; // 换图型 / 换 spec：系列数和类目轴都可能变，旧的 index 和区间没有意义
      viewFor.current = { spec, target };
    }
    const option = prepare(spec, { ...ui, view: view.current }, theme);
    shown.current = option as Option;
    chart.setOption(option, { notMerge: true });
    view.current = viewFromRendered(chart.getOption() as Option, option as Option);
  }, [spec, ui, theme, target]);

  // 交互态写进 view（只存数值：区间和 index）。datazoom 的参数两种形状：inside 漫游是 batch[0]，dispatchAction 是顶层。
  useEffect(() => {
    const chart = inst.current;
    if (!chart) return;
    const onZoom = (e: unknown) => {
      const p = e as { start?: unknown; end?: unknown; batch?: { start?: unknown; end?: unknown }[] };
      const b = Array.isArray(p.batch) && p.batch[0] ? p.batch[0] : p;
      view.current = { ...view.current, zoom: asZoom(b.start, b.end) };
    };
    const onLegend = (e: unknown) => {
      const o = shown.current;
      if (o) view.current = { ...view.current, hidden: hiddenFromSelected(o, (e as { selected?: unknown }).selected) };
    };
    chart.on("datazoom", onZoom);
    chart.on("legendselectchanged", onLegend);
    return () => {
      if (chart.isDisposed()) return;
      chart.off("datazoom", onZoom);
      chart.off("legendselectchanged", onLegend);
    };
  }, []);

  // 缩放的恢复入口：toolbox 在 BANNED_KEYS 里，restore 用不了，自己接双击。挂 zr 不挂 chart.on：实例级事件只在命中带
  // dataIndex 的元素时派发，空白处不触发（echarts.js:843–870）。e.target 有值 = ECharts 自己的交互（图例双击切显隐、柱子），
  // 不重置；空白才是我们的手势（S 10-19）。缩到一个点时周围全是空白，总能点到。
  const zoomOn = !!shape && sw.zoom && compat("zoom", shape).ok;
  useEffect(() => {
    const chart = inst.current;
    if (!chart || !zoomOn) return;
    const zr = chart.getZr();
    const reset = (e: { target?: unknown }) => {
      if (e.target) return;
      chart.dispatchAction({ type: "dataZoom", start: 0, end: 100 });
    };
    zr.on("dblclick", reset);
    // 普通滚轮（不按 Shift）在到达 ECharts 之前拦下，让它只滚页面。原因（F3 第五步实测，偏离方案 A 的源码依据）：
    // echarts 6.1.0 的 dataZoom inside 给 RoamController 的是统一配置 zoomOnMouseWheel / moveOnMouseWheel 都为 true
    // （lib/component/dataZoom/roams.js:175-181），每个 dataZoom 自己的 'shift' / false 要到监听器里才判
    // （roams.js:107）；而 RoamController 在触发监听器之前、只要指针在 grid 内就先 eventTool.stop(e.event)
    // （lib/component/helper/RoamController.js:316-322，preventDefault + stopPropagation）。所以只靠 option，
    // plot 区里的每一次滚轮都会被吞、页面滚不动（e2e「缩放」实测）。capture 阶段在容器上 stopPropagation：
    // 事件到不了 zrender 的监听器，默认动作（滚页面）照常；按着 Shift 的不拦，交给 ECharts 缩放。
    const el = ref.current!;
    const pass = (e: WheelEvent) => {
      if (!e.shiftKey) e.stopPropagation();
    };
    el.addEventListener("wheel", pass, { capture: true, passive: true });
    return () => {
      el.removeEventListener("wheel", pass, { capture: true });
      if (!chart.isDisposed()) zr.off("dblclick", reset);
    };
  }, [zoomOn]);

  const set = <K extends SwitchName>(s: K, v: Switches[K]) => setPrefs(prefKind, { ...sw, [s]: v });

  const onExport = () => {
    try {
      const el = ref.current!;
      const size = { width: el.clientWidth, height: el.clientHeight }; // 0（display:none）由 exportPng 抛错，显示导出失败
      const t = theme === "darkCanvas" && light ? "classic" : theme;
      const url = exportPng(spec, { ...ui, view: view.current }, t, size);
      const title = (spec.option.title as { text?: unknown } | undefined)?.text;
      download(url, safeFilename(title, kind ? KIND_LABEL[kind] : undefined));
      setExportFailed(false);
    } catch {
      setExportFailed(true);
    }
  };

  return (
    <div className="echart-wrap">
      <div ref={ref} className="echart" data-testid="echart" data-kind={spec.kind} data-shown-kind={kind ?? ""} data-theme={theme} />
      {src && shape && (
        <div className="chart-controls" data-testid="chart-controls">
          <label>
            图型{" "}
            <select aria-label="图型" value={kind ?? ""} onChange={(e) => setTarget(asKind(e.target.value))}>
              {KINDS.map((k) => {
                const v = canChangeKind(base, src, k, asXKind(spec.x_kind));
                return (
                  <option key={k} value={k} disabled={!v.ok} title={v.ok ? undefined : v.reason}>
                    {KIND_LABEL[k]}
                  </option>
                );
              })}
            </select>
          </label>
          {SWITCHES.map((s) => {
            const v = compat(s, shape);
            const title = v.ok ? undefined : v.reason;
            const choices = CHOICE_LABEL[s];
            if (choices) {
              return (
                <label key={s} title={title}>
                  <select aria-label={SWITCH_LABEL[s]} disabled={!v.ok} value={String(sw[s])}
                    onChange={(e) => set(s, e.target.value as Switches[typeof s])}>
                    {(SWITCH_VALUES[s] as readonly string[]).map((x) => <option key={x} value={x}>{choices[x]}</option>)}
                  </select>
                </label>
              );
            }
            return (
              <label key={s} title={title}>
                <input type="checkbox" aria-label={SWITCH_LABEL[s]} disabled={!v.ok} checked={sw[s] === true}
                  onChange={(e) => set(s, e.target.checked as Switches[typeof s])} />
                {SWITCH_LABEL[s]}
              </label>
            );
          })}
          {zoomOn && <span className="chart-hint">Shift + 滚轮缩放，拖动平移，双击空白处还原</span>}
          <span className="chart-export">
            <button type="button" onClick={onExport}>导出 PNG</button>
            {theme === "darkCanvas" && (
              <label>
                <input type="checkbox" checked={light} onChange={(e) => setLight(e.target.checked)} />
                导出为浅色（经典配色）
              </label>
            )}
            {exportFailed && <span className="warn small" role="alert">导出失败</span>}
          </span>
        </div>
      )}
    </div>
  );
}

function seriesCount(o: Option): number {
  return Array.isArray(o.series) ? o.series.length : 0;
}
