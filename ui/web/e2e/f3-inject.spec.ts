import { expect, type Locator, type Page, test } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { E2E_TOKEN } from "../playwright.config";
import inject from "../src/generated/inject.json" with { type: "json" };

// F3 第二步：注入实测（THREAT_MODEL §2.3）。后端托管 dist、带 CSP、canvas renderer，走真实产品路径。
// 载荷和 CSV 都来自 inject.json（tests/fake_llm.py 的 INJECT_PAYLOADS + csv.writer），这里不手拼。
// 三轮：inject-bar（宽表 + 长表两张图）、inject-pie、inject-error（无图，chart_error 进 warnings）。
// canvas 上画了什么靠包一层 fillText / strokeText 记录（原样转调，不改行为）；P4、P5 按渲染位置判"解析 / 未解析"。
const P = inject.payloads;
const auth = { Authorization: `Bearer ${E2E_TOKEN}` };

type Draw = { m: string; text: string; x: number; y: number; font: string; align: string; chart: number; cw: number; ch: number; phase: string };
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
// 饼图：左侧竖排是图例，其余是扇区标签；直角坐标系：底部是图例，align=center 且在下半部是类目轴标签，
// align=right 是 y 轴刻度数字，剩下的是轴名。
type Pos = "title" | "legend" | "xAxisLabel" | "axisName" | "pieLabel" | "tooltip" | "yTick";
function posOf(d: Draw, pie: boolean): Pos {
  if (d.font.startsWith("bold")) return "title";
  if (pie) return d.x < 100 && d.align === "left" ? "legend" : "pieLabel";
  if (d.y > d.ch - 30) return "legend";
  if (d.align === "right") return "yTick";
  if (d.align === "center" && d.y > d.ch * 0.6) return "xAxisLabel";
  return "axisName";
}

