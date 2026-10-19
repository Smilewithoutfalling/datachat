// F3 第六步：导出文件名清洗（docs/roadmap/phase5-frontend.md「F3 第六步」第 3 条）。
// 导出文件名是用户字符串离开画布的唯一出口（THREAT_MODEL §2.3）。来源 option.title.text：后端 _clean_str 清过一遍，
// 但它的 _CTRL（app/tools/charts.py）不含 C1 和 bidi，重放路径又不过 validate_spec，所以这里不信任上游，自己清。
// 字符集在本文件独立定义、表驱动测试（filename.test.ts），**不复用** charts.py 的 _CTRL，也不复用 app/server/app.py 的
// _CONTROL_CHARS（S 10-19）：三处用途不同，"统一一下"会把 RLO 防线的依据搞混。
// 顺序有讲究：限长在 trim 之前，否则截断会重新造出尾随空格 / 点（S 10-19）；保留名判第一个点之前的段，所以 CON.png 也算。

/** 删除：C0、DEL、C1、行 / 段分隔符、bidi 控制符（RLO 能让 gnp.exe 显示成 exe.png）。 */
// eslint-disable-next-line no-control-regex -- 删控制字符正是这条正则的用途
const DROP = /[\u0000-\u001f\u007f-\u009f\u2028\u2029\u200e\u200f\u061c\u202a-\u202e\u2066-\u2069]/gu;
/** 换成 _：路径分隔符和 Windows 文件名非法字符。 */
const ILLEGAL = /[\\/:*?"<>|]/g;
const RESERVED = new Set(["CON", "PRN", "AUX", "NUL", ...[1, 2, 3, 4, 5, 6, 7, 8, 9].flatMap((n) => [`COM${n}`, `LPT${n}`])]);
export const NAME_MAX = 60;
export const FALLBACK = "图表";

/** 清洗后的文件名（含 .png）。title 不是非空字符串时用 fallback（调用方传图型名，如"柱状图"）。 */
export function safeFilename(title: unknown, fallback: string = FALLBACK): string {
  const raw = typeof title === "string" && title.trim() ? title : fallback;
  let s = raw.normalize("NFC").replace(DROP, "").replace(ILLEGAL, "_").replace(/\s+/gu, " ");
  s = Array.from(s).slice(0, NAME_MAX).join(""); // 按码点，不切断代理对
  s = s.replace(/^[\s.]+|[\s.]+$/gu, "");
  if (!s) s = FALLBACK;
  if (RESERVED.has(s.split(".")[0].trimEnd().toUpperCase())) s = `_${s}`;
  return `${s}.png`;
}
