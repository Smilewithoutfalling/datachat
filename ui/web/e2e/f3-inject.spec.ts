import { expect, type Locator, type Page, test } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { E2E_TOKEN } from "../playwright.config";
import inject from "../src/generated/inject.json" with { type: "json" };

// F3 第二步：注入实测（THREAT_MODEL §2.3）。后端托管 dist、带 CSP、canvas renderer，走真实产品路径。
// 载荷和 CSV 都来自 inject.json（tests/fake_llm.py 的 INJECT_PAYLOADS + csv.writer），这里不手拼。
// 三轮：inject-bar（宽表 + 长表两张图）、inject-pie、inject-error（无图，chart_error 进 warnings）。
// P6（借样式伪造数值）、P7（换行改行归属）是第二步实测出的最高级威胁的回归（F3 第三步）。
// canvas 上画了什么靠包一层 fillText / strokeText 记录（原样转调，不改行为）；P4、P5 按渲染位置判"解析 / 未解析"。
const P = inject.payloads;
// 第三步起画布上画的是后端 _display_safe 之后的串（{ } → 全角，\n → 空格），期望显示串由后端算好放在 inject.json，这里不另写规范化
const D = inject.display;
const auth = { Authorization: `Bearer ${E2E_TOKEN}` };

// align 和 w（measureText 宽度）必须同时记：x 的含义取决于 textAlign（left 是起点、center 是中点、right 是终点），只记 x 判不了是否出界
type Draw = { m: string; text: string; x: number; y: number; w: number; font: string; align: string; chart: number; cw: number; ch: number; phase: string };
type Win = { __draws: Draw[]; __phase: string; __armed: boolean; __added: string[]; __badAttrs: string[]; __csp: string[]; __pwned?: unknown };

async function setScenario(page: Page, model: string) {
  const r = await page.request.put("/settings", { headers: auth, data: { model } });
  expect((await r.json()).model).toBe(model);
}

// 连续两次截图逐字节相同才算稳定（入场动画、tooltip 过渡都会让单次截图时机不确定）；不改产品的 animation。
async function stableShot(el: Locator, label: string): Promise<Buffer> {
  let prev = await el.screenshot();
  for (let i = 0; i < 30; i++) {
    await el.page().waitForTimeout(150);
    const cur = await el.screenshot();
    if (cur.equals(prev)) return cur;
    prev = cur;
  }
  writeFileSync(test.info().outputPath(`unstable-${label}.png`), prev);
  throw new Error(`画面 30 次内没有稳定：${label}`);
}

// 渲染位置分类（echarts 6.1.0 默认布局，由本测试的记录确认）：标题是 bold 18px；tooltip 是悬停阶段新出现的绘制；
// 饼图：左侧竖排是图例，其余是扇区标签；直角坐标系：底部是图例，align=right 是 y 轴刻度数字。
// 第四步改判（轴名移位）：x 轴名改为轴下方居中（nameLocation='middle'），同样是 align=center、在下半部——
// 只按"center + 下半部"会把 x 轴名算成类目标签，P4（既是类目又是 x 轴名）的 axisName 一格就丢了，类目标签的前提也会被轴名冒充。
// 所以按行分：下半部 align=center 的最上一行（labelY，实测 279）是类目标签，比它低的那一行（实测 299）是 x 轴名。
// y 轴名左对齐、在顶部（实测 y=66），归 axisName。
type Pos = "title" | "legend" | "xAxisLabel" | "axisName" | "pieLabel" | "tooltip" | "yTick";
function xLabelRow(st: Draw[]): number {
  // 纯数字不算：第五步开关全开时，柱顶数值标签和极值标记也是下半部居中的文字，会被误当成类目行（实测 P4 因此被分到 axisName）
  const ys = st.filter((d) => !d.font.startsWith("bold") && d.align === "center" && d.y > d.ch * 0.6 && !/^-?[\d.,]+$/.test(d.text)).map((d) => d.y);
  return ys.length ? Math.min(...ys) : Infinity;
}
// 第五步"开关全开"那一轮：图例位置开关把多系列图的图例挪到顶部（标题下方、y 轴名上方，实测 y < 40）
let legendTop = false;
function posOf(d: Draw, pie: boolean, labelY = Infinity): Pos {
  if (d.font.startsWith("bold")) return "title";
  if (pie) return d.x < 100 && d.align === "left" ? "legend" : "pieLabel";
  if (legendTop && d.align === "left" && d.y < 40) return "legend";
  // 图例在底部；第三步起长表有 7 个系列，图例折成两行（实测 y=326、348，ch=360），所以不能只认最底下 30px。
  if (d.y > d.ch - 30 || (d.align === "left" && d.y > d.ch * 0.85)) return "legend";
  if (d.align === "right") return "yTick";
  if (d.align === "center" && d.y > d.ch * 0.6) return Math.abs(d.y - labelY) <= 2 ? "xAxisLabel" : "axisName";
  return "axisName";
}


