// 一张结构化图 = 一个 ECharts 实例（F3 第 5 条）。option 原样交给 ECharts：不 eval、不执行 formatter、不拼 option，
// 只过一遍 prepare（纵深防御）。canvas renderer：用户字符串画成像素，不进 DOM（THREAT_MODEL §2.3）。
import { init } from "echarts/core";
import { useEffect, useRef, useSyncExternalStore } from "react";
import { prepare } from "./prepare";
import { registerCharts } from "./register";
import { getChartTheme, subscribeChartTheme } from "./themes";

export type ChartSpec = { v: number; kind: string; truncated: boolean; option: Record<string, unknown> };

export function EChart({ spec }: { spec: ChartSpec }) {
  const ref = useRef<HTMLDivElement>(null);
  const inst = useRef<ReturnType<typeof init> | null>(null);
  const theme = useSyncExternalStore(subscribeChartTheme, getChartTheme);
  const themeAtInit = useRef(theme);

  useEffect(() => {
    registerCharts();
    const el = ref.current!;
    // 主题名已经过 resolveTheme 收口（不认识的回退默认）；切换走 setTheme，不 dispose、不重设 option
    const chart = init(el, themeAtInit.current, { renderer: "canvas" });
    inst.current = chart;
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(el);
    return () => {
      ro.disconnect();
      chart.dispose();
      inst.current = null;
    };
  }, []);

  useEffect(() => {
    inst.current?.setOption(prepare(spec.option, {}), { notMerge: true }); // option 变了整体重设，不做增量合并
  }, [spec]);

  useEffect(() => {
    // setTheme 内部 _resetOption('recreate') → initBase 先清空 ecModel.option：新主题没写的键不会残留旧主题的值
    inst.current?.setTheme(theme);
  }, [theme]);

  return <div ref={ref} className="echart" data-testid="echart" data-kind={spec.kind} data-theme={theme} />;
}
