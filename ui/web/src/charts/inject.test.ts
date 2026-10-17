// F3 第二步：注入夹具（chart_fixtures.json 的 inject-*，后端 build_option 真产出）用 SSR SVG 渲染。
// SVG 只是断言工具：产品是 canvas（文本画成像素），canvas 上的结论见 e2e/f3-inject.spec.ts 与 THREAT_MODEL §2.3。
// 这里证明两件事：载荷确实到了渲染器（攻击成立的前提），以及到了之后只以转义文本出现，不成标签、不成属性。
import { init, use as installEcharts } from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import fixtures from "../generated/chart_fixtures.json";
import inject from "../generated/inject.json";
import { prepare } from "./prepare";
import { productExtensions } from "./register";

installEcharts([...productExtensions(), SVGRenderer]);

type Spec = { kind: string; option: { series: { name: string; data: unknown[] }[] } & Record<string, unknown> };
const INJ = fixtures.fixtures.filter((f) => f.id.startsWith("inject-")) as unknown as { id: string; spec: Spec }[];
const P = inject.payloads;

test("注入夹具齐全：bar 宽表、bar 长表、pie", () => {
  expect(INJ.map((f) => f.id)).toEqual(["inject-bar", "inject-bar-series", "inject-pie"]);
});

describe.each(INJ.map((f) => [f.id, f.spec] as const))("%s：SSR SVG", (_id, spec) => {
  let svg = "";
  beforeAll(() => {
    const c = init(null, null, { renderer: "svg", ssr: true, width: 640, height: 400 });
    c.setOption(prepare(spec.option), { notMerge: true });
    svg = c.renderToSVGString();
    c.dispose();
  });

  // 不用正则查原串：转义后的文本里本来就有 " onerror=" 这几个字（&lt;img src=x onerror=&quot;…），要按 XML 结构判。
  const doc = () => new DOMParser().parseFromString(svg, "image/svg+xml");

  test("载荷到达渲染器：每个 series 都有图元，P1 / P2 作为文本节点完整出现", () => {
    const d = doc();
    expect(d.getElementsByTagName("parsererror")).toHaveLength(0);
    expect(svg).toMatch(spec.kind === "pie" ? /<path/ : /<path|<rect/);
    const texts = [...d.getElementsByTagName("text")].map((t) => t.textContent ?? "");
    expect(texts).toContain(P.P1); // 标题
    expect(texts.some((t) => t.includes(P.P2))).toBe(true); // 宽表图例 / 长表 y 轴名 / 饼图扇区
    expect(svg).toContain("&lt;img src=x onerror="); // 序列化时转义了
  });

  test("没有载荷造出来的元素和属性：无 img/script/iframe/object/embed/foreignObject，无 on* 属性，无 javascript: 链接", () => {
    const all = [...doc().getElementsByTagName("*")];
    expect(all.length).toBeGreaterThan(10);
    const tags = new Set(all.map((e) => e.tagName.toLowerCase()));
    for (const t of ["img", "script", "iframe", "object", "embed", "foreignobject", "a"]) expect([t, tags.has(t)]).toEqual([t, false]);
    expect(all.filter((e) => e.tagName.toLowerCase() === "svg")).toHaveLength(1); // 只有根，P2 没造出 <svg>
    const bad = all.flatMap((e) => [...e.attributes].filter((a) => /^on/i.test(a.name) || /^\s*javascript:/i.test(a.value)).map((a) => `${e.tagName}@${a.name}`));
    expect(bad).toEqual([]);
  });
});
