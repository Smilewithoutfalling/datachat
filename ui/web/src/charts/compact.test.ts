// issue #49：紧凑几何。逐图型、只收紧不放宽、默认关时与原产物逐字节相同、机制测试（写出的键 ⊆ COMPACT_KEYS）。
import fixtures from "../generated/chart_fixtures.json";
import { COMPACT, COMPACT_BELOW, COMPACT_KEYS, isCompact } from "./compact";
import { type ChartInput, DEFAULT_UI, type Json, prepare } from "./prepare";

type F = { id: string; spec: ChartInput };
const FX = (fixtures as unknown as { fixtures: F[] }).fixtures;
type O = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const fx = (id: string) => FX.find((f) => f.id === id)!.spec;
const run = (spec: ChartInput, compact: boolean) => prepare(spec, { ...DEFAULT_UI, compact }) as O;

test("阈值：默认卡片 360 不触发，220 触发；0 / NaN（未布局）不触发", () => {
  expect([isCompact(360), isCompact(COMPACT_BELOW), isCompact(COMPACT_BELOW - 1), isCompact(220), isCompact(0), isCompact(NaN)])
    .toEqual([false, false, true, true, false, false]);
});
test("单系列 bar：top 60→36、bottom 30→14、nameGap 28→22、值轴 3 档且首末刻度必画", () => {
  const before = run(fx("bar"), false), o = run(fx("bar"), true);
  expect([before.grid.top, before.grid.bottom, before.xAxis.nameGap]).toEqual([60, 30, 28]);
  expect([o.grid.top, o.grid.bottom, o.xAxis.nameGap, o.yAxis.splitNumber]).toEqual([COMPACT.topTitled, 14, COMPACT.nameGap, 3]);
  expect([o.yAxis.axisLabel.showMinLabel, o.yAxis.axisLabel.showMaxLabel]).toEqual([true, true]);
});
test("无标题：top 收到 16；多系列（图例在下）bottom 50→34", () => {
  expect(run(fx("bar-untitled"), true).grid.top).toBe(COMPACT.topBare);
  expect(run(fx("line-wide"), true).grid.bottom).toBe(34);
});
test("饼图没有 grid：原样", () => {
  for (const id of ["pie", "pie-50"]) expect(JSON.stringify(run(fx(id), true))).toBe(JSON.stringify(run(fx(id), false)));
});
test("time 轴 / 散点 x 值轴：只动 y 值轴的档数", () => {
  const o = run(fx("line-time"), true);
  expect(o.xAxis.splitNumber).toBeUndefined();
  expect(o.yAxis.splitNumber).toBe(3);
});
test("默认关：全部夹具与 DEFAULT_UI 产物逐字节相同", () => {
  for (const f of FX) expect(JSON.stringify(run(f.spec, false))).toBe(JSON.stringify(prepare(f.spec)));
});

function diffPaths(a: Json, b: Json, path: string, out: Set<string>) {
  if (JSON.stringify(a) === JSON.stringify(b)) return;
  if (a && b && typeof a === "object" && typeof b === "object" && !Array.isArray(a) && !Array.isArray(b)) {
    for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) diffPaths((a as O)[k], (b as O)[k], path ? `${path}.${k}` : k, out);
    return;
  }
  out.add(path);
}
test("机制：全部夹具，紧凑写出的键 ⊆ COMPACT_KEYS，且每个键都被写到过", () => {
  const hits = new Set<string>();
  for (const f of FX) {
    const d = new Set<string>();
    diffPaths(run(f.spec, false) as Json, run(f.spec, true) as Json, "", d);
    for (const p of d) {
      const norm = p === "yAxis.axisLabel" ? "yAxis.axisLabel.showMinLabel" : p;
      expect(COMPACT_KEYS as readonly string[]).toContain(norm);
      hits.add(norm);
      if (p === "yAxis.axisLabel") hits.add("yAxis.axisLabel.showMaxLabel");
    }
  }
  expect([...hits].sort()).toEqual([...COMPACT_KEYS].sort());
});