// 第四步：默认主题和暗色画布各跑一遍。主题不设 rich / formatter，判定表不随主题变；哪天主题配了 rich，这里变红是对的（纪律③）
// 第五步：再加一轮"经典 + 全部开关开启"（偏好按图型写进 localStorage）。开关只写字面量，判定表应不变。
const ALL_ON = { label: true, legend: "top", stack: true, smooth: true, gradient: true, radius: true, sort: "desc", marks: true, zoom: true };
for (const [theme, switchesOn] of [["classic", false], ["darkCanvas", false], ["classic", true]] as const)
test(`注入（主题 ${theme}${switchesOn ? "，开关全开" : ""}）：图表各位置、tooltip、警告、结论、代码面板都不执行、不成元素；P4/P5 按位置判定`, async ({ page, baseURL }) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 1600, height: 1000 }); // 对话列最宽 1214（V2a 照改版前的图宽定），图宽到顶 1174；类目标签隔一个画一个（见 INJECT_ORDER）
  const origin = new URL(baseURL!).origin;
  const external: string[] = [];
  const sameOriginAssets: string[] = [];
  const dialogs: string[] = [];
  page.on("request", (req) => {
    const u = new URL(req.url());
    if (u.protocol === "data:" || u.protocol === "blob:") return;
    if (u.origin !== origin) external.push(req.url());
    else if (u.pathname.startsWith("/assets/")) sameOriginAssets.push(u.pathname);
  });
  page.on("dialog", (d) => {
    dialogs.push(d.message());
    void d.dismiss();
  });
  await page.addInitScript((t) => localStorage.setItem("datachat.chartTheme", t), theme);
  legendTop = switchesOn;
  if (switchesOn)
    await page.addInitScript((sw) => { for (const k of ["bar", "pie"]) localStorage.setItem(`datachat.chartUi:${k}`, JSON.stringify(sw)); }, ALL_ON);
  await page.addInitScript(() => {
    const w = window as unknown as Win;
    w.__draws = [];
    w.__phase = "static";
    w.__added = [];
    w.__armed = false; // index.html 自己的 <script type=module> 在页面加载时插入，不算；页面就绪后才开始记新增元素
    w.__badAttrs = [];
    w.__csp = [];
    document.addEventListener("securitypolicyviolation", (e) => w.__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
    for (const m of ["fillText", "strokeText"] as const) {
      const orig = CanvasRenderingContext2D.prototype[m];
      CanvasRenderingContext2D.prototype[m] = function (this: CanvasRenderingContext2D, text: string, x: number, y: number, maxWidth?: number) {
        const p = this.getTransform().transformPoint(new DOMPoint(x, y));
        const host = this.canvas.closest(".echart");
        const dpr = window.devicePixelRatio || 1;
        w.__draws.push({
          m, text: String(text), x: Math.round(p.x / dpr), y: Math.round(p.y / dpr), w: this.measureText(String(text)).width, font: this.font, align: this.textAlign,
          chart: host ? [...document.querySelectorAll(".echart")].indexOf(host) : -1,
          cw: this.canvas.width / dpr, ch: this.canvas.height / dpr, phase: w.__phase,
        });
        return maxWidth === undefined ? orig.call(this, text, x, y) : orig.call(this, text, x, y, maxWidth);
      };
    }
    const attrBad = (el: Element) => {
      for (const a of [...el.attributes]) {
        if (/^on/i.test(a.name) || (/^(href|src|xlink:href|action|formaction)$/i.test(a.name) && /^\s*javascript:/i.test(a.value)))
          w.__badAttrs.push(`${el.tagName}@${a.name}=${a.value}`);
      }
    };
    new MutationObserver((recs) => {
      for (const r of recs) {
        if (r.type === "attributes" && r.target instanceof Element) attrBad(r.target);
        r.addedNodes.forEach((n) => {
          if (!(n instanceof Element)) return;
          for (const el of [n, ...n.querySelectorAll("*")]) {
            // V2a 起产品用内联 SVG 图标（icons.tsx，源码里写死的静态标记，全部带 data-icon）；只放过这些，别的 <svg> 照样记
            if (w.__armed && !el.closest("svg[data-icon]")) w.__added.push(el.tagName.toLowerCase());
            attrBad(el);
          }
        });
      }
    }).observe(document, { childList: true, subtree: true, attributes: true });
  });

  await page.goto(`/#token=${E2E_TOKEN}`);
  await expect(page.getByLabel("选择 CSV 文件")).toBeVisible();
  await page.evaluate(() => ((window as unknown as Win).__armed = true));
  await page.getByLabel("选择 CSV 文件").setInputFiles([{ name: "inject.csv", mimeType: "text/csv", buffer: Buffer.from(inject.csv) }]);
  await page.getByRole("button", { name: "上传" }).click();
  await page.getByTestId("dataset-view").getByRole("button", { name: "新建会话" }).click();
  const sv = page.getByTestId("session-view");
  const rounds = ["inject-bar", "inject-pie", "inject-error"];
  for (const [i, model] of rounds.entries()) {
    await setScenario(page, model);
    await sv.getByLabel("提问").fill(`注入 ${model}`);
    await sv.getByRole("button", { name: "发送" }).click();
    await expect(sv.getByTestId("assistant-msg").nth(i)).toContainText("（fake）结论", { timeout: 60_000 });
  }
  const msgs = sv.getByTestId("assistant-msg");
  const charts = sv.getByTestId("echart");
  await expect(charts).toHaveCount(3); // bar 宽表、bar 长表、pie
  for (const el of await charts.all()) await expect(el).toHaveAttribute("data-theme", theme);
  await expect(msgs.nth(0).getByTestId("echart")).toHaveCount(2);
  await expect(msgs.nth(1).getByTestId("echart")).toHaveCount(1);
  await expect(msgs.nth(2).getByTestId("echart")).toHaveCount(0);

  // ---- DOM 面：警告、结论、代码面板按文本出现
  // P1-17（阶段 5 收尾 D，判定表改动）：ChartError 原文只回到模型，警告是固定文案，不再带任何载荷
  await expect(msgs.nth(2).locator(".warnings")).toContainText("图没画出来：模型给的画图参数和结果数据对不上。");
  for (const k of ["P1", "P2", "P3", "P4", "P5"] as const) await expect(msgs.nth(2).locator(".warnings")).not.toContainText(P[k]);
  for (const i of [0, 1, 2]) for (const k of ["P1", "P2", "P3"] as const) await expect(msgs.nth(i)).toContainText(P[k]);
  for (const i of [0, 1, 2]) {
    await msgs.nth(i).getByRole("button", { name: "查看过程" }).click(); // V2a §2.3：过程默认折叠
    const code = msgs.nth(i).locator("details.ev.code").first();
    await code.locator("summary").click();
    await expect(code.locator("pre")).toContainText(P.P1);
  }
  await expect(msgs.nth(0).locator("details.ev.code pre").first()).toContainText(`${P.P4} ${P.P5}`);
  // 验收 P0-4 起：危险协议链接只留文字（span.md-link-blocked），不再是 <a>。对照：「点我」确实渲染出来了，只是不可点
  const links = await sv.locator("a").evaluateAll((as) => as.map((a) => a.getAttribute("href")));
  expect(links.filter((h) => h && /javascript:/i.test(h))).toEqual([]);
  await expect(sv.locator(".md-link-blocked", { hasText: "点我" }).first()).toBeVisible();
  expect(await sv.locator("a", { hasText: "点我" }).count()).toBe(0);

  // ---- 画面稳定后取静态绘制记录
  const shots: Buffer[] = [];
  for (const i of [0, 1, 2]) {
    await charts.nth(i).scrollIntoViewIfNeeded();
    shots.push(await stableShot(charts.nth(i), `static-${i}`));
  }

  // ---- tooltip 真机悬停：每处都要 fillText 里出现被悬停的名字（确定性对照），像素和悬停前不同（证明真画出来了）
  const draws = () => page.evaluate(() => (window as unknown as Win).__draws);
  const staticOf = async (chart: number) => (await draws()).filter((d) => d.chart === chart && d.phase === "static");
  const hover = async (chart: number, label: string, at: (box: { x: number; y: number; width: number; height: number }, st: Draw[]) => [number, number], expectText: string) => {
    await page.mouse.move(1, 1);
    await charts.nth(chart).scrollIntoViewIfNeeded();
    const before = await stableShot(charts.nth(chart), `before-${label}`);
    const box = (await charts.nth(chart).boundingBox())!;
    await page.evaluate((ph) => ((window as unknown as Win).__phase = ph), label);
    const [x, y] = at(box, await staticOf(chart));
    await page.mouse.move(box.x + x, box.y + y);
    await expect.poll(async () => {
      const st = new Set((await staticOf(chart)).map((d) => `${d.text}|${d.x}|${d.y}|${d.font}`));
      return (await draws()).filter((d) => d.phase === label && d.chart === chart && !st.has(`${d.text}|${d.x}|${d.y}|${d.font}`))
        .map((d) => d.text).join("");
    }, { message: `tooltip ${label} 没画出 ${expectText}` }).toContain(expectText);
    const after = await stableShot(charts.nth(chart), `after-${label}`);
    expect(after.equals(before), `悬停 ${label} 前后像素相同`).toBe(false);
  };
  // 类目轴：按画出来的类目标签横坐标找第 k 个类目的中心（标签与柱子同一列）
  const atCategory = (k: number) => (box: { height: number }, st: Draw[]): [number, number] => {
    // 标签放不下时 echarts 自动隔一个画一个，所以用画出来的标签（类目下标已知）线性推出第 k 列的横坐标
    const cats = inject.order.map((k) => D[k as keyof typeof D]);
    const pts = st.filter((d) => d.align === "center" && d.y > d.ch * 0.6 && cats.includes(d.text)).map((d) => [cats.indexOf(d.text), d.x]);
    const uniq = [...new Map(pts.map(([i, x]) => [i, x])).entries()];
    if (uniq.length < 2) throw new Error(`类目轴标签少于 2 个，推不出第 ${k} 列`);
    const [[i0, x0], [i1, x1]] = uniq;
    return [x0 + ((x1 - x0) / (i1 - i0)) * (k - i0), box.height * 0.5];
  };
  // 饼图：N 个扇区等分（P2 列全相等），从 12 点方向顺时针；中心 60%/55%，半径 65%（builder 的 option）
  const sliceDeg = 360 / inject.order.length;
  const atSlice = (k: number) => (box: { width: number; height: number }): [number, number] => {
    const r = (Math.min(box.width, box.height) / 2) * 0.65 * 0.6;
    const a = ((90 - sliceDeg * (k + 0.5)) * Math.PI) / 180;
    return [box.width * 0.6 + r * Math.cos(a), box.height * 0.55 - r * Math.sin(a)];
  };
  // 第 4 个参数只用来证明悬停到了（第三步起是后端规范化后的显示串）；解析与否在下面按位置判
  const idx = (k: string) => inject.order.indexOf(k);
  await hover(0, "t-bar-P4", atCategory(idx("P4")), D.P4); // 宽表：类目 P4 进 tooltip 表头，系列名 P2/P3 进行
  await hover(0, "t-bar-P5", atCategory(idx("P5")), "富文本");
  await hover(0, "t-bar-P6", atCategory(idx("P6")), D.P6); // 借样式：表头是 P6
  await hover(1, "t-series-P1", atCategory(idx("P1")), "富文本"); // 长表：系列名（单元格值 P1–P7）进 tooltip 行
  // 换行：长表第 i 行的系列是 order[i+1]，所以 P7 这个系列只在它前一个类目上有值；悬停那里，P7 那一行带真值
  await hover(1, "t-series-P7", atCategory(idx("P7") - 1), D.P7);
  await hover(2, "t-pie-P4", atSlice(idx("P4")), D.P4); // 饼图：扇区名进 tooltip
  await hover(2, "t-pie-P5", atSlice(idx("P5")), "富文本");
  await page.mouse.move(1, 1);

  // ---- P4 / P5 按位置判定
  const all = await draws();
  writeFileSync(test.info().outputPath("draws.json"), JSON.stringify(all));

  // 前提：P4–P7 都画在宽表的类目轴标签位置上（INJECT_ORDER 的排布），否则类目轴这个位置的结论不完整
  const st0 = all.filter((d) => d.chart === 0 && d.phase === "static");
  expect(st0[0]?.cw).toBe(1174); // 前提：图宽与改版前一致（V2a 改了对话列宽度，这里钉住）
  const xLabels0 = st0.filter((d) => posOf(d, false, xLabelRow(st0)) === "xAxisLabel").map((d) => d.text);
  for (const k of ["P4", "P5", "P6", "P7"] as const) expect([k, xLabels0.includes(D[k])]).toEqual([k, true]);
  // 前提（第四步，防假绿）：每个载荷都确实画出来了——没有 fillText 记录就谈不上"没被解析"。
  // 'all' 会改变 hideOverlap 的类目标签集合，且集合依赖运行宽度：任何一个载荷掉出绘制，这里先红，而不是在判定表里静默变少
  const drawn = all.filter((d) => d.phase === "static").map((d) => d.text);
  for (const k of ["P1", "P2", "P3", "P4", "P5", "P6", "P7"] as const)
    expect([k, drawn.some((t) => t.includes(D[k]))]).toEqual([k, true]);
  // x 轴名（P4）这一行确实存在且与类目行分开，否则 axisName 一格是从别处来的
  expect(st0.filter((d) => posOf(d, false, xLabelRow(st0)) === "axisName" && d.align === "center").map((d) => d.text)).toContain(D.P4);
  // 上面的分类器靠 |y - labelY| <= 2 区分两行，前提是轴名行与类目行至少隔 8px（nameGap 28 是实测调的；
  // 主题将来加 axisLabel.fontSize 时，这里先红并直说"间距不够"，而不是只报 P4 位置不对）
  const xNameRowY = Math.min(...st0.filter((d) => d.text === D.P4 && posOf(d, false, xLabelRow(st0)) === "axisName").map((d) => d.y));
  expect(xNameRowY - xLabelRow(st0)).toBeGreaterThanOrEqual(8);

  // tooltip 新增绘制（悬停阶段出现、静态阶段没有的）
  const tipDraws = (chart: number, phase: string) => {
    const st = new Set(all.filter((d) => d.chart === chart && d.phase === "static").map((d) => `${d.text}|${d.x}|${d.y}|${d.font}`));
    return all.filter((d) => d.chart === chart && d.phase === phase && !st.has(`${d.text}|${d.x}|${d.y}|${d.font}`));
  };
  // P6：悬停确实命中（显示串作为一段画出来），且任何 tooltip 里都没有以 900 字重画出的 "999"（借样式伪造数值已不可能）
  expect(tipDraws(0, "t-bar-P6").some((d) => d.text.includes(D.P6))).toBe(true);
  const fake999 = all.filter((d) => d.phase.startsWith("t-") && d.text === "999" && /\b900\b/.test(d.font));
  expect(fake999).toEqual([]);
  // P7：tooltip 每一帧里 "上 下" 都是一次画完、不拆行（tooltip 过渡期间会重绘多帧，所以按"每次绘制"判，不按次数）；
  // 它那一行的真值（P2 列恒为 2）与它同一个 y
  const t7 = tipDraws(1, "t-series-P7");
  const t7label = t7.filter((d) => d.text.includes("上") || d.text.includes("下"));
  expect(t7label.length).toBeGreaterThan(0);
  expect([...new Set(t7label.map((d) => d.text))]).toEqual([D.P7]);
  const valueYs = new Set(t7.filter((d) => d.text === "2").map((d) => d.y));
  expect(t7label.filter((d) => !valueYs.has(d.y))).toEqual([]);
  type Verdict = { raw: boolean; parsed: boolean };
  const verdict: Record<string, Verdict> = {};
  const note = (key: string, d: Draw[]) => {
    const t = d.map((x) => x.text);
    const v = verdict[key] ?? { raw: false, parsed: false };
    // 判据（第三步改）：raw = 画出了后端给的完整显示串 display[P]（规范化后不再含 ASCII { }）；
    // parsed = 只剩残片：被当成模板替换（{a} 变成别的）或被富文本切开（画出 "{a" / "富文本" 而没有完整串）
    if (key.startsWith("P4")) {
      v.raw ||= t.some((s) => s.includes(D.P4));
      v.parsed ||= t.some((s) => /\{a\b|\{b\}\{c\}\}|^\{a$/.test(s));
    } else {
      v.raw ||= t.some((s) => s.includes(D.P5));
      v.parsed ||= t.some((s) => s.includes("富文本") && !s.includes(D.P5));
    }
    verdict[key] = v;
  };
  for (const chart of [0, 1, 2]) {
    const pie = chart === 2;
    const st = all.filter((d) => d.chart === chart && d.phase === "static");
    const stKeys = new Set(st.map((d) => `${d.text}|${d.x}|${d.y}|${d.font}`));
    const byPos = new Map<Pos, Draw[]>();
    const ly = xLabelRow(st);
    for (const d of st) byPos.set(posOf(d, pie, ly), [...(byPos.get(posOf(d, pie, ly)) ?? []), d]);
    byPos.set("tooltip", all.filter((d) => d.chart === chart && d.phase.startsWith("t-") && !stKeys.has(`${d.text}|${d.x}|${d.y}|${d.font}`)));
    for (const [pos, ds] of byPos) {
      if (pos === "yTick") continue;
      const hit4 = ds.filter((d) => d.text.includes("{a") || d.text.includes("{b}") || d.text.includes(D.P4));
      const hit5 = ds.filter((d) => d.text.includes("富文本"));
      if (hit4.length) note(`P4 ${pos}`, hit4);
      if (hit5.length) note(`P5 ${pos}`, hit5);
    }
  }
  writeFileSync(test.info().outputPath("verdict.json"), JSON.stringify(verdict, null, 1));
  // 实测结论（echarts 6.1.0）。改了这张表就要同步改 THREAT_MODEL §2.3；升级 echarts 时这里会红，按新现象重判。
  // 第三步变更：tooltip 两格 PARSED → R。原因：后端 _display_safe 把 { } 规范化为全角，richText 包装不再能被提前闭合。
  // 变更纪律：每改一格，都要在那个 commit 里写清楚这个位置的行为为什么变了（prepare 上线后 tooltip 变成不解析、主题给 axisLabel /
  // series.label 配了 rich 后变成解析，都属于正确的红）。不准"红了就改期望值"。如果规范化改变了字符串本身，要改的是判据（note()），不是期望值。
  const R = { raw: true, parsed: false };
  expect(verdict).toEqual({
    "P4 title": R, "P4 axisName": R, "P4 xAxisLabel": R, "P4 legend": R, "P4 pieLabel": R, "P4 tooltip": R,
    "P5 title": R, "P5 xAxisLabel": R, "P5 legend": R, "P5 pieLabel": R, "P5 tooltip": R,
  });

  // ---- 执行面 / DOM 面断言
  const w = await page.evaluate(() => {
    const x = window as unknown as Win;
    return { pwned: x.__pwned, added: x.__added, bad: x.__badAttrs, csp: x.__csp };
  });
  expect(w.pwned).toBeUndefined();
  expect(dialogs).toEqual([]);
  expect(w.bad).toEqual([]);
  expect(w.added.length).toBeGreaterThan(20); // 对照：观察器确实在记
  expect(w.added.filter((t) => ["img", "svg", "script", "iframe", "object", "embed", "foreignobject"].includes(t))).toEqual([]);
  for (const el of await charts.all()) {
    expect(await el.evaluate((n) => n.textContent)).toBe("");
    expect(await el.evaluate((n) => [...new Set([...n.querySelectorAll("*")].map((c) => c.tagName.toLowerCase()))].sort())).toEqual(["canvas", "div"]);
  }
  expect(w.csp).toEqual([]);
  expect(external).toEqual([]);
  expect(sameOriginAssets.length).toBeGreaterThan(0);
  expect(shots).toHaveLength(3);
});
