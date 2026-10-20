// F3 第六步：safeFilename 表驱动（phase5-frontend.md「F3 第六步」第 3 条、验收 vitest 第一项）。逐条写期望值，不只断言"不含某字符"。
import inject from "../generated/inject.json";
import src from "./filename.ts?raw";
import { FALLBACK, NAME_MAX, safeFilename } from "./filename";

const P = inject.payloads as Record<string, string>;
const a59 = "a".repeat(59);

const CASES: [string, unknown, string | undefined, string][] = [
  // 注入载荷（P1–P7 全部）
  ["P1", P.P1, undefined, "_img src=x onerror=_window.__pwned=1__.png"],
  ["P2", P.P2, undefined, "___svg onload=_window.__pwned=2__.png"],
  ["P3", P.P3, undefined, "javascript_window.__pwned=3.png"],
  ["P4", P.P4, undefined, "{a}{b}{c}.png"],
  ["P5", P.P5, undefined, "{x_富文本}.png"],
  ["P6", P.P6, undefined, "x}{__EC_aUTo_4_999.png"],
  ["P7 换行是 C0，删掉", P.P7, undefined, "上下.png"],
  // bidi：RLO 让 gnp.exe 显示成 exe.png
  ["RLO", "\u202Egnp.exe", undefined, "gnp.exe.png"],
  ["LRI…PDI、LRM、ALM", "\u2066a\u2069\u200Eb\u061Cc", undefined, "abc.png"],
  ["C1", "a\u0085b\u009Fc", undefined, "abc.png"],
  ["行 / 段分隔符", "a\u2028b\u2029c", undefined, "abc.png"],
  // Windows 保留名：判第一个点之前的段
  ["CON", "CON", undefined, "_CON.png"],
  ["con.txt", "con.txt", undefined, "_con.txt.png"],
  ["CON.png（判成 CON.png ≠ CON 就会漏）", "CON.png", undefined, "_CON.png.png"],
  ["Nul.tar.gz", "Nul.tar.gz", undefined, "_Nul.tar.gz.png"],
  ["COM9 / LPT1", "lpt1", undefined, "_lpt1.png"],
  ["CONSOLE 不是保留名", "CONSOLE", undefined, "CONSOLE.png"],
  ["COM0 不是保留名", "COM0", undefined, "COM0.png"],
  // 首尾空格和点；清完为空回退
  ["..", "..", undefined, `${FALLBACK}.png`],
  ["空格点空格", "  . ", undefined, `${FALLBACK}.png`],
  ["全是控制字符", "\u0001\u0002\u007F\u202E", undefined, `${FALLBACK}.png`],
  ["前导点（类 Unix 隐藏文件）", ".hidden", undefined, "hidden.png"],
  ["尾随点", "报告...", undefined, "报告.png"],
  // 限长在 trim 之前：第 60 个码点是空格 / 点，截断后不能留尾巴
  ["第 60 个码点是空格", `${a59} ${"b".repeat(60)}`, undefined, `${a59}.png`],
  ["第 60 个码点是点", `${a59}.${"b".repeat(60)}`, undefined, `${a59}.png`],
  ["65 个 emoji：按码点限长，不切断代理对", "😀".repeat(65), undefined, `${"😀".repeat(60)}.png`],
  // 其余
  ["路径分隔符", "a/b\\c", undefined, "a_b_c.png"],
  ["连续空白合并（含全角空格）", "a  \u3000 b", undefined, "a b.png"],
  ["NFC", "e\u0301", undefined, "é.png"],
  ["正常中文标题原样保留", "各城市销量", undefined, "各城市销量.png"],
  ["无标题：回退到图型名", undefined, "柱状图", "柱状图.png"],
  ["空白标题：回退到图型名", "   ", "饼图", "饼图.png"],
  ["非字符串标题", 42, "折线图", "折线图.png"],
  ["没给图型名", undefined, undefined, `${FALLBACK}.png`],
];

describe("safeFilename", () => {
  test.each(CASES)("%s", (_n, title, fallback, want) => {
    expect(safeFilename(title, fallback)).toBe(want);
  });
  test("长度：保留名加 _ 后最多 61 个码点 + .png", () => {
    const n = Array.from(safeFilename(`CON.${"x".repeat(100)}`)).length;
    expect(n).toBe(NAME_MAX + 1 + 4);
  });
  test("字符集独立定义：不 import 任何模块，不复用 _CTRL / _CONTROL_CHARS（S 10-19）", () => {
    expect(src).not.toMatch(/^\s*import\s/m);
    expect(src).toMatch(/^const DROP = /m);
  });
});
