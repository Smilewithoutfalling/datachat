// 阶段 7.6 U1：字阶表，docs/roadmap/phase76-ui.md §2 U1 的验收。原来只有三级（标题 20/22，正文 13，辅助 12）；
// S 11-20 定（C1）新增一档聊天阅读 14（--fs-read）：聊天气泡、回答正文（含其中 Markdown）、输入框在 U1 里从 14 降到 13 后读着偏小，
// 退回 14，但只给这几处用（READ_SELECTORS），别的正文仍是 13。所以断言从「三级四档」改成「四级五档」，并加一条钉住 --fs-read 的使用范围。
// styles.css 里每一处 font-size 都只能取字阶表里的值：
//   - :root 定义 --fs-*，其值必须是 calc(N * var(--px))，N 和 TYPE_SCALE 一一对应；
//   - 其余 font-size 一律写 var(--fs-*)，不许直接写数字（calc(11 * var(--px))、12px、.9em 都算违规）；
//   - 唯一例外是 :root 的根字号（14px），它是 --px 的锚，不是一档字号。
import css from "./styles.css?raw";
import { READ_SELECTORS, TYPE_SCALE } from "./typeScale";

type Decl = { selector: string; value: string };

/** 去注释后按「选择器 { 声明 }」切块，@media 之类的外层块不影响内层规则的选择器。 */
function fontSizeDecls(src: string): Decl[] {
  const text = src.replace(/\/\*[\s\S]*?\*\//g, "");
  const out: Decl[] = [];
  const rule = /([^{}]+)\{([^{}]*)\}/g;
  for (let m = rule.exec(text); m; m = rule.exec(text)) {
    const selector = m[1].trim();
    for (const d of m[2].split(";")) {
      const i = d.indexOf(":");
      if (i < 0) continue;
      if (d.slice(0, i).trim() === "font-size") out.push({ selector, value: d.slice(i + 1).trim() });
    }
  }
  return out;
}

function rootVars(src: string): Record<string, string> {
  const text = src.replace(/\/\*[\s\S]*?\*\//g, "");
  const root = /:root\s*\{([^{}]*)\}/.exec(text);
  const vars: Record<string, string> = {};
  for (const d of (root?.[1] ?? "").split(";")) {
    const m = /^\s*(--fs-[\w-]+)\s*:\s*(.+?)\s*$/.exec(d);
    if (m) vars[m[1]] = m[2];
  }
  return vars;
}

describe("字阶表（U1）", () => {
  test("字阶表四级五档：标题 20/22，正文 13，聊天阅读 14，辅助 12", () => {
    expect(TYPE_SCALE).toEqual({ aux: 12, body: 13, read: 14, title: 20, "title-lg": 22 });
  });

  test("--fs-read 只用在聊天阅读区：气泡、回答正文、回答里的 Markdown 小标题、输入框", () => {
    const users = fontSizeDecls(css).filter((d) => d.value === "var(--fs-read)").map((d) => d.selector);
    expect(users.sort()).toEqual([...READ_SELECTORS].sort());
  });

  test(":root 的 --fs-* 与 TYPE_SCALE 一一对应，值写成 calc(N * var(--px))", () => {
    const vars = rootVars(css);
    const want = Object.fromEntries(Object.entries(TYPE_SCALE).map(([k, n]) => [`--fs-${k}`, `calc(${n} * var(--px))`]));
    expect(vars).toEqual(want);
  });

  test("styles.css 的 font-size 只取字阶表里的值（var(--fs-*)）", () => {
    const allowed = new Set(Object.keys(TYPE_SCALE).map((k) => `var(--fs-${k})`));
    const decls = fontSizeDecls(css);
    expect(decls.length).toBeGreaterThan(100); // 解析器没漏读：现在约 150 处
    const bad = decls.filter((d) => !(d.selector === ":root" && d.value === "14px") && !allowed.has(d.value));
    expect(bad).toEqual([]);
  });

  test("自检：直接写数字的 font-size 会被抓出来", () => {
    const sample = ".a { font-size: calc(11 * var(--px)); } .b { color: red; font-size: 12px } .c { font-size: var(--fs-aux); }";
    const allowed = new Set(Object.keys(TYPE_SCALE).map((k) => `var(--fs-${k})`));
    expect(fontSizeDecls(sample).filter((d) => !allowed.has(d.value)).map((d) => d.selector)).toEqual([".a", ".b"]);
  });
});