test("注入：图表各位置、tooltip、警告、结论、代码面板都不执行、不成元素；P4/P5 按位置判定", async ({ page, baseURL }) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 1600, height: 1000 }); // .view 最宽 1200px，图宽到顶；类目标签隔一个画一个（见 INJECT_ORDER）
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
          m, text: String(text), x: Math.round(p.x / dpr), y: Math.round(p.y / dpr), font: this.font, align: this.textAlign,
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
            if (w.__armed) w.__added.push(el.tagName.toLowerCase());
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
    await sv.getByRole("button", { name: "提问" }).click();
    await expect(sv.getByTestId("assistant-msg").nth(i)).toContainText("（fake）结论", { timeout: 60_000 });
  }
  const msgs = sv.getByTestId("assistant-msg");
  const charts = sv.getByTestId("echart");
  await expect(charts).toHaveCount(3); // bar 宽表、bar 长表、pie
  await expect(msgs.nth(0).getByTestId("echart")).toHaveCount(2);
  await expect(msgs.nth(1).getByTestId("echart")).toHaveCount(1);
  await expect(msgs.nth(2).getByTestId("echart")).toHaveCount(0);

  // ---- DOM 面：警告、结论、代码面板按文本出现
  await expect(msgs.nth(2).locator(".warnings")).toContainText(`图表未生成：x 列 '${P.P1}' 不存在`);
  for (const k of ["P2", "P3", "P4", "P5"] as const) await expect(msgs.nth(2).locator(".warnings")).toContainText(P[k]);
  for (const i of [0, 1, 2]) for (const k of ["P1", "P2", "P3"] as const) await expect(msgs.nth(i)).toContainText(P[k]);
  for (const i of [0, 1, 2]) {
    const code = msgs.nth(i).locator("details.ev.code").first();
    await code.locator("summary").click();
    await expect(code.locator("pre")).toContainText(P.P1);
  }
  await expect(msgs.nth(0).locator("details.ev.code pre").first()).toContainText(`${P.P4} ${P.P5}`);
  const links = await sv.locator("a").evaluateAll((as) => as.map((a) => a.getAttribute("href")));
  expect(links.length).toBeGreaterThan(0); // 对照：结论里的 [点我](javascript:…) 确实渲染成了链接
  expect(links.filter((h) => h && /javascript:/i.test(h))).toEqual([]);

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
    const cats = inject.order.map((k) => P[k as keyof typeof P]);
    const pts = st.filter((d) => d.align === "center" && d.y > d.ch * 0.6 && cats.includes(d.text)).map((d) => [cats.indexOf(d.text), d.x]);
    const uniq = [...new Map(pts.map(([i, x]) => [i, x])).entries()];
    if (uniq.length < 2) throw new Error(`类目轴标签少于 2 个，推不出第 ${k} 列`);
    const [[i0, x0], [i1, x1]] = uniq;
    return [x0 + ((x1 - x0) / (i1 - i0)) * (k - i0), box.height * 0.5];
  };
  // 饼图：5 个扇区等分（P2 列全相等），从 12 点方向顺时针；中心 60%/55%，半径 65%（builder 的 option）
  const atSlice = (k: number) => (box: { width: number; height: number }): [number, number] => {
    const r = (Math.min(box.width, box.height) / 2) * 0.65 * 0.6;
    const a = ((90 - 72 * (k + 0.5)) * Math.PI) / 180;
    return [box.width * 0.6 + r * Math.cos(a), box.height * 0.55 - r * Math.sin(a)];
  };
  // 第 4 个参数是解析与否都会留下的片段（"{b}{c}"、"富文本"），只用来证明悬停到了；解析与否在下面按位置判
  const idx = (k: string) => inject.order.indexOf(k);
  await hover(0, "t-bar-P4", atCategory(idx("P4")), "{b}{c}"); // 宽表：类目 P4 进 tooltip 表头，系列名 P2/P3 进行
  await hover(0, "t-bar-P5", atCategory(idx("P5")), "富文本");
  await hover(1, "t-series-P1", atCategory(idx("P1")), "富文本"); // 长表：系列名（单元格值 P1–P5）进 tooltip 行
  await hover(2, "t-pie-P4", atSlice(idx("P4")), "{b}{c}"); // 饼图：扇区名进 tooltip
  await hover(2, "t-pie-P5", atSlice(idx("P5")), "富文本");
  await page.mouse.move(1, 1);

  // ---- P4 / P5 按位置判定
  const all = await draws();
  writeFileSync(test.info().outputPath("draws.json"), JSON.stringify(all));
  type Verdict = { raw: boolean; parsed: boolean };
  const verdict: Record<string, Verdict> = {};
  const note = (key: string, d: Draw[]) => {
    const t = d.map((x) => x.text);
    const v = verdict[key] ?? { raw: false, parsed: false };
    if (key.startsWith("P4")) {
      v.raw ||= t.some((s) => s.includes(P.P4));
      // 被当成模板替换（{a} 变成了系列名 / 数值），或被当成富文本切开（画出 "{a" 这类残片）都算解析
      v.parsed ||= t.some((s) => !s.includes(P.P4) && /\{a\b|\{b\}\{c\}\}|^\{a$/.test(s));
    } else {
      v.raw ||= t.some((s) => s.includes(P.P5));
      v.parsed ||= t.some((s) => s.includes("富文本") && !s.includes(P.P5));
    }
    verdict[key] = v;
  };
  for (const chart of [0, 1, 2]) {
    const pie = chart === 2;
    const st = all.filter((d) => d.chart === chart && d.phase === "static");
    const stKeys = new Set(st.map((d) => `${d.text}|${d.x}|${d.y}|${d.font}`));
    const byPos = new Map<Pos, Draw[]>();
    for (const d of st) byPos.set(posOf(d, pie), [...(byPos.get(posOf(d, pie)) ?? []), d]);
    byPos.set("tooltip", all.filter((d) => d.chart === chart && d.phase.startsWith("t-") && !stKeys.has(`${d.text}|${d.x}|${d.y}|${d.font}`)));
    for (const [pos, ds] of byPos) {
      if (pos === "yTick") continue;
      const hit4 = ds.filter((d) => d.text.includes("{a") || d.text.includes("{b}") || d.text.includes(P.P4));
      const hit5 = ds.filter((d) => d.text.includes("富文本"));
      if (hit4.length) note(`P4 ${pos}`, hit4);
      if (hit5.length) note(`P5 ${pos}`, hit5);
    }
  }
  writeFileSync(test.info().outputPath("verdict.json"), JSON.stringify(verdict, null, 1));
  // 实测结论（echarts 6.1.0）。改了这张表就要同步改 THREAT_MODEL §2.3；升级 echarts 时这里会红，按新现象重判。
  // 变更纪律：每改一格，都要在那个 commit 里写清楚这个位置的行为为什么变了（prepare 上线后 tooltip 变成不解析、主题给 axisLabel /
  // series.label 配了 rich 后变成解析，都属于正确的红）。不准"红了就改期望值"。如果规范化改变了字符串本身，要改的是判据（note()），不是期望值。
  const R = { raw: true, parsed: false };
  const PARSED = { raw: false, parsed: true };
  expect(verdict).toEqual({
    "P4 title": R, "P4 axisName": R, "P4 xAxisLabel": R, "P4 legend": R, "P4 pieLabel": R, "P4 tooltip": PARSED,
    "P5 title": R, "P5 xAxisLabel": R, "P5 legend": R, "P5 pieLabel": R, "P5 tooltip": PARSED,
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
