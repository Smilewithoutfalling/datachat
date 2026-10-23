// V2b B3（phase5「阶段 5 收尾」B3）：标记卡「文字」组的标题输入。这是"UiState 只存编号、数值、枚举，用户串不进 option"
// （switches.ts 头注释，S 10-19）的第一处、也是唯一一处例外：`Edit.title`。规则写死：
// 1. 进 option 只写 title.text 一处，写之前过 sanitizeTitle；屏幕和导出走同一条 prepare，两边是同一个串。
// 2. sanitizeTitle：C0 / C1 控制字符和 DEL、U+2028 / U+2029、Bidi 控制符一律换空格；DISPLAY_UNSAFE（后端 charts.py 同一份，
//    经 chart_schema.json 的 display 导出）里的 { } 换全角、\n 换空格；首尾去空白；限长 TITLE_MAX（= 后端 100），超出按码点
//    截断加「…」，和后端 _clean_str 同一种截法。清完是空串 = 没设置（null）。
//    后端 _CTRL 不含 Bidi，这里比后端严：标题会进导出文件名，Bidi 能让文件名显示成别的扩展名。Bidi 表是前端独有的，不导出。
// 3. localStorage 读回时 parseEdit 要求 sanitizeTitle(v) === v（存进去的永远是清过的串），不等就丢掉这个字段。
// 4. canvas 渲染，不进 DOM；组头「当前值」是 React 文本节点（自动转义）；不碰 document.title；导出文件名仍经 safeFilename。
import schema from "../generated/chart_schema.json";

const DISPLAY = schema.display as { unsafe: Record<string, string>; title_max: number };
export const TITLE_MAX = DISPLAY.title_max;
// eslint-disable-next-line no-control-regex -- 换掉控制字符正是这条正则的用途
const CTRL = /[\u0000-\u001f\u007f-\u009f\u2028\u2029\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/gu;

/** 用户输入的标题 → 可以写进 title.text 的串；空串 = 没设置。 */
export function sanitizeTitle(raw: string): string {
  let s = raw.replace(CTRL, " ");
  for (const [bad, good] of Object.entries(DISPLAY.unsafe)) s = s.split(bad).join(good);
  s = s.trim();
  const cps = Array.from(s);
  return cps.length <= TITLE_MAX ? s : cps.slice(0, TITLE_MAX - 1).join("") + "…";
}

/** 存储里的 title 是否合法：string、≤ TITLE_MAX 个码点、非空、且已经是清洗过的样子。 */
export function isCleanTitle(v: unknown): v is string {
  return typeof v === "string" && v !== "" && Array.from(v).length <= TITLE_MAX && sanitizeTitle(v) === v;
}
