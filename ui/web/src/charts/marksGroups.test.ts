// F4 迭代 V1 第 4 条：组级不可用只有三种情形。逐格枚举（图型 × 单/多系列 × 时间/非时间 x 轴），COMPAT 一改这里就红。
import { GROUPS, groupStates, whyLine } from "./marksGroups";
import { KINDS, type Shape } from "./switches";

const shapes: Shape[] = KINDS.flatMap((kind) => [1, 3].flatMap((series) =>
  (["category", "time"] as const).map((xKind) => ({ kind, series: kind === "pie" ? 1 : series, xKind }))));

test("组不可用的情形恰好是三种：形状（散点、饼）、轴（饼）、标签（单系列散点）", () => {
  const seen = new Set<string>();
  for (const s of shapes) for (const g of groupStates(s)) if (!g.ok) seen.add(`${g.group}|${g.reason}`);
  expect([...seen].sort()).toEqual([
    "axis|饼图没有 y 轴",
    "label|散点图不显示数值标签，单系列也没有图例",
    "shape|散点图没有可调的形状",
    "shape|饼图没有可调的形状",
  ].sort());
});

test("颜色、文字两组恒可用；每组至少有一项时才可用", () => {
  for (const s of shapes) {
    const st = groupStates(s);
    expect(st.map((g) => g.group)).toEqual([...GROUPS]);
    for (const g of st) {
      if (g.group === "color" || g.group === "text") expect(g.ok).toBe(true);
      expect(g.ok).toBe(g.items.length > 0);
    }
  }
});

test("卡内共 12 项（各图形状的并集），排序不在卡内（留在工具栏）", () => {
  const all = new Set(shapes.flatMap((s) => groupStates(s).flatMap((g) => g.items)));
  expect(all.size).toBe(12);
  expect(all.has("sort")).toBe(false);
});

test("多条理由用「 · 」连成一行", () => {
  expect(whyLine(groupStates({ kind: "pie", series: 1, xKind: "category" }))).toBe("形状：饼图没有可调的形状 · 轴：饼图没有 y 轴");
});
