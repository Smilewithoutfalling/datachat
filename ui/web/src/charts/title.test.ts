// V2b B3：标题输入的清洗规则（sanitizeTitle）、存储校验（parseEdit 只丢 title）、写进 option 只有 title.text 一处、
// SSR 渲染不产生 DOM 节点、导出文件名不含 Bidi。规则见 title.ts 头注释。
import { init, use as installEcharts } from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import fixtures from "../generated/chart_fixtures.json";
import schema from "../generated/chart_schema.json";
import { safeFilename } from "./filename";
import { EMPTY_EDIT, parseEdit, titleOf } from "./layer1";
import { type ChartInput, DEFAULT_UI, prepare } from "./prepare";
import { productExtensions } from "./register";
import { isCleanTitle, sanitizeTitle, TITLE_MAX } from "./title";

installEcharts([...productExtensions(), SVGRenderer]);
const FX = (fixtures as unknown as { fixtures: { id: string; spec: ChartInput }[] }).fixtures;
const fx = (id: string) => FX.find((f) => f.id === id)!.spec;
type O = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const BIDI = ["\u061c", "\u200e", "\u200f", "\u202a", "\u202b", "\u202c", "\u202d", "\u202e", "\u2066", "\u2067", "\u2068", "\u2069"];

describe("sanitizeTitle", () => {
  test("限长和替换表来自 chart_schema.json 的 display（= 后端 TITLE_MAX / DISPLAY_UNSAFE）", () => {
    expect(TITLE_MAX).toBe(100);
    expect(schema.display.unsafe).toEqual({ "{": "\uff5b", "}": "\uff5d", "\n": " " });
  });
  test.each([
    ["rich 语法", "{a|x}", "\uff5ba|x\uff5d"],
    ["换行 / 回车 / 制表", "a\nb\r\nc\td", "a b  c d"],
    ["C1 / DEL / 行分隔符", "a\u0085b\u007fc\u2028d\u2029e", "a b c d e"],
    ["HTML 原样当文本", "<img src=x onerror=alert(1)>", "<img src=x onerror=alert(1)>"],
    ["首尾空白", "  标题 \u202e ", "标题"],
    ["全是控制符 = 空", "\u0000\u202e\n", ""],
  ])("%s", (_n, raw, want) => {
    expect(sanitizeTitle(raw)).toBe(want);
  });
  test("Bidi 控制符一律换空格", () => {
    for (const b of BIDI) expect(sanitizeTitle(`a${b}b`)).toBe("a b");
  });
  test("限长 100 码点：101 字截成 99 字 +「…」（和后端 _clean_str 同一种截法）；100 字原样；按码点不切代理对", () => {
    expect(sanitizeTitle("字".repeat(100))).toBe("字".repeat(100));
    const cut = sanitizeTitle("字".repeat(101));
    expect([Array.from(cut).length, cut.endsWith("…")]).toEqual([100, true]);
    const emoji = sanitizeTitle("😀".repeat(101));
    expect(Array.from(emoji).slice(0, 99).every((c) => c === "😀")).toBe(true);
  });
  test("幂等：清过的串再清一遍不变（存储校验靠它）", () => {
    for (const raw of ["{a|x}\n\u202eexe.png", "x".repeat(150), " a "]) expect(sanitizeTitle(sanitizeTitle(raw))).toBe(sanitizeTitle(raw));
  });
});

describe("存储校验：parseEdit 只丢 title，别的字段照常", () => {
  test.each([
    ["未清洗（含换行）", "a\nb"],
    ["未清洗（含 Bidi）", "a\u202eb"],
    ["未清洗（首尾空白）", " a"],
    ["超长", "字".repeat(101)],
    ["非字符串", 42],
    ["对象", { text: "x" }],
    ["空串", ""],
  ])("%s → 丢掉 title", (_n, title) => {
    expect(parseEdit({ title, font: "l" })).toEqual({ font: "l" });
  });
  test("清洗过的串和 null 保留", () => {
    expect(parseEdit({ title: "各城市 ｛销量｝" })).toEqual({ title: "各城市 ｛销量｝" });
    expect(parseEdit({ title: null })).toEqual({ title: null });
    expect(isCleanTitle("字".repeat(100))).toBe(true);
  });
});

describe("写进 option：只有 title.text 一处", () => {
  const INJ = "{a|x}\n<img src=x onerror=window.__pwned=1>\u202egnp.exe" + "长".repeat(120);
  const run = (title: string | null, id = "bar") => prepare(fx(id), { ...DEFAULT_UI, edit: { ...EMPTY_EDIT, title } }) as O;
  test("空串 = 回到后端标题；null 不写", () => {
    expect(titleOf("   ")).toBeNull();
    expect(run(titleOf("")).title.text).toBe((fx("bar").option.title as { text: string }).text);
  });
  test("注入串：title.text = 清洗结果，长度 100；没有标题的图也只多出 title.text", () => {
    const t = titleOf(INJ)!;
    expect(Array.from(t).length).toBe(100);
    expect(run(t).title.text).toBe(t);
    expect(run(t, "bar-untitled").title).toEqual({ text: t });
    for (const b of BIDI) expect(t.includes(b)).toBe(false);
    expect(t.includes("\n") || t.includes("{") || t.includes("}")).toBe(false);
  });
  test("SSR 渲染：注入标题画成文字，不产生 DOM 元素（SVG 里没有 img / foreignObject，文本被转义）", () => {
    const c = init(null, null, { renderer: "svg", ssr: true, width: 640, height: 400 });
    c.setOption(run(titleOf(INJ)), { notMerge: true });
    const svg = c.renderToSVGString();
    c.dispose();
    const doc = new DOMParser().parseFromString(svg, "image/svg+xml");
    expect(doc.querySelectorAll("img, foreignObject, script, [onerror]").length).toBe(0);
    expect(svg).toContain("&lt;img");
  });
  test("导出文件名：取用户标题，经 safeFilename，不含 Bidi", () => {
    const name = safeFilename(titleOf("报表\u202egnp.exe"));
    expect(name).toBe("报表 gnp.exe.png");
    for (const b of BIDI) expect(name.includes(b)).toBe(false);
  });
});
