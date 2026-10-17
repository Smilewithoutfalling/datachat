// 一张结构化图 = 一个 ECharts 实例（F3 第 5 条）。option 原样交给 ECharts：不 eval、不执行 formatter、不拼 option，
// 只过一遍 prepare（纵深防御）。canvas renderer：用户字符串画成像素，不进 DOM（THREAT_MODEL §2.3）。
import { init } from "echarts/core";
import { useEffect, useRef } from "react";
import { prepare } from "./prepare";
import { registerCharts } from "./register";

export type ChartSpec = { v: number; kind: string; truncated: boolean; option: Record<string, unknown> };

export function EChart({ spec }: { spec: ChartSpec }) {
  const ref = useRef<HTMLDivElement>(null);
  const inst = useRef<ReturnType<typeof init> | null>(null);

  useEffect(() => {
    registerCharts();
    const el = ref.current!;
    const chart = init(el, null, { renderer: "canvas" });
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
    inst.current?.setOption(prepare(spec.option), { notMerge: true }); // option 变了整体重设，不做增量合并
  }, [spec]);

  return <div ref={ref} className="echart" data-testid="echart" data-kind={spec.kind} />;
}
