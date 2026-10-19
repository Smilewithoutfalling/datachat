// 对照：故意少注册组件，证明 charts.test.ts 的"console 无 warn/error/[ECharts] log"断言真的抓得到缺组件。
// vitest 每个测试文件独立模块图，这里的 use() 不影响主测试。
import { init, use as installEcharts } from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import fixtures from "../generated/chart_fixtures.json";
import { prepare } from "./prepare";
import { ENUMS, productExtensions } from "./register";

const bar = ENUMS["series.type"].bar[0];
installEcharts([...productExtensions().filter((e) => e !== bar), SVGRenderer]); // 产品注册表本身已不含 LegacyGridContainLabel

function render(id: string, mutate: (o: Record<string, unknown>) => void = () => {}) {
  const spec = JSON.parse(JSON.stringify(fixtures.fixtures.find((f) => f.id === id)!.spec));
  mutate(spec.option);
  const spies = (["warn", "error", "log"] as const).map((m) => vi.spyOn(console, m).mockImplementation(() => {}));
  const c = init(null, null, { renderer: "svg", ssr: true, width: 640, height: 400 });
  let thrown = false;
  try {
    c.setOption(prepare(spec), { notMerge: true });
    c.renderToSVGString();
  } catch {
    thrown = true;
  } finally {
    c.dispose();
  }
  const msgs = spies.flatMap((s) => s.mock.calls.map((a) => String(a[0])));
  spies.forEach((s) => s.mockRestore());
  return { thrown, msgs };
}

// echarts 的 log 带 onlyOnce（同一句只打一次），所以 containLabel 这条放在最前面。
// 第三步起后端不再产出 containLabel（白名单已删），这里手工塞回去，只为证明"零 [ECharts] log"这道守卫仍然抓得到
// "缺 feature 只打 dev log"这一类问题。守卫在 vitest（开发构建）才有意义：生产构建里 __DEV__ 被去掉，log 不存在。
test("手工塞 containLabel 且没注册 LegacyGridContainLabel：提示走 console.log，被 [ECharts] 前缀过滤抓到", () => {
  const { msgs } = render("line", (o) => {
    o.grid = { containLabel: true };
  });
  expect(msgs.some((m) => m.startsWith("[ECharts]") && m.includes("LegacyGridContainLabel"))).toBe(true);
});

test("没注册 BarChart：渲染柱图会报错或报警", () => {
  const { thrown, msgs } = render("bar");
  expect(thrown || msgs.length > 0).toBe(true);
});
