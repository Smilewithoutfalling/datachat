// 一张结构化图 = 一个 ECharts 实例（F3 第 5 条）。option 原样交给 ECharts：不 eval、不执行 formatter、不拼 option，
// 只过一遍 prepare（纵深防御）。canvas renderer：用户字符串画成像素，不进 DOM（THREAT_MODEL §2.3）。
// F3 第五步：EChart 持有后端原始 spec，图型 / 开关 / 主题任何一个变了都整体重算 prepare + setOption(notMerge)；
// 主题变了先 setTheme（主题的默认值层：背景、轴色）。取代第四步"切主题只调 setTheme"的路径——渐变色值由 prepare 写死，
// setTheme 换主题对象不会重算它。实例始终不重建（data-instance 不变，e2e 钉住）。
import { init } from "echarts/core";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { effectiveKind, normalize, type Ctx, type Option, prepare, type UiState } from "./prepare";
import { registerCharts } from "./register";
import {
  asKind, asXKind, canChangeKind, compat, KINDS, KIND_LABEL, type Kind, type Shape, SWITCHES, SWITCH_LABEL, SWITCH_VALUES,
  type SwitchName, type Switches,
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
    chart.setOption(prepare(spec, ui, theme), { notMerge: true });
  }, [spec, ui, theme]);

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
        </div>
      )}
    </div>
  );
}

function seriesCount(o: Option): number {
  return Array.isArray(o.series) ? o.series.length : 0;
}
